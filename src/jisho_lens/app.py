"""Jisho Lens tray application (Phase 1).

Flow: hotkey -> frozen, dimmed screen -> drag a rectangle -> OCR in the background ->
always-on-top window with the Japanese text (Edit / Copy / Re-capture / Retry).
"""

from __future__ import annotations

import getpass
import logging
import sys

from PIL import Image
from PySide6.QtCore import QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from jisho_lens import __version__
from jisho_lens.core.capture import Rect, grab_desktop, grab_rect
from jisho_lens.core.displays import describe_displays, enable_per_monitor_dpi_awareness
from jisho_lens.core.hotkey import HotkeyManager
from jisho_lens.core.logs import setup_logging
from jisho_lens.core.ocr.worker import OcrOutcome, OcrService
from jisho_lens.core.settings import Settings
from jisho_lens.ui.capture_overlay import CaptureOverlay
from jisho_lens.ui.icons import app_icon
from jisho_lens.ui.main_window import MainWindow
from jisho_lens.ui.settings_window import SettingsWindow

log = logging.getLogger("jisho_lens")

_INSTANCE_NAME = f"mc-jisho-lens-{getpass.getuser()}"


def _another_instance_running() -> bool:
    """If the app is already running, ask it to show its window and return True."""
    sock = QLocalSocket()
    sock.connectToServer(_INSTANCE_NAME)
    if sock.waitForConnected(300):
        sock.write(b"show")
        sock.waitForBytesWritten(300)
        sock.disconnectFromServer()
        return True
    return False


class JishoLens:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.settings = Settings.load()
        self._overlay: CaptureOverlay | None = None
        self._last_image: Image.Image | None = None
        self._pending_job: int | None = None
        self._settings_window: SettingsWindow | None = None

        # single instance server
        QLocalServer.removeServer(_INSTANCE_NAME)
        self.server = QLocalServer()
        self.server.listen(_INSTANCE_NAME)
        self.server.newConnection.connect(self._on_instance_message)

        # The main window holds a Qt WebEngine view (~590 MB committed), so it is created on
        # first use rather than at startup; the app idles in the tray much lighter.
        self._window: MainWindow | None = None

        self.ocr = OcrService()
        self.ocr.finished.connect(self._on_ocr_finished)
        self.ocr.failed.connect(self._on_ocr_failed)
        self.ocr.engine_ready.connect(
            lambda name, s: log.info("engine %s ready (%.1fs)", name, s))
        self.ocr.engine_failed.connect(self._on_engine_failed)
        self.ocr.preload(self.settings.ocr.engine)

        self._build_tray()

        self.hotkeys = HotkeyManager(app)
        self.hotkeys.pressed.connect(self.start_capture)
        self.hotkey_ok, message = self.hotkeys.register(self.settings.capture.hotkey)
        if self.hotkey_ok:
            self.tray.showMessage("Jisho Lens", f"Running. Press {message} to capture text.",
                                  app_icon(), 4000)
        else:
            self.tray.showMessage("Jisho Lens", f"Hotkey not set: {message}. Open Settings.",
                                  app_icon(), 6000)
        self._update_tray_tooltip()

    @property
    def window(self) -> MainWindow:
        if self._window is None:
            w = MainWindow(self.settings.window.font_size)
            w.setWindowIcon(app_icon())
            w.restore_geometry(self.settings.window.geometry)
            w.set_engine_preset(self.settings.ocr.engine, self.settings.ocr.preset)
            w.recapture_requested.connect(self.start_capture)
            w.retry_requested.connect(self._retry)
            w.settings_requested.connect(self.open_settings)
            w.geometry_changed.connect(self._save_geometry)
            self._window = w
        return self._window

    def show_window(self) -> None:
        self.window.present()

    # ---------- tray ----------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self.app)
        menu = QMenu()
        menu.addAction("Capture text", self.start_capture)
        menu.addAction("Show window", self.show_window)
        menu.addSeparator()
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self._window is not None and self._window.isVisible():
                self._window.hide()
            else:
                self.show_window()

    def _update_tray_tooltip(self) -> None:
        hk = self.hotkeys.current or "no hotkey"
        self.tray.setToolTip(f"Jisho Lens {__version__} — {hk}")

    def _on_instance_message(self) -> None:
        conn = self.server.nextPendingConnection()
        conn.waitForReadyRead(300)
        if bytes(conn.readAll()) == b"show":
            self.show_window()
        conn.disconnectFromServer()

    # ---------- capture ----------
    def start_capture(self) -> None:
        if self._overlay is not None:
            return  # already selecting
        try:
            shot = grab_desktop()  # main window is excluded from captures
        except Exception:  # noqa: BLE001
            log.exception("screenshot failed")
            self.tray.showMessage("Jisho Lens", "Screenshot failed.", app_icon(), 3000)
            return
        self._overlay = CaptureOverlay(shot, lambda rect: self._on_selected(shot, rect))
        self._overlay.show()

    def _on_selected(self, shot, rect: Rect | None) -> None:
        self._overlay = None
        if rect is None:
            return
        delay = self.settings.capture.delay_seconds
        self.window.present()
        if delay > 0:
            self.window.show_busy(f"Waiting {delay:g} s…")
            QTimer.singleShot(int(delay * 1000), lambda: self._read(grab_rect(rect)))
        else:
            self._read(shot.crop(rect))

    def _read(self, image: Image.Image, engine: str | None = None,
              preset: str | None = None) -> None:
        self._last_image = image
        engine = engine or self.settings.ocr.engine
        preset = preset or self.settings.ocr.preset
        self.window.set_engine_preset(engine, preset)
        self.window.show_busy(f"Reading… ({engine})")
        self.tray.setIcon(app_icon(busy=True))
        self._pending_job = self.ocr.submit(
            image, engine, preset,
            remove_key_icons=self.settings.capture.remove_key_icons,
            detect_speaker=self.settings.capture.detect_speaker,
        )

    def _retry(self, engine: str, preset: str) -> None:
        if self._last_image is None:
            self.start_capture()
            return
        self._read(self._last_image, engine, preset)

    def _on_ocr_finished(self, outcome: OcrOutcome) -> None:
        if outcome.job.job_id != self._pending_job:
            return  # an older job finished after a newer one was started
        self.tray.setIcon(app_icon())
        status = f"{outcome.job.engine} · {outcome.job.preset} · {outcome.seconds:.1f} s"
        self.window.show_text(outcome.cleaned.lines, outcome.cleaned.speaker, status)

    def _on_ocr_failed(self, job_id: int, message: str) -> None:
        if job_id != self._pending_job:
            return
        self.tray.setIcon(app_icon())
        self.window.show_message(f"OCR failed: {message}", error=True)

    def _on_engine_failed(self, name: str, message: str) -> None:
        self.tray.showMessage("Jisho Lens", f"OCR engine {name} unavailable: {message}",
                              app_icon(), 6000)

    # ---------- settings ----------
    def open_settings(self) -> None:
        if self._settings_window is not None:
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        self._settings_window = SettingsWindow(self.settings, self.hotkey_ok)
        self._settings_window.setWindowIcon(app_icon())
        self._settings_window.applied.connect(self._apply_settings)
        self._settings_window.finished.connect(lambda _: setattr(self, "_settings_window", None))
        self._settings_window.show()

    def _apply_settings(self, new: Settings) -> None:
        old = self.settings
        new.window.geometry = old.window.geometry
        self.settings = new
        if new.capture.hotkey != old.capture.hotkey or not self.hotkey_ok:
            self.hotkey_ok, message = self.hotkeys.register(new.capture.hotkey)
            if not self.hotkey_ok:
                self.tray.showMessage("Jisho Lens", f"Hotkey not set: {message}", app_icon(),
                                      6000)
                new.capture.hotkey = self.hotkeys.current or old.capture.hotkey
        if new.ocr.engine != old.ocr.engine:
            self.ocr.preload(new.ocr.engine)
        if self._window is not None:
            self._window.set_engine_preset(new.ocr.engine, new.ocr.preset)
            self._window.set_font_size(new.window.font_size)
        self.settings.save()
        self._update_tray_tooltip()

    def _save_geometry(self, geometry: list[int]) -> None:
        self.settings.window.geometry = geometry
        self.settings.save()

    # ---------- quit ----------
    def quit(self) -> None:
        self.hotkeys.unregister()
        self.ocr.shutdown()
        self.tray.hide()
        self.server.close()
        self.app.quit()


def main() -> int:
    enable_per_monitor_dpi_awareness()
    setup_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Jisho Lens")
    app.setQuitOnLastWindowClosed(False)
    if _another_instance_running():
        log.info("already running; asked the running app to show its window")
        return 0
    log.info("Jisho Lens %s starting\n%s", __version__, describe_displays())
    if not QSystemTrayIcon.isSystemTrayAvailable():
        log.error("no system tray available")
    _lens = JishoLens(app)  # noqa: F841 (keep a reference for the app's lifetime)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
