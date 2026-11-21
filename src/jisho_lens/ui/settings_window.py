"""Basic settings window (Phase 1: hotkey, capture, OCR, display)."""

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

from jisho_lens.core.hotkey import parse_hotkey
from jisho_lens.core.ocr import ENGINE_NAMES
from jisho_lens.core.ocr.preprocess import PRESETS
from jisho_lens.core.settings import Settings

DELAYS = [0.0, 0.5, 1.0, 2.0]


class SettingsWindow(QDialog):
    applied = Signal(object)  # Settings

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

        form = QFormLayout()
        form.addRow("Capture hotkey", self.hotkey)
        form.addRow("", self.hotkey_hint)
        form.addRow("Capture delay", self.delay)
        form.addRow("OCR engine", self.engine)
        form.addRow("Image preprocessing", self.preset)
        form.addRow("", self.remove_icons)
        form.addRow("", self.speaker)
        form.addRow("Text size", self.font_size)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

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
        self.applied.emit(self._settings)
        self.accept()
