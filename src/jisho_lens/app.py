"""Jisho Lens tray application (Phase 1).

Flow: hotkey -> frozen, dimmed screen -> drag a rectangle -> OCR in the background ->
always-on-top window with the Japanese text (Edit / Copy / Re-capture / Retry).
"""

from __future__ import annotations

import getpass
import logging
import sys
import time

from PIL import Image
from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QDialog, QMenu, QSystemTrayIcon, QWidget

from jisho_lens import __version__, components
from jisho_lens.core.analysis import SPLITTING_MODES
from jisho_lens.core.analysis.pipeline import analyze_text
from jisho_lens.core.capture import Rect, grab_desktop, grab_rect
from jisho_lens.core.displays import (
    describe_displays,
    enable_per_monitor_dpi_awareness,
    get_displays,
)
from jisho_lens.core.history import HistoryStore
from jisho_lens.core.hotkey import ESC, HotkeyManager
from jisho_lens.core.logs import setup_logging
from jisho_lens.core.ocr.worker import OcrOutcome, OcrService
from jisho_lens.core.ocr_data import OcrDataStore
from jisho_lens.core.ocr_data.corrections import CorrectionStore
from jisho_lens.core.ocr_data.store import png_bytes, sample_id
from jisho_lens.core.settings import Settings
from jisho_lens.ui import winapi
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


def _screen_info() -> dict:
    try:
        d = get_displays()[0]
        return {"width": d.width, "height": d.height, "scale": d.scale_percent}
    except Exception:  # noqa: BLE001
        return {}


class _ChildrenOnTop(QObject):
    """Stacking of the windows that belong to the text window (History, Settings, About,
    dialogs, message boxes): in front when opened or clicked, behind when the user focuses
    something else (the text window or another app). Moving between them doesn't count."""

    def __init__(self, lens: JishoLens) -> None:
        super().__init__()
        self.lens = lens

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        kind = event.type()
        if kind in (QEvent.Type.Show, QEvent.Type.WindowActivate, QEvent.Type.WindowDeactivate) \
                and isinstance(obj, QWidget) and obj.isWindow() and self._is_child(obj):
            hwnd = int(obj.winId())
            if kind == QEvent.Type.Show:
                # not owned by the text window: an owned window can never go behind it
                if self.lens._window is not None \
                        and winapi.owner(hwnd) == int(self.lens._window.winId()):
                    winapi.set_owner(hwnd, 0)
                winapi.set_topmost(hwnd)  # in front when opened
            elif kind == QEvent.Type.WindowActivate:
                if time.monotonic() >= self.lens._settle_until:
                    winapi.set_topmost(hwnd)  # clicked / focused again: in front
            else:
                # focus moved; see where it went once Windows has finished switching
                QTimer.singleShot(50, self.lens._focus_moved)
        return False

    def _is_child(self, window: QWidget) -> bool:
        text_window = self.lens._window
        return (text_window is not None and window is not text_window
                and _descends_from(window, text_window))


def _descends_from(widget: QWidget, ancestor: QWidget) -> bool:
    """True if `ancestor` is up the parent chain, across windows (isAncestorOf stops at
    window boundaries)."""
    w = widget.parentWidget()
    while w is not None:
        if w is ancestor:
            return True
        w = w.parentWidget()
    return False


def _depth(widget: QWidget) -> int:
    n, w = 0, widget.parentWidget()
    while w is not None:
        n, w = n + 1, w.parentWidget()
    return n


class JishoLens:
    def __init__(self, app: QApplication) -> None:
        self.app = app
        self.settings = Settings.load()
        self._excluded: list = []  # child windows left out of the capture being taken
        self._settle_until = 0.0  # ignore activations until then (overlay closing)
        self._on_top = _ChildrenOnTop(self)
        app.installEventFilter(self._on_top)
        self._overlay: CaptureOverlay | None = None
        self._last_image: Image.Image | None = None
        self._pending_job: int | None = None
        self._delay_timer: QTimer | None = None  # capture delay running (Esc cancels it)
        self._settings_window: SettingsWindow | None = None
        self._history_window = None
        # History (core) and OCR data collection (opt-in, local only)
        self.history = HistoryStore()
        self.ocr_data = OcrDataStore()
        self._capture_id: int | None = None  # History row of the capture on screen
        self._sample_id: str | None = None  # OCR data sample of it, when collecting
        # Remember my corrections (only while collecting): fixes learned from Edit
        self.corrections = CorrectionStore()
        self._ocr_lines: list[str] | None = None  # text as OCR read it, before corrections
        self._applied: list = []  # corrections used on the text on screen
        if self.settings.data.collecting and not self.corrections.path.exists():
            self._learn_from_samples()
        self._tidy_ocr_data()
        self._retrying = False

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
        self._check_word_splitting()
        self._preload()

        self._build_tray()

        self.hotkeys = HotkeyManager(app)
        self.hotkeys.pressed.connect(self.start_capture)
        self.hotkeys.triggered.connect(self._on_hotkey)
        self.hotkey_ok, message = self.hotkeys.register(self.settings.capture.hotkey)
        self.show_hotkey_ok, show_message = self.hotkeys.register(
            self.settings.capture.show_hotkey, "show")
        if not self.show_hotkey_ok:
            log.warning("show-window hotkey not set: %s", show_message)
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
            ws = self.settings.window
            w = MainWindow(ws.font_size, ws.show_furigana, ws.show_romaji)
            w.setWindowIcon(app_icon())
            w.text_edited.connect(self._on_text_edited)
            w.display_changed.connect(self._on_display_changed)
            w.restore_geometry(self.settings.window.geometry)
            w.set_engine_preset(self.settings.ocr.engine, self.settings.ocr.preset)
            w.recapture_requested.connect(self.start_capture)
            w.retry_requested.connect(self._retry)
            w.settings_requested.connect(self.open_settings)
            w.confirm_requested.connect(self._on_confirm)
            w.history_requested.connect(self.open_history)
            w.undo_corrections_requested.connect(self._undo_corrections)
            w.favorite_toggled.connect(self._on_favorite)
            w.geometry_changed.connect(self._save_geometry)
            self._window = w
            # windows opened from the tray before the text window existed
            for child in (self._settings_window, self._history_window,
                          getattr(self, "_about", None)):
                if child is not None:
                    self._own(child)
        return self._window

    def _own(self, child) -> None:
        """Make `child` belong to the text window (stacking rules in _ChildrenOnTop, closing
        on a new capture). The text window is created on first use (Qt WebEngine is heavy),
        so a window opened from the tray before that is adopted when it is created."""
        if self._window is None or child.parent() is self._window:
            return
        visible, geometry = child.isVisible(), child.geometry()
        child.setParent(self._window, child.windowFlags() | Qt.WindowType.Window)
        if visible:
            child.setGeometry(geometry)
            child.show()

    def show_window(self) -> None:
        self.window.present()

    # ---------- tray ----------
    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(app_icon(), self.app)
        menu = QMenu()
        menu.addAction("Capture text", self.start_capture)
        menu.addAction("Show window", self.show_window)
        menu.addAction("History…", self.open_history)
        menu.addSeparator()
        menu.addAction("Settings…", self.open_settings)
        menu.addAction("About…", self.open_about)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def open_about(self) -> None:
        from jisho_lens.ui.about import AboutWindow

        self._about = AboutWindow()
        self._about.setWindowIcon(app_icon())
        self._about.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self._about.destroyed.connect(lambda: setattr(self, "_about", None))
        self._own(self._about)
        self._about.show()

    def _on_tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            if self._window is not None and self._window.isVisible():
                self._window.hide()
            else:
                self.show_window()

    def _update_tray_tooltip(self) -> None:
        hk = self.hotkeys.current or "no hotkey"
        show = self.hotkeys.current_for("show")
        self.tray.setToolTip(f"Jisho Lens {__version__} — capture {hk}"
                             + (f", show/hide {show}" if show else ""))

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
        if self.settings.window.on_capture == "close":
            changed = self._close_children()
        else:  # keep them open, but leave them out of the screenshot
            changed = self._exclude_children(True)
        if changed:
            # let Windows update the screen before the screenshot
            QTimer.singleShot(150, self._grab_and_select)
        else:
            self._grab_and_select()

    def _exclude_children(self, exclude: bool) -> bool:
        """Leave the open child windows out of screenshots (they stay on screen) while a
        capture is being taken. Returns True if any is open."""
        children = self._children() if exclude else self._excluded
        self._excluded = children if exclude else []
        for w in children:
            try:
                winapi.exclude_from_capture(int(w.winId()), exclude)
            except RuntimeError:  # closed in the meantime
                pass
        return bool(children)

    def _child_handles(self) -> list[int]:
        out = []
        for w in self._children():
            try:
                out.append(int(w.winId()))
            except RuntimeError:  # closed in the meantime
                pass
        return out

    def _focus_moved(self) -> None:
        """A child window lost focus. If focus went outside them (the text window, another
        app), they all go behind it; between them (History -> Settings) nothing changes."""
        children = self._child_handles()
        foreground = winapi.foreground()
        if not children or foreground in children:
            return
        self._send_behind(children, foreground)

    def _send_behind(self, children: list[int], foreground: int = 0) -> None:
        """No longer always on top: behind the text window and every always-on-top window,
        and behind `foreground` when that is a normal app window."""
        below = foreground if foreground and not winapi.is_topmost(foreground) else 0
        for hwnd in reversed(children):
            winapi.set_topmost(hwnd, False)
            if below:
                winapi.place_below(hwnd, below)

    def _text_window_in_front(self) -> None:
        """On-capture option "in front": the open windows go behind the new text window."""
        self._settle_until = time.monotonic() + 0.8  # see _ChildrenOnTop (overlay closing)
        self._send_behind(self._child_handles())
        winapi.set_topmost(int(self.window.winId()))

    def _children_in_front(self) -> None:
        """On-capture option "behind": the open windows stay in front of the text window."""
        self._settle_until = time.monotonic() + 0.8
        for hwnd in self._child_handles():
            winapi.set_topmost(hwnd)

    def _children(self) -> list[QWidget]:
        """Visible windows that belong to the text window: History, Settings, About, and
        the dialogs and message boxes opened from them or from the text window."""
        known = [self._settings_window, self._history_window, getattr(self, "_about", None)]
        out = [w for w in known if w is not None and w.isVisible()]
        if self._window is not None:
            for w in QApplication.topLevelWidgets():
                if w.isVisible() and w not in out and _descends_from(w, self._window):
                    out.append(w)
        return out

    def _close_children(self) -> bool:
        """A new capture closes every child window. Returns True if any was open."""
        children = self._children()
        # innermost first, so modal dialogs and message boxes end before their parents
        children.sort(key=lambda w: -_depth(w))
        for w in children:
            w.setProperty("dismissed", True)  # e.g. the consent question stays unanswered
            if w is self._settings_window and self._settings_window.components.busy:
                w.hide()  # a component is installing: keep it running; Settings reopens it
            elif isinstance(w, QDialog):
                w.reject()
            else:
                w.close()
        return bool(children)

    def _grab_and_select(self) -> None:
        if self._overlay is not None:
            return
        try:
            shot = grab_desktop()  # main window is excluded from captures
        except Exception:  # noqa: BLE001
            log.exception("screenshot failed")
            self.tray.showMessage("Jisho Lens", "Screenshot failed.", app_icon(), 3000)
            return
        finally:
            self._exclude_children(False)
        self._overlay = CaptureOverlay(shot, lambda rect: self._on_selected(shot, rect))
        self._overlay.show()

    def _on_selected(self, shot, rect: Rect | None) -> None:
        self._overlay = None
        if rect is None:
            return
        delay = self.settings.capture.delay_seconds
        self.window.present()
        if self.settings.window.on_capture == "above":
            self._text_window_in_front()
        elif self.settings.window.on_capture == "behind":
            self._children_in_front()
        if delay > 0:
            self.window.show_busy(f"Waiting {delay:g} s… (Esc cancels)")
            if self.settings.window.on_capture != "close":
                self._exclude_children(True)  # open windows may cover the area meanwhile
            self._delay_timer = QTimer(singleShot=True)
            self._delay_timer.timeout.connect(lambda: self._delayed_grab(rect))
            self._delay_timer.start(int(delay * 1000))
            self._arm_cancel(True)
        else:
            self._read(shot.crop(rect))

    # ---------- Esc cancels a capture ----------
    def _arm_cancel(self, on: bool) -> None:
        """While a capture waits or is being read, Esc cancels it. Esc is a global hotkey
        only for those seconds (the game keeps the focus), then it's released again."""
        if on:
            ok, message = self.hotkeys.register_key(ESC, "cancel")
            if not ok:
                log.info("Esc to cancel unavailable: %s", message)
        else:
            self.hotkeys.unregister("cancel")

    def cancel_capture(self) -> None:
        """Esc while waiting or reading: drop the capture; the previous text stays."""
        busy = self._pending_job is not None or self._delay_timer is not None
        self._arm_cancel(False)
        if not busy:
            return
        if self._delay_timer is not None:
            self._delay_timer.stop()
            self._delay_timer = None
            self._exclude_children(False)
        self._pending_job = None  # its result is ignored when it arrives
        self.tray.setIcon(app_icon())
        self.window.end_busy("Capture cancelled")
        log.info("capture cancelled")

    def _on_hotkey(self, name: str) -> None:
        if name == "show":
            self._on_tray_activated(QSystemTrayIcon.ActivationReason.Trigger)  # show / hide
        elif name == "cancel":
            self.cancel_capture()

    def _delayed_grab(self, rect: Rect) -> None:
        self._delay_timer = None
        try:
            image = grab_rect(rect)
        finally:
            self._exclude_children(False)
        self._read(image)

    def _read(self, image: Image.Image, engine: str | None = None,
              preset: str | None = None, retry: bool = False) -> None:
        self._last_image = image
        self._retrying = retry
        engine = engine or self.settings.ocr.engine
        preset = preset or self.settings.ocr.preset
        self.window.set_engine_preset(engine, preset)
        self.window.show_busy(f"Reading… ({engine}) · Esc cancels")
        self.window.set_corrections(0)
        self._applied = []
        self.tray.setIcon(app_icon(busy=True))
        self._arm_cancel(True)
        self._pending_job = self.ocr.submit(
            image, engine, preset,
            remove_key_icons=self.settings.capture.remove_key_icons,
            detect_speaker=self.settings.capture.detect_speaker,
            splitting=self.settings.analysis.word_splitting,
            dictionary=self.settings.analysis.dictionary_active,
        )

    def _retry(self, engine: str, preset: str) -> None:
        if self._last_image is None:
            self.start_capture()
            return
        self._read(self._last_image, engine, preset, retry=True)

    def _on_ocr_finished(self, outcome: OcrOutcome) -> None:
        if outcome.job.job_id != self._pending_job:
            return  # an older or cancelled job finished
        self._pending_job = None
        self._arm_cancel(False)
        self.tray.setIcon(app_icon())
        status =f"{outcome.job.engine} · {outcome.job.preset} · {outcome.seconds:.1f} s"
        lines, analysis = outcome.cleaned.lines, outcome.analysis
        self._ocr_lines, self._applied = list(lines), []
        if self.settings.data.collecting:
            try:
                result = self.corrections.apply(lines)
            except Exception:  # noqa: BLE001
                log.exception("applying corrections failed")
                result = None
            if result and result.used:
                self._applied = result.used
                lines = result.lines
                a = self.settings.analysis
                analysis = analyze_text(lines, a.word_splitting, a.dictionary_active)
                n = len(result.used)
                status += f" · Applied {n} of your earlier correction{'s' if n > 1 else ''}"
        self._show_analysis(lines, analysis, outcome.cleaned.speaker, status)
        self.window.set_corrections(len(self._applied))
        self._record(outcome, lines)

    # ---------- history and OCR data ----------
    def _record(self, outcome: OcrOutcome, lines: list[str]) -> None:
        """Save the capture to History and, if the user agreed, keep it as an OCR sample."""
        data = self.settings.data
        if data.collect == "ask":
            from jisho_lens.ui.consent import ask_consent

            answer = ask_consent(self._window)
            if answer is not None:  # None: closed by a new capture, ask again next time
                data.collect = "yes" if answer else "no"
                self.settings.save()
            log.info("OCR data collection: %s", data.collect)
        job, raw = outcome.job, outcome.raw.text  # raw OCR (with speaker line) for OCR data
        speaker = outcome.cleaned.speaker
        shown = "\n".join(lines)  # History keeps the text as shown
        self._sample_id = None
        png = png_bytes(job.image)
        same_file = None  # the sample's PNG when it is exactly this image (shared with History)
        if data.collecting:
            try:
                self._sample_id = self.ocr_data.add_capture(
                    job.image, raw, engine=job.engine, preset=job.preset,
                    seconds=round(outcome.seconds, 3), speaker=speaker, game=data.game,
                    screen=_screen_info(), png=png)
                if self._sample_id == sample_id(png):
                    same_file = self.ocr_data.png_path(self._sample_id)
            except Exception:  # noqa: BLE001
                log.exception("keeping the OCR sample failed")
        if self.settings.history.enabled:
            try:
                if self._retrying and self._capture_id is not None:
                    self.history.update_ocr(self._capture_id, shown, speaker, job.engine,
                                            job.preset, outcome.seconds, self._sample_id)
                else:
                    self._capture_id = self.history.add(
                        job.image, shown, speaker=speaker, engine=job.engine, preset=job.preset,
                        seconds=outcome.seconds, sample_id=self._sample_id, png=png,
                        same_file=same_file)
                    self.history.enforce_retention(self.settings.history.keep_last)
            except Exception:  # noqa: BLE001
                log.exception("saving to History failed")
        if data.collecting:
            try:
                keep = self.history.favorite_sample_ids() | {self._sample_id or ""}
                trimmed = self.ocr_data.enforce_limit(data.max_mb * 1024 * 1024, keep)
                if trimmed:
                    log.info("OCR data over %d MB: removed %d oldest unchecked samples",
                             data.max_mb, trimmed)
            except Exception:  # noqa: BLE001
                log.exception("trimming OCR data failed")
        if self._history_window is not None:
            self._history_window.refresh()
        self._update_confirm()
        self._update_favorite()

    def _update_favorite(self) -> None:
        c = self.history.get(self._capture_id) if self._capture_id is not None else None
        self.window.set_favorite(c is not None, bool(c and c.favorite))

    def _on_favorite(self, favorite: bool) -> None:
        if self._capture_id is None:
            return
        self.history.set_favorite(self._capture_id, favorite)
        self.window.status_label.setText(
            "Added to favorites ★" if favorite else "Removed from favorites")
        if self._history_window is not None:
            self._history_window.refresh()

    def _update_confirm(self) -> None:
        sample = self.ocr_data.get(self._sample_id) if self._sample_id else None
        self.window.set_collecting(sample is not None,
                                   confirmed=bool(sample and sample.checked))

    def _on_confirm(self) -> None:
        if self._sample_id:
            self.ocr_data.set_truth(self._sample_id, self.window.text(), "confirmed")
            if self._applied:  # kept the OCR text after Undo: those corrections were wrong
                self.corrections.forget(self._applied, self.window._lines)
                self._applied = []
            self.window.status_label.setText("Saved as correct ✓")
            self._update_confirm()

    def open_history(self) -> None:
        from jisho_lens.ui.history_window import HistoryWindow

        if self._history_window is None:
            self._history_window = HistoryWindow(self.history, self.ocr_data, self.settings,
                                                 self.corrections)
            self._history_window.changed.connect(self._on_history_changed)
            self._history_window.setWindowIcon(app_icon())
            self._history_window.open_requested.connect(self.open_capture)
            self._own(self._history_window)
        self._history_window.refresh()
        self._history_window.show()
        self._history_window.raise_()
        self._history_window.activateWindow()

    def _on_history_changed(self) -> None:
        """Captures or collected data were deleted in the History window."""
        if self._capture_id is not None and self.history.get(self._capture_id) is None:
            self._capture_id = None
        if self._sample_id and self.ocr_data.get(self._sample_id) is None:
            self._sample_id = None
        if self._window is not None:
            self._update_confirm()
            self._update_favorite()

    def open_capture(self, capture_id: int) -> None:
        capture = self.history.get(capture_id)
        if capture is None:
            return
        self._capture_id, self._sample_id = capture.id, capture.sample_id
        self._ocr_lines, self._applied = None, []
        self.window.set_corrections(0)
        if self._sample_id and self.ocr_data.get(self._sample_id) is None:
            self._sample_id = None  # collected data was deleted
        try:
            self._last_image = capture.image()
        except OSError:
            self._last_image = None
        a = self.settings.analysis
        analysis = analyze_text(capture.lines, a.word_splitting, a.dictionary_active)
        when = time.strftime("%Y-%m-%d %H:%M", time.localtime(capture.created_at))
        self.window.present()
        self._show_analysis(capture.lines, analysis, capture.speaker, f"History · {when}")
        self._update_confirm()
        self._update_favorite()

    def _show_analysis(self, lines, analysis, speaker, status) -> None:
        if analysis.warning:
            status = f"{status} · {analysis.warning}"
        self.window.show_text(lines, analysis.tokens, speaker, status, analysis.dictionary)

    def _on_text_edited(self, lines: list[str]) -> None:
        before = list(self.window._lines)  # the text as shown before this edit
        a = self.settings.analysis
        analysis = analyze_text(lines, a.word_splitting, a.dictionary_active)
        self._show_analysis(lines, analysis, self.window._speaker, "Edited")
        self.window.set_corrections(0)
        text = "\n".join(lines)
        if self._capture_id is not None:
            self.history.set_edited(self._capture_id, text)
        if self._sample_id:
            self.ocr_data.set_truth(self._sample_id, text, "edited")
            status = "Edited · correction saved"
            if self.settings.data.collecting:
                try:
                    learned = self.corrections.learn(before, lines, self._applied)
                except Exception:  # noqa: BLE001
                    log.exception("learning corrections failed")
                    learned = 0
                if learned:
                    status += " · will be fixed in later captures"
            self._applied = []
            self.window.status_label.setText(status)
        self._update_confirm()

    def _tidy_ocr_data(self) -> None:
        """Once: merge duplicate samples kept before duplicates were detected, and share
        identical images between History and OCR data."""
        marker = self.ocr_data.folder / "tidy-1.done"
        if marker.exists() or not self.ocr_data.samples_dir.exists():
            return
        try:
            from jisho_lens.core.storage import share_identical_images

            mapping = self.ocr_data.remove_duplicates(self.history.favorite_sample_ids())
            self.history.remap_samples(mapping)
            shared = share_identical_images(self.history, self.ocr_data)
            log.info("OCR data tidy: merged %d duplicate samples, shared %d images",
                     len(mapping), shared)
            marker.write_text("ok", encoding="utf-8")
        except Exception:  # noqa: BLE001
            log.exception("tidying OCR data failed")

    def _learn_from_samples(self) -> None:
        """Learn from corrections saved before this feature existed (runs once)."""
        try:
            n = self.corrections.learn_from_samples(self.ocr_data.all())
            log.info("learned %d corrections from saved samples", n)
        except Exception:  # noqa: BLE001
            log.exception("learning from saved samples failed")

    def _undo_corrections(self) -> None:
        """Show the text as OCR read it, without the corrections applied to it."""
        if self._ocr_lines is None:
            return
        a = self.settings.analysis
        analysis = analyze_text(self._ocr_lines, a.word_splitting, a.dictionary_active)
        self._show_analysis(self._ocr_lines, analysis, self.window._speaker,
                            "As OCR read it · Edit to fix, or ✓ if it's right")
        self.window.set_corrections(0)

    def _check_word_splitting(self) -> bool:
        """Fall back to plain text when the selected UniDic isn't installed. True if changed."""
        a = self.settings.analysis
        mode = a.word_splitting
        ok = mode == "none" or (mode in SPLITTING_MODES and components.is_installed(
            {"lite": "unidic-lite", "full": "unidic-full"}.get(mode, "")))
        if not ok:
            a.word_splitting = "none"
            self.settings.save()
        return not ok

    def _on_components_changed(self, changed: list) -> None:
        log.info("components changed: %s; installed now: %s", changed, components.installed())
        if self._check_word_splitting():
            self.tray.showMessage("Jisho Lens", "Word splitting is off: its UniDic was removed.",
                                  app_icon(), 5000)
        self._preload()

    def _preload(self) -> None:
        a = self.settings.analysis
        self.ocr.preload(self.settings.ocr.engine, a.word_splitting, a.dictionary_active)

    def _on_display_changed(self, furigana: bool, romaji: bool) -> None:
        self.settings.window.show_furigana = furigana
        self.settings.window.show_romaji = romaji
        self.settings.save()

    def _on_ocr_failed(self, job_id: int, message: str) -> None:
        if job_id != self._pending_job:
            return
        self._pending_job = None
        self._arm_cancel(False)
        self.tray.setIcon(app_icon())
        self.window.show_message(f"OCR failed: {message}", error=True)

    def _on_engine_failed(self, name: str, message: str) -> None:
        what = {"splitting": "Word splitting", "jmdict": "Dictionary (meanings)"}.get(
            name, f"OCR engine {name}")
        self.tray.showMessage("Jisho Lens", f"{what} unavailable: {message}", app_icon(), 8000)

    # ---------- settings ----------
    def open_settings(self) -> None:
        if self._settings_window is not None:
            self._settings_window.show()  # may have been hidden by a capture
            self._settings_window.raise_()
            self._settings_window.activateWindow()
            return
        self._settings_window = SettingsWindow(self.settings, self.hotkey_ok, self.corrections,
                                              self.ocr_data, self.history)
        self._settings_window.setWindowIcon(app_icon())
        self._settings_window.applied.connect(self._apply_settings)
        self._settings_window.components_changed.connect(self._on_components_changed)
        self._settings_window.data_changed.connect(self._on_history_changed)
        self._settings_window.finished.connect(self._settings_closed)
        self._own(self._settings_window)
        self._settings_window.show()

    def _settings_closed(self, _result: int) -> None:
        if self._settings_window is not None:
            self._settings_window.deleteLater()  # owned by the text window: free it
        self._settings_window = None

    def _apply_settings(self, new: Settings) -> None:
        old = self.settings
        new.window.geometry = old.window.geometry
        new.window.show_furigana = old.window.show_furigana
        new.window.show_romaji = old.window.show_romaji
        self.settings = new
        if new.capture.hotkey != old.capture.hotkey or not self.hotkey_ok:
            self.hotkey_ok, message = self.hotkeys.register(new.capture.hotkey)
            if not self.hotkey_ok:
                self.tray.showMessage("Jisho Lens", f"Hotkey not set: {message}", app_icon(),
                                      6000)
                new.capture.hotkey = self.hotkeys.current or old.capture.hotkey
        if new.capture.show_hotkey != old.capture.show_hotkey or not self.show_hotkey_ok:
            self.show_hotkey_ok, message = self.hotkeys.register(new.capture.show_hotkey, "show")
            if not self.show_hotkey_ok:
                self.tray.showMessage("Jisho Lens", f"Show-window hotkey not set: {message}",
                                      app_icon(), 6000)
                new.capture.show_hotkey = self.hotkeys.current_for("show") or ""
        if (new.ocr.engine != old.ocr.engine
                or new.analysis.word_splitting != old.analysis.word_splitting
                or new.analysis.dictionary_active != old.analysis.dictionary_active):
            self._preload()
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
        self.history.close()
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
