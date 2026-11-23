"""Settings window: hotkey, capture, OCR, display, word splitting and components."""

from __future__ import annotations

import copy

from PySide6.QtCore import Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QKeySequenceEdit,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
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
ON_CAPTURE = [
    ("Keep other windows, text window in front", "above"),
    ("Keep other windows in front of the text window", "behind"),
    ("Close other windows", "close"),
]


class SettingsWindow(QDialog):
    applied = Signal(object)  # Settings
    components_changed = Signal(list)  # component ids installed / removed
    data_changed = Signal()  # collected data was deleted

    def __init__(self, settings: Settings, hotkey_ok: bool = True, corrections=None,
                 data=None, history=None) -> None:
        super().__init__(None)  # stacking: see _ChildrenOnTop in app.py
        self.setWindowTitle("Jisho Lens settings")
        self._settings = copy.deepcopy(settings)

        self.hotkey = QKeySequenceEdit(QKeySequence(settings.capture.hotkey))
        self.hotkey.setMaximumSequenceLength(1)
        self.hotkey_hint = QLabel()
        self.hotkey_hint.setStyleSheet("color: #c0392b;")
        if not hotkey_ok:
            self.hotkey_hint.setText("This hotkey couldn't be registered; choose another.")
        self.show_hotkey = QKeySequenceEdit(QKeySequence(settings.capture.show_hotkey))
        self.show_hotkey.setMaximumSequenceLength(1)
        self.show_hotkey.setToolTip("Shows or hides the text window. Clear it for none.")
        self.show_hotkey_hint = QLabel()
        self.show_hotkey_hint.setStyleSheet("color: #c0392b;")
        self.show_hotkey_clear = QPushButton("Clear")
        self.show_hotkey_clear.clicked.connect(self.show_hotkey.clear)

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

        self.on_capture = QComboBox()
        for label, key in ON_CAPTURE:
            self.on_capture.addItem(label, key)
        i = self.on_capture.findData(settings.window.on_capture)
        self.on_capture.setCurrentIndex(i if i >= 0 else 0)
        self.on_capture.setToolTip("What happens to History, Settings and other Jisho Lens "
                                   "windows when you capture text again. Open windows are "
                                   "never in the screenshot.")

        self.font_size = QSpinBox()
        self.font_size.setRange(12, 48)
        self.font_size.setValue(settings.window.font_size)

        # History and OCR data collection (opt-in, local only)
        self.history_keep = QSpinBox()
        self.history_keep.setRange(0, 100000)
        self.history_keep.setSpecialValueText("No limit")
        self.history_keep.setValue(settings.history.keep_last)
        self.history_keep.setSuffix(" captures")
        self.collect = QCheckBox("Keep my captures and corrections to improve OCR accuracy")
        self.collect.setChecked(settings.data.collect == "yes")
        self.collect.setToolTip("Off unless you agree. The data stays on this computer; nothing "
                                "is sent anywhere unless you export and share it yourself.")
        self.game = QLineEdit(settings.data.game)
        self.game.setPlaceholderText("Optional, e.g. Azur Promilia")
        self.delete_data_btn = QPushButton("Delete collected data…")
        self.delete_data_btn.clicked.connect(self._delete_collected)
        self._corrections = corrections
        self._data, self._history = data, history
        self.data_limit = QSpinBox()
        self.data_limit.setRange(0, 100000)
        self.data_limit.setSingleStep(50)
        self.data_limit.setSpecialValueText("No limit")
        self.data_limit.setSuffix(" MB")
        self.data_limit.setValue(settings.data.max_mb)
        self.data_limit.setToolTip("When full, the oldest unchecked samples are removed. "
                                   "Corrected (edited or ✓) samples and favorites are always "
                                   "kept.")
        self.corrections_btn = QPushButton("Learned corrections…")
        self.corrections_btn.setToolTip("Fixes learned from Edit and applied to later captures "
                                        "while OCR data collection is on")
        self.corrections_btn.clicked.connect(self._open_corrections)
        self.corrections_btn.setEnabled(corrections is not None)
        # fixed line breaks: a word-wrapped label in a form gets too little height and is cut
        collect_note = QLabel("Stays on this computer. Nothing is sent anywhere unless\n"
                              "you export it and share it yourself (History → Export pack).")
        collect_note.setStyleSheet("color: #8a8f99;")
        self._collect_note = collect_note

        # Word splitting: None or an installed UniDic. Dictionaries are used when installed.
        self.splitting = QComboBox()
        self.splitting_hint = QLabel()
        self.splitting_hint.setStyleSheet("color: #8a8f99;")
        self._fill_splitting(settings.analysis.word_splitting)
        self.components = ComponentsPanel(self)
        self.components.changed.connect(self._components_changed)

        form = QFormLayout()
        form.addRow("Capture hotkey", self.hotkey)
        form.addRow("", self.hotkey_hint)
        show_row = QHBoxLayout()
        show_row.addWidget(self.show_hotkey, 1)
        show_row.addWidget(self.show_hotkey_clear)
        form.addRow("Show/hide window", show_row)
        form.addRow("", self.show_hotkey_hint)
        form.addRow("Capture delay", self.delay)
        form.addRow("OCR engine", self.engine)
        form.addRow("Image preprocessing", self.preset)
        form.addRow("", self.remove_icons)
        form.addRow("", self.speaker)
        form.addRow("Text size", self.font_size)
        form.addRow("On new capture", self.on_capture)
        form.addRow("Word splitting", self.splitting)
        form.addRow("", self.splitting_hint)
        form.addRow("Keep in History", self.history_keep)
        form.addRow("OCR data", self.collect)
        form.addRow("", self._collect_note)
        form.addRow("Game name", self.game)
        form.addRow("OCR data space", self.data_limit)
        data_buttons = QHBoxLayout()
        data_buttons.addWidget(self.corrections_btn)
        data_buttons.addWidget(self.delete_data_btn)
        data_buttons.addStretch(1)
        form.addRow("", data_buttons)

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
        hint = "" if self.splitting.count() > 1 else (
            "Install UniDic-lite or full UniDic below for clickable words,\n"
            "readings and dictionaries.")
        self.splitting_hint.setText(hint)
        self.splitting_hint.setVisible(bool(hint))  # no empty gap when nothing to say

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

    def _delete_collected(self) -> None:
        from jisho_lens.core.ocr_data import OcrDataStore

        store = self._data or OcrDataStore()
        keep = self._history.favorite_sample_ids() if self._history is not None else set()
        n = store.stats()["samples"]
        kept = f"\n\n{len(keep)} samples of favorites are kept." if keep else ""
        if QMessageBox.question(
                self, "Delete collected data",
                f"Delete all {n} collected OCR samples (corrected ones too) and the learned "
                "corrections from this computer?\n\n"
                f"History is kept. This can't be undone.{kept}",
                defaultButton=QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            store.delete_all(keep)
            if self._corrections is not None:
                self._corrections.delete_all()
            self.data_changed.emit()
            QMessageBox.information(self, "Delete collected data", "Collected data deleted.")

    def _open_corrections(self) -> None:
        from jisho_lens.ui.corrections_dialog import CorrectionsDialog

        CorrectionsDialog(self._corrections, self).exec()

    def _accept(self) -> None:
        seq = self.hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if seq:
            try:
                parse_hotkey(seq)
            except ValueError as exc:
                self.hotkey_hint.setText(str(exc))
                return
            self._settings.capture.hotkey = seq
        show = self.show_hotkey.keySequence().toString(QKeySequence.SequenceFormat.PortableText)
        if show:
            try:
                parse_hotkey(show)
            except ValueError as exc:
                self.show_hotkey_hint.setText(str(exc))
                return
            if show.replace(" ", "").lower() == (seq or self._settings.capture.hotkey) \
                    .replace(" ", "").lower():
                self.show_hotkey_hint.setText("Use a different key from the capture hotkey.")
                return
        self._settings.capture.show_hotkey = show
        self._settings.capture.delay_seconds = float(self.delay.currentData())
        self._settings.ocr.engine = self.engine.currentText()
        self._settings.ocr.preset = self.preset.currentText()
        self._settings.capture.remove_key_icons = self.remove_icons.isChecked()
        self._settings.capture.detect_speaker = self.speaker.isChecked()
        self._settings.window.font_size = self.font_size.value()
        self._settings.window.on_capture = self.on_capture.currentData() or "above"
        self._settings.analysis.word_splitting = self.splitting.currentData() or "none"
        self._settings.history.keep_last = self.history_keep.value()
        self._settings.data.max_mb = self.data_limit.value()
        if self.collect.isChecked():
            self._settings.data.collect = "yes"
        elif self._settings.data.collect == "yes":
            self._settings.data.collect = "no"  # turned off; "ask" stays until answered
        self._settings.data.game = self.game.text().strip()
        self.applied.emit(self._settings)
        self.accept()
