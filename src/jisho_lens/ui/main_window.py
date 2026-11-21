"""Always-on-top window showing the captured Japanese text (SPEC §3.1 Main window).

Phase 2: words are clickable (popup with reading, romaji, word type, dictionary form),
furigana sits over kanji, and a romaji line can be shown under each line.
"""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QGuiApplication
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from jisho_lens.core.analysis import Token
from jisho_lens.core.ocr import ENGINE_NAMES
from jisho_lens.core.ocr.preprocess import PRESETS
from jisho_lens.ui.render import page_for_message, page_for_tokens
from jisho_lens.ui.winapi import exclude_from_capture


class MainWindow(QWidget):
    recapture_requested = Signal()
    retry_requested = Signal(str, str)  # engine, preset
    settings_requested = Signal()
    text_edited = Signal(list)  # new lines
    geometry_changed = Signal(list)
    display_changed = Signal(bool, bool)  # furigana, romaji

    def __init__(self, font_size: int = 22, furigana: bool = True, romaji: bool = False) -> None:
        super().__init__(
            None,
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,  # no taskbar button
        )
        self.setWindowTitle("Jisho Lens")
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setMinimumSize(380, 170)
        self._font_size = font_size
        self._tokens: list[list[Token]] = []
        self._lines: list[str] = []
        self._speaker: str | None = None
        self._message: tuple[str, bool] | None = None

        self.speaker_label = QLabel()
        self.speaker_label.setStyleSheet("color: #a9cfff; font-weight: bold; font-size: 15px;")
        self.furigana_btn = QPushButton("Furigana")
        self.romaji_btn = QPushButton("Romaji")
        for b, on in ((self.furigana_btn, furigana), (self.romaji_btn, romaji)):
            b.setCheckable(True)
            b.setChecked(on)
            b.toggled.connect(self._display_toggled)
        self.status_label = QLabel()
        self.status_label.setStyleSheet("color: #8a8f99; font-size: 12px;")
        top = QHBoxLayout()
        top.addWidget(self.speaker_label)
        top.addStretch(1)
        top.addWidget(self.status_label)
        top.addWidget(self.furigana_btn)
        top.addWidget(self.romaji_btn)

        self.view = QWebEngineView()
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet(
            f"background:#1d1f24; color:#f1f1f1; font-size:{font_size}px;"
            "font-family:'Yu Gothic UI','Meiryo'; border:1px solid #3d7dd8;"
        )
        self.stack = QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.editor)

        self.recapture_btn = QPushButton("Re-capture")
        self.edit_btn = QPushButton("Edit")
        self.copy_btn = QPushButton("Copy")
        self.engine_box = QComboBox()
        self.engine_box.addItems(ENGINE_NAMES)
        self.preset_box = QComboBox()
        self.preset_box.addItems(PRESETS)
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setToolTip("Read the same capture again with this engine and preset")
        self.settings_btn = QPushButton("Settings")
        bottom = QHBoxLayout()
        for w in (self.recapture_btn, self.edit_btn, self.copy_btn):
            bottom.addWidget(w)
        bottom.addStretch(1)
        for w in (self.engine_box, self.preset_box, self.retry_btn, self.settings_btn):
            bottom.addWidget(w)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self.stack, 1)
        layout.addLayout(bottom)
        self.setStyleSheet(
            "QWidget { background: #25272d; color: #e6e6e6; }"
            "QPushButton, QComboBox { padding: 3px 8px; }"
            "QPushButton:checked { background: #3d5a8a; }"
        )

        self.recapture_btn.clicked.connect(self.recapture_requested)
        self.edit_btn.clicked.connect(self._toggle_edit)
        self.copy_btn.clicked.connect(self._copy)
        self.retry_btn.clicked.connect(
            lambda: self.retry_requested.emit(self.engine_box.currentText(),
                                              self.preset_box.currentText())
        )
        self.settings_btn.clicked.connect(self.settings_requested)

        self._geometry_timer = QTimer(self, singleShot=True, interval=500)
        self._geometry_timer.timeout.connect(self._emit_geometry)
        self._excluded = False
        self.show_message("Press the capture hotkey and select Japanese text.")

    # ---------- content ----------
    def set_engine_preset(self, engine: str, preset: str) -> None:
        self.engine_box.setCurrentText(engine)
        self.preset_box.setCurrentText(preset)

    def set_font_size(self, size: int) -> None:
        self._font_size = size
        self._render()

    def show_busy(self, message: str = "Reading…") -> None:
        self.status_label.setText(message)
        self._set_buttons_enabled(False)

    def show_message(self, message: str, error: bool = False) -> None:
        self._tokens, self._lines, self._speaker = [], [], None
        self._message = (message, error)
        self.speaker_label.setText("")
        self._render()
        self._set_buttons_enabled(True)

    def show_text(self, lines: list[str], tokens: list[list[Token]], speaker: str | None,
                  status: str | None = None) -> None:
        self._lines, self._tokens, self._speaker = list(lines), tokens, speaker
        self._message = None
        self.speaker_label.setText(speaker or "")
        if status is not None:
            self.status_label.setText(status)
        self._leave_edit_mode(save=False)
        self._render()
        self._set_buttons_enabled(True)

    def text(self) -> str:
        return "\n".join(self._lines)

    def _render(self) -> None:
        if self._message is not None:
            message, error = self._message
            html = page_for_message(message, self._font_size, error=error)
        elif not self._lines:
            html = page_for_message("No Japanese text found. Try Retry with another engine or "
                                    "preset, or Edit.", self._font_size)
        else:
            html = page_for_tokens(self._tokens, self._font_size,
                                   self.furigana_btn.isChecked(), self.romaji_btn.isChecked())
        self.view.setHtml(html)

    def _display_toggled(self) -> None:
        furi, rom = self.furigana_btn.isChecked(), self.romaji_btn.isChecked()
        # update in place (keeps an open popup); no full re-render needed
        self.view.page().runJavaScript(
            f"setOpt('furi', {str(furi).lower()}); setOpt('romaji', {str(rom).lower()});")
        self.display_changed.emit(furi, rom)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for w in (self.recapture_btn, self.edit_btn, self.copy_btn, self.retry_btn):
            w.setEnabled(enabled)

    # ---------- edit / copy ----------
    def _toggle_edit(self) -> None:
        if self.stack.currentWidget() is self.editor:
            self._leave_edit_mode(save=True)
        else:
            self.editor.setPlainText(self.text())
            self.stack.setCurrentWidget(self.editor)
            self.edit_btn.setText("Done")
            self.activateWindow()
            self.editor.setFocus()

    def _leave_edit_mode(self, save: bool) -> None:
        if self.stack.currentWidget() is not self.editor:
            return
        self.stack.setCurrentWidget(self.view)
        self.edit_btn.setText("Edit")
        if save:
            new_lines = [ln.strip() for ln in self.editor.toPlainText().splitlines()
                         if ln.strip()]
            if new_lines != self._lines:
                self.text_edited.emit(new_lines)  # the app re-analyzes and calls show_text

    def _copy(self) -> None:
        QGuiApplication.clipboard().setText(self.text())
        self.status_label.setText("Copied")

    # ---------- window behaviour ----------
    def present(self) -> None:
        """Show without taking focus from the game."""
        if not self.isVisible():
            self.show()
        self.raise_()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._excluded:
            self._excluded = exclude_from_capture(int(self.winId()))

    def restore_geometry(self, geometry: list[int]) -> None:
        if len(geometry) == 4:
            rect = QRect(*geometry)
            if any(s.availableGeometry().intersects(rect) for s in QGuiApplication.screens()):
                self.setGeometry(rect)
                return
        screen = QGuiApplication.primaryScreen().availableGeometry()
        self.resize(680, 260)
        self.move(screen.right() - 700, screen.bottom() - 300)

    def moveEvent(self, event) -> None:  # noqa: N802
        super().moveEvent(event)
        self._geometry_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._geometry_timer.start()

    def _emit_geometry(self) -> None:
        g = self.geometry()
        self.geometry_changed.emit([g.x(), g.y(), g.width(), g.height()])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # Closing only hides; the app keeps running in the tray.
        event.ignore()
        self.hide()
