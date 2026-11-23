"""Always-on-top window showing the captured Japanese text (SPEC §3.1 Main window).

Phase 2: words are clickable (popup with reading, romaji, word type, dictionary form),
furigana sits over kanji, and a romaji line can be shown under each line.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QFont,
    QFontMetrics,
    QGuiApplication,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QBoxLayout,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLayout,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWidgetItem,
)

from jisho_lens.core.analysis import Token
from jisho_lens.core.ocr import ENGINE_NAMES
from jisho_lens.core.ocr.preprocess import PRESETS
from jisho_lens.dictionary.enrich import PageDictionary
from jisho_lens.ui.render import page_for_message, page_for_plain, page_for_tokens
from jisho_lens.ui.winapi import exclude_from_capture

# Button colors by what the button does (tinted fill + colored border and text, readable on
# the dark window). Checked toggles (Furigana, Romaji, ★ Favorite, Edit while editing) fill.
BUTTON_COLORS = {
    "capture": "#4a8fe7",  # Re-capture, Retry: read the text again
    "edit": "#e0a030",  # Edit / Save Edit
    "copy": "#3fb6a8",
    "confirm": "#5cbf6a",  # ✓ Correct
    "favorite": "#e8c547",
    "history": "#a27be0",
    "undo": "#e07b4a",  # Undo applied corrections
    "display": "#6fb3e0",  # Furigana, Romaji
    "settings": "#8a8f99",
    "cancel": "#c96b6b",  # Cancel while editing
}


def _rgba(color: str, alpha: float) -> str:
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return f"rgba({r}, {g}, {b}, {alpha})"


ENGINE_HELP = {
    "windows": "Windows OCR: built in, very fast, least accurate",
    "rapid-v6": "RapidOCR v6: most accurate on game text (default)",
    "rapid-v5-server": "RapidOCR v5 server: large model, very slow, sometimes reads ゛ better",
    "rapid-v4-japan": "RapidOCR v4 Japanese: fast, less accurate",
}
PRESET_HELP = {
    "none": "As captured (usually best)",
    "upscale": "Enlarged: helps very small text",
    "contrast": "Stronger contrast: helps faint text",
    "white-text": "For white text on a busy background",
    "auto": "Picks a filter from the image",
}

_BUTTON_PADDING = 10  # px left and right, as in button_style()


def _fit_bold(button: QPushButton, texts) -> None:
    """Minimum width that fits each of `texts` in bold (the "on" look), so the text isn't
    cut off when the button fills; the button doesn't change size between states."""
    font = QFont(button.font())
    font.setBold(True)
    metrics = QFontMetrics(font)
    widest = max(metrics.horizontalAdvance(t) for t in texts)
    button.setMinimumWidth(widest + 2 * _BUTTON_PADDING + 2 + 6)  # + border, breathing room


def button_style() -> str:
    css = []
    for role, c in BUTTON_COLORS.items():
        sel = f'QPushButton[role="{role}"]'
        css.append(
            f"{sel} {{ background: {_rgba(c, 0.16)}; border: 1px solid {_rgba(c, 0.75)};"
            f" color: {c}; border-radius: 4px; padding: 3px 10px; }}"
            f"{sel}:hover {{ background: {_rgba(c, 0.30)}; border-color: {c}; }}"
            f"{sel}:pressed {{ background: {_rgba(c, 0.45)}; }}"
            f"{sel}:checked, {sel}[active=\"true\"] {{ background: {_rgba(c, 0.85)};"
            f" border-color: {c}; color: #15171b; font-weight: bold; }}"
            f"{sel}:disabled {{ background: transparent; border-color: #3a3d44;"
            f" color: #5d616b; }}")
    return "".join(css)


def _divider() -> QFrame:
    """A thin vertical line between groups of controls."""
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFixedWidth(9)
    line.setStyleSheet("QFrame { color: #4a4e57; background: transparent; margin: 4px 4px; }"
                       "QFrame[frameShape='5'] { border: none; border-left: 1px solid "
                       "#4a4e57; }")
    return line


class GroupFlow(QLayout):
    """Groups of controls in a row that wrap to more rows when the window is too narrow.
    A group never splits, and its divider shows only between groups on the same row."""

    SPACING = 6

    def __init__(self, groups: list[tuple], align_right: bool = False) -> None:
        super().__init__()
        self.setContentsMargins(0, 0, 0, 0)
        self._align_right = align_right
        self.changed = None  # called when a group's size changes (a button shown/hidden)
        self._items = []  # (divider item or None, group item)
        for i, group in enumerate(groups):
            box = QWidget()
            row = QHBoxLayout(box)
            row.setContentsMargins(0, 0, 0, 0)
            row.setSpacing(self.SPACING)
            for w in group:
                if w == "gap":
                    row.addSpacing(self.SPACING)
                else:
                    row.addWidget(w)
            divider = None
            if i:
                self.addChildWidget(line := _divider())
                divider = QWidgetItem(line)
            self.addChildWidget(box)
            self._items.append((divider, QWidgetItem(box)))

    # ---- QLayout
    def addItem(self, item) -> None:  # noqa: N802
        raise NotImplementedError("GroupFlow takes its groups in the constructor")

    def count(self) -> int:
        return sum(1 + (d is not None) for d, _g in self._items)

    def itemAt(self, index: int):  # noqa: N802
        flat = [x for d, g in self._items for x in (d, g) if x is not None]
        return flat[index] if 0 <= index < len(flat) else None

    def takeAt(self, index: int):  # noqa: N802
        return None

    def expandingDirections(self):  # noqa: N802
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        return self._place(QRect(0, 0, width, 0), apply=False)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self.one_row_width(), self._place(QRect(0, 0, 10**6, 0), apply=False))

    def minimumSize(self) -> QSize:  # noqa: N802
        widest = max((g.sizeHint().width() for _d, g in self._shown()), default=0)
        return QSize(widest, self._place(QRect(0, 0, widest, 0), apply=False))

    def invalidate(self) -> None:
        super().invalidate()
        if getattr(self, "changed", None) is not None:
            self.changed()

    def setGeometry(self, rect: QRect) -> None:  # noqa: N802
        super().setGeometry(rect)
        self._place(rect, apply=True)

    # ---- placing
    def _shown(self):
        return [(d, g) for d, g in self._items if not g.widget().isHidden()]

    def one_row_width(self) -> int:
        """The width everything needs on one row."""
        shown = self._shown()
        width = sum(g.sizeHint().width() for _d, g in shown)
        for i, (d, _g) in enumerate(shown):
            if i and d is not None:
                width += d.sizeHint().width() + 2 * self.SPACING
            elif i:
                width += self.SPACING
        return width

    def _place(self, rect: QRect, apply: bool) -> int:
        """Lay the groups out in `rect` (or only measure); returns the height used."""
        rows, row, used = [], [], 0
        for d, g in self._shown():
            w = g.sizeHint().width()
            lead = (d.sizeHint().width() + 2 * self.SPACING) if d is not None else self.SPACING
            if row and used + lead + w > rect.width():
                rows.append(row)
                row, used = [], 0
            row.append((d, g, lead if row else 0, w))
            used += (lead if len(row) > 1 else 0) + w
        if row:
            rows.append(row)
        y = rect.y()
        hidden = {id(d) for d, _g in self._items if d is not None}
        for n, row in enumerate(rows):
            height = max(g.sizeHint().height() for _d, g, _l, _w in row)
            width = sum(lead + w for _d, _g, lead, w in row)
            x = rect.x() + (rect.width() - width if self._align_right else 0)
            for d, g, lead, w in row:
                if lead and d is not None:
                    dw = d.sizeHint().width()
                    if apply:
                        d.setGeometry(QRect(x + self.SPACING, y, dw, height))
                    hidden.discard(id(d))
                if apply:
                    g.setGeometry(QRect(QPoint(x + lead, y), QSize(w, height)))
                x += lead + w
            y += height + (self.SPACING if n < len(rows) - 1 else 0)
        if apply:  # dividers at the start of a row (or of hidden groups) aren't drawn
            for d, _g in self._items:
                if d is not None and id(d) in hidden:
                    d.setGeometry(QRect())
        return y - rect.y()


class ElideLabel(QLabel):
    """A one-line label that shortens its text with … when the window is narrow (the full
    text is in the hover text)."""

    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = text
        self.setMinimumWidth(40)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._elide()

    def set_full_text(self, text: str) -> None:
        self._full = text
        self._elide()

    def full_text(self) -> str:
        return self._full

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        self.setText(self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight,
                                                   max(0, self.width())))


class MainWindow(QWidget):
    recapture_requested = Signal()
    retry_requested = Signal(str, str)  # engine, preset
    settings_requested = Signal()
    confirm_requested = Signal()  # ✓ Correct: OCR read this capture right
    history_requested = Signal()
    favorite_toggled = Signal(bool)  # star the whole phrase (History capture)
    undo_corrections_requested = Signal()  # show what OCR read before my corrections
    redo_corrections_requested = Signal()  # show the fix again
    text_edited = Signal(list, object)  # new lines, speaker's name (None = no speaker)
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
        self._dictionary: PageDictionary | None = None

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
        # what your OCR data is made of, always shown ("RavenOCR v2 + own data")
        self.data_label = ElideLabel()
        self.data_label.setStyleSheet("color: #7f9cc4; font-size: 12px;")
        top = QHBoxLayout()
        top.addWidget(self.speaker_label)
        top.addSpacing(8)
        top.addWidget(self.data_label, 1)
        top.addWidget(self.status_label)
        self.undo_btn = QPushButton("Undo Fix")
        self.undo_btn.setToolTip("Show the text as OCR read it, without your earlier fixes "
                                 "(nothing is saved; Redo Fix brings them back)")
        self.undo_btn.setVisible(False)
        self.undo_btn.clicked.connect(self.undo_corrections_requested)
        top.addWidget(self.undo_btn)
        self.redo_btn = QPushButton("Redo Fix")
        self.redo_btn.setToolTip("Show your fix again")
        self.redo_btn.setVisible(False)
        self.redo_btn.clicked.connect(self.redo_corrections_requested)
        top.addWidget(self.redo_btn)
        top.addWidget(_divider())  # display options
        top.addWidget(self.furigana_btn)
        top.addWidget(self.romaji_btn)

        self.view = QWebEngineView()
        self.view.page().setBackgroundColor(Qt.GlobalColor.transparent)
        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet(
            f"background:#1d1f24; color:#f1f1f1; font-size:{font_size}px;"
            "font-family:'Yu Gothic UI','Meiryo'; border:1px solid #3d7dd8;"
        )
        # edit mode: the speaker's name above the text
        self.speaker_edit = QLineEdit()
        self.speaker_edit.setPlaceholderText("No speaker")
        self.speaker_edit.setStyleSheet("background:#1d1f24; color:#a9cfff; font-weight:bold;"
                                        "border:1px solid #3d7dd8; padding:2px 6px;")
        self.edit_page = QWidget()
        edit_layout = QVBoxLayout(self.edit_page)
        edit_layout.setContentsMargins(0, 0, 0, 0)
        speaker_row = QHBoxLayout()
        speaker_row.addWidget(QLabel("Speaker"))
        speaker_row.addWidget(self.speaker_edit, 1)
        edit_layout.addLayout(speaker_row)
        edit_layout.addWidget(self.editor, 1)
        self.stack = QStackedWidget()
        self.stack.addWidget(self.view)
        self.stack.addWidget(self.edit_page)

        self.recapture_btn = QPushButton("Re-capture")
        self.edit_btn = QPushButton("Edit")
        self.cancel_edit_btn = QPushButton("Cancel")  # shown while editing
        self.cancel_edit_btn.setToolTip("Stop editing without saving (Esc)")
        self.cancel_edit_btn.setVisible(False)
        self.cancel_edit_btn.clicked.connect(
            lambda _checked=False: self._leave_edit_mode(save=False))
        self.editor.installEventFilter(self)  # Esc in the editor = Cancel
        self.speaker_edit.installEventFilter(self)
        self.copy_btn = QPushButton("Copy")
        self.confirm_btn = QPushButton("✓ Correct")
        self.confirm_btn.setToolTip("OCR read this correctly: keep it as a checked sample "
                                    "(only when OCR data collection is on)")
        self.confirm_btn.setVisible(False)
        self.history_btn = QPushButton("History")
        self.favorite_btn = QPushButton("☆ Favorite")
        self.favorite_btn.setCheckable(True)
        self.favorite_btn.setToolTip("Keep this phrase in History. Favorites can't be deleted "
                                     "until you remove the star.")
        self.favorite_btn.setVisible(False)
        self.favorite_btn.clicked.connect(self._favorite_clicked)
        self.engine_box = QComboBox()
        self.engine_box.addItems(ENGINE_NAMES)
        self.engine_box.setToolTip("OCR engine: the program that reads the text in the image")
        for i, name in enumerate(ENGINE_NAMES):
            self.engine_box.setItemData(i, ENGINE_HELP.get(name, ""), Qt.ItemDataRole.ToolTipRole)
        self.preset_box = QComboBox()
        self.preset_box.addItems(PRESETS)
        self.preset_box.setToolTip("Image filter: how the captured image is prepared before "
                                   "the OCR engine reads it")
        for i, name in enumerate(PRESETS):
            self.preset_box.setItemData(i, PRESET_HELP.get(name, ""), Qt.ItemDataRole.ToolTipRole)
        engine_label = QLabel("OCR engine")
        engine_label.setBuddy(self.engine_box)
        preset_label = QLabel("Image filter")
        preset_label.setBuddy(self.preset_box)
        for label in (engine_label, preset_label):
            label.setStyleSheet("color: #8a8f99; font-size: 12px;")
        self.retry_btn = QPushButton("Retry")
        self.retry_btn.setToolTip("Read the same capture again with this OCR engine and "
                                  "image filter")
        self.settings_btn = QPushButton("Settings")
        # bottom bar: actions on the left, OCR controls on the right; on a narrow window the
        # OCR controls wrap to a second row (see _fit_bottom_bar)
        # groups: capture | the text | keeping it (OCR data, favorites, History); a group
        # that doesn't fit goes to the next row (no overlapping buttons on a narrow window)
        self.actions_bar = QWidget()
        self.actions_flow = GroupFlow([
            (self.recapture_btn,), (self.edit_btn, self.cancel_edit_btn, self.copy_btn),
            (self.confirm_btn, self.favorite_btn, self.history_btn)])
        self.actions_bar.setLayout(self.actions_flow)
        # groups: reading again (engine, image filter, Retry) | settings
        self.ocr_bar = QWidget()
        self.ocr_flow = GroupFlow([
            (engine_label, self.engine_box, "gap", preset_label, self.preset_box,
             self.retry_btn), (self.settings_btn,)], align_right=True)
        self.ocr_bar.setLayout(self.ocr_flow)
        self._fit_timer = QTimer(self)  # one row or two, again after buttons show/hide
        self._fit_timer.setSingleShot(True)
        self._fit_timer.setInterval(0)
        self._fit_timer.timeout.connect(self._fit_bottom_bar)
        self.actions_flow.changed = self.ocr_flow.changed = self._fit_timer.start
        self.bottom = QBoxLayout(QBoxLayout.Direction.LeftToRight)
        self.bottom.addWidget(self.actions_bar, 1)
        self.bottom.addWidget(self.ocr_bar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 8)
        layout.addLayout(top)
        layout.addWidget(self.stack, 1)
        layout.addLayout(self.bottom)
        roles = {
            "capture": (self.recapture_btn, self.retry_btn), "edit": (self.edit_btn,),
            "cancel": (self.cancel_edit_btn,),
            "copy": (self.copy_btn,), "confirm": (self.confirm_btn,),
            "favorite": (self.favorite_btn,), "history": (self.history_btn,),
            "undo": (self.undo_btn, self.redo_btn),
            "display": (self.furigana_btn, self.romaji_btn),
            "settings": (self.settings_btn,),
        }
        # every text a button can show (its width must fit the widest one, in bold)
        texts = {self.edit_btn: ("Edit", "Save Edit"),
                 self.favorite_btn: ("☆ Favorite", "★ Favorite"),
                 self.confirm_btn: ("✓ Correct", "✓ Saved", "Save Undo")}
        for role, buttons in roles.items():
            for b in buttons:
                b.setProperty("role", role)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                _fit_bold(b, texts.get(b, (b.text(),)))
        self.setStyleSheet(
            "QWidget { background: #25272d; color: #e6e6e6; }"
            "QPushButton, QComboBox { padding: 3px 8px; }"
            + button_style()
        )

        self.recapture_btn.clicked.connect(self.recapture_requested)
        self.edit_btn.clicked.connect(self._toggle_edit)
        self.copy_btn.clicked.connect(self._copy)
        self.confirm_btn.clicked.connect(self.confirm_requested)
        self.history_btn.clicked.connect(self.history_requested)
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

    def end_busy(self, message: str) -> None:
        """Busy state ended without new text (e.g. the capture was cancelled)."""
        self.status_label.setText(message)
        self._set_buttons_enabled(True)

    def show_message(self, message: str, error: bool = False) -> None:
        self._tokens, self._lines, self._speaker = [], [], None
        self._message = (message, error)
        self.speaker_label.setText("")
        self._render()
        self._set_buttons_enabled(True)

    def show_text(self, lines: list[str], tokens: list[list[Token]], speaker: str | None,
                  status: str | None = None, dictionary: PageDictionary | None = None) -> None:
        self._lines, self._tokens, self._speaker = list(lines), tokens, speaker
        self._dictionary = dictionary
        has_words = bool(tokens)
        for b in (self.furigana_btn, self.romaji_btn):
            b.setEnabled(has_words)
            b.setToolTip("" if has_words else "Word splitting is off (Settings)")
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
        elif not self._tokens:
            html = page_for_plain(self._lines, self._font_size)
        else:
            html = page_for_tokens(self._tokens, self._font_size,
                                   self.furigana_btn.isChecked(), self.romaji_btn.isChecked(),
                                   self._dictionary)
        self.view.setHtml(html)

    def _display_toggled(self) -> None:
        furi, rom = self.furigana_btn.isChecked(), self.romaji_btn.isChecked()
        # update in place (keeps an open popup); no full re-render needed
        self.view.page().runJavaScript(
            f"setOpt('furi', {str(furi).lower()}); setOpt('romaji', {str(rom).lower()});")
        self.display_changed.emit(furi, rom)

    def set_collecting(self, collecting: bool, confirmed: bool = False,
                       undone: bool = False) -> None:
        """The ✓ button, shown only while OCR data collection is on for the capture:
        "✓ Saved" (disabled) when the text and name shown are what's saved; "Save Undo"
        after Undo (the text as OCR read it isn't saved yet); otherwise "✓ Correct"."""
        self._undone = collecting and undone  # Save Edit then saves even without changes
        self.confirm_btn.setVisible(collecting)
        self.confirm_btn.setEnabled(collecting and not confirmed)
        if confirmed:
            text, tip = "✓ Saved", "The text and name shown are saved as the right answer"
        elif undone:
            text, tip = ("Save Undo", "Save the text and name as OCR read them as the right "
                         "answer (your earlier fix is replaced)")
        else:
            text, tip = ("✓ Correct", "OCR read this correctly: keep it as a checked sample "
                         "(only when OCR data collection is on)")
        self.confirm_btn.setText(text)
        self.confirm_btn.setToolTip(tip)

    def set_favorite(self, available: bool, favorite: bool = False) -> None:
        """Show the star while the text on screen is a History capture."""
        self.favorite_btn.setVisible(available)
        self.favorite_btn.setChecked(favorite)
        self.favorite_btn.setText("★ Favorite" if favorite else "☆ Favorite")

    def _favorite_clicked(self, checked: bool) -> None:
        self.favorite_btn.setText("★ Favorite" if checked else "☆ Favorite")
        self.favorite_toggled.emit(checked)

    def set_data_label(self, text: str, details: str = "") -> None:
        """The "OCR data: …" line (shown with or without text in the window)."""
        self.data_label.set_full_text(text)
        self.data_label.setToolTip(details)

    def set_corrections(self, count: int, redo: bool = False) -> None:
        """Undo Fix while the text has `count` > 0 of your earlier fixes; Redo Fix (instead)
        after Undo Fix, while the fix can be shown again."""
        self.undo_btn.setVisible(count > 0 and not redo)
        self.redo_btn.setVisible(redo)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        for w in (self.recapture_btn, self.edit_btn, self.copy_btn, self.retry_btn,
                  self.confirm_btn):
            w.setEnabled(enabled)

    # ---------- edit / copy ----------
    @staticmethod
    def _set_active(button: QPushButton, active: bool) -> None:
        """Filled look for a button that is "on" without being checkable (Edit → Save Edit)."""
        button.setProperty("active", "true" if active else "false")
        button.style().unpolish(button)
        button.style().polish(button)

    def eventFilter(self, obj, event) -> bool:  # noqa: N802
        if (obj in (self.editor, self.speaker_edit) and event.type() == QEvent.Type.KeyPress
                and event.key() == Qt.Key.Key_Escape):
            self._leave_edit_mode(save=False)
            return True
        return super().eventFilter(obj, event)

    def _toggle_edit(self) -> None:
        if self.stack.currentWidget() is self.edit_page:
            self._leave_edit_mode(save=True)
        else:
            self.editor.setPlainText(self.text())
            self.speaker_edit.setText(self._speaker or "")
            self.stack.setCurrentWidget(self.edit_page)
            self.edit_btn.setText("Save Edit")
            self.edit_btn.setToolTip("Save the edited text")
            self._set_active(self.edit_btn, True)
            self.cancel_edit_btn.setVisible(True)
            self.activateWindow()
            self.editor.setFocus()

    def _leave_edit_mode(self, save: bool) -> None:
        if self.stack.currentWidget() is not self.edit_page:
            return
        self.stack.setCurrentWidget(self.view)
        self.edit_btn.setText("Edit")
        self.edit_btn.setToolTip("")
        self._set_active(self.edit_btn, False)
        self.cancel_edit_btn.setVisible(False)
        if save:
            new_lines = [ln.strip() for ln in self.editor.toPlainText().splitlines()
                         if ln.strip()]
            speaker = " ".join(self.speaker_edit.text().split()) or None
            # after Undo Fix the shown text isn't saved yet: Save Edit keeps it (like Save Undo)
            if (new_lines != self._lines or speaker != (self._speaker or None)
                    or getattr(self, "_undone", False)):
                # the app re-analyzes and calls show_text
                self.text_edited.emit(new_lines, speaker)

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
        self._fit_bottom_bar()
        self._geometry_timer.start()

    def _fit_bottom_bar(self) -> None:
        """One row when everything fits, otherwise the OCR controls go to a second row."""
        m = self.layout().contentsMargins()
        room = self.width() - m.left() - m.right()
        need = (self.actions_flow.one_row_width() + self.bottom.spacing()
                + self.ocr_flow.one_row_width())
        direction = (QBoxLayout.Direction.LeftToRight if room >= need
                     else QBoxLayout.Direction.TopToBottom)
        if self.bottom.direction() != direction:
            self.bottom.setDirection(direction)

    def _emit_geometry(self) -> None:
        g = self.geometry()
        self.geometry_changed.emit([g.x(), g.y(), g.width(), g.height()])

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        # Closing only hides; the app keeps running in the tray.
        event.ignore()
        self.hide()
