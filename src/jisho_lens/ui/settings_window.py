"""Settings window: hotkey, capture, OCR, display, word splitting and components."""

from __future__ import annotations

import copy

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QKeySequenceEdit,
    QLabel,
    QSpinBox,
    QVBoxLayout,
)

from jisho_lens.components import is_installed as components_installed
from jisho_lens.core.analysis import SPLITTING_LABELS, SPLITTING_MODES, available_modes
from jisho_lens.core.hotkey import parse_hotkey
from jisho_lens.core.ocr import ENGINE_NAMES
from jisho_lens.core.ocr.preprocess import PRESETS
from jisho_lens.core.settings import Settings
from jisho_lens.ui.components_panel import ComponentsPanel

DELAYS = [0.0, 0.5, 1.0, 2.0]


class SettingsWindow(QDialog):
    applied = Signal(object)  # Settings
    components_changed = Signal(list)  # component ids installed / removed

    def __init__(self, settings: Settings, hotkey_ok: bool = True) -> None:
        super().__init__(None, Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle("Jisho Lens settings")
        self._settings = copy.deepcopy(settings)

        self.hotkey = QKeySequenceEdit(QKeySequence(settings.capture.hotkey))
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey_hint = QLabel()
        self.hotkey_hint.setStyleSheet("color: #c0392b;")
        if not hotkey_ok:
            self.hotkey_hint.setText("This hotkey couldn't be registered; choose another.")

        self.delay = QComboBox()
        for d in DELAYS:
            self.delay.addItem("No delay" if d == 0 else f"{d:g} s", d)
        self.delay.setCurrentIndex(max(0, DELAYS.index(settings.capture.delay_seconds))
                                   if settings.capture.delay_seconds in DELAYS else 0)
        self.delay.setToolTip("Wait after selecting before reading the screen, so a line that "
                              "is still appearing letter by letter can finish.")

        self.engine = QComboBox()
        self.engine.addItems(ENGINE_NAMES)
        self.engine.setCurrentText(settings.ocr.engine)
        self.preset = QComboBox()
        self.preset.addItems(PRESETS)
        self.preset.setCurrentText(settings.ocr.preset)

        self.remove_icons = QCheckBox("Remove key icons like [T] or Esc")
        self.remove_icons.setChecked(settings.capture.remove_key_icons)
        self.speaker = QCheckBox("Show the speaker's name separately")
        self.speaker.setChecked(settings.capture.detect_speaker)

        self.font_size = QSpinBox()
        self.font_size.setRange(12, 48)
        self.font_size.setValue(settings.window.font_size)

        # Word splitting: None or an installed UniDic. Dictionaries are used when installed.
        self.splitting = QComboBox()
        self.splitting_hint = QLabel()
        self.splitting_hint.setWordWrap(True)
        self.splitting_hint.setStyleSheet("color: #8a8f99;")
        self._fill_splitting(settings.analysis.word_splitting)
        self.components = ComponentsPanel(self)
        self.components.changed.connect(self._components_changed)

        form = QFormLayout()
        form.addRow("Capture hotkey", self.hotkey)
        form.addRow("", self.hotkey_hint)
        form.addRow("Capture delay", self.delay)
        form.addRow("OCR engine", self.engine)
        form.addRow("Image preprocessing", self.preset)
        form.addRow("", self.remove_icons)
        form.addRow("", self.speaker)
        form.addRow("Text size", self.font_size)
        form.addRow("Word splitting", self.splitting)
        form.addRow("", self.splitting_hint)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.components)
        layout.addWidget(buttons)

    def _fill_splitting(self, current: str) -> None:
        """None, plus every installed UniDic."""
        availability = available_modes()
        self.splitting.clear()
        for mode in SPLITTING_MODES:
            if availability.get(mode) is None:
                self.splitting.addItem(SPLITTING_LABELS[mode], mode)
        idx = self.splitting.findData(current)
        self.splitting.setCurrentIndex(idx if idx >= 0 else self.splitting.findData("none"))
        self.splitting_hint.setText(
            "" if self.splitting.count() > 1 else
            "Install UniDic-lite or full UniDic below for clickable words, readings and "
            "dictionaries.")

    def _components_changed(self, changed: list) -> None:
        current = self.splitting.currentData()
        newly = {"unidic-lite": "lite", "unidic-full": "full"}
        # select a word splitter that was just installed if none was selected
        for cid in changed:
            if cid in newly and components_installed(cid) and current == "none":
                current = newly[cid]
        self._fill_splitting(current)
        self.components_changed.emit(changed)

    def reject(self) -> None:  # noqa: D102
        if self.components.busy:
            return  # don't close while installing / removing
        super().reject()

    def _accept(self) -> None:
        seq = self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if seq:
            try:
                parse_hotkey(seq)
            except ValueError as exc:
                self.hotkey_hint.setText(str(exc))
                return
            self._settings.capture.hotkey = seq
        self._settings.capture.delay_seconds = float(self.delay.currentData())
        self._settings.ocr.engine = self.engine.currentText()
        self._settings.ocr.preset = self.preset.currentText()
        self._settings.capture.remove_key_icons = self.remove_icons.isChecked()
        self._settings.capture.detect_speaker = self.speaker.isChecked()
        self._settings.window.font_size = self.font_size.value()
        self._settings.analysis.word_splitting = self.splitting.currentData() or "none"
        self.applied.emit(self._settings)
        self.accept()
