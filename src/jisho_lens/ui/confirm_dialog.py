"""Typed confirmation for deletions that can't be undone and lose your own work (samples
fixed with Edit): the Delete button works only after typing the confirm word."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

CONFIRM_WORD = "delete"


def fixes_note(count: int) -> str:
    """The warning line for `count` samples fixed with Edit."""
    return (f"{count} of them {'is' if count == 1 else 'are'} fixed with Edit: your own "
            f"correction{'' if count == 1 else 's'}, lost for good.")


class ConfirmDeleteDialog(QDialog):
    """`text` explains what goes; the user types `word` to enable the Delete button.
    Enter without the word does nothing; Esc or Cancel never deletes."""

    def __init__(self, parent: QWidget | None, title: str, text: str,
                 word: str = CONFIRM_WORD, action: str = "Delete") -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.word = word
        layout = QVBoxLayout(self)
        message = QLabel(text)
        message.setWordWrap(True)
        message.setMinimumWidth(380)
        layout.addWidget(message)
        prompt = QLabel(f"Type <b>{word}</b> to confirm:")
        prompt.setTextFormat(Qt.TextFormat.RichText)
        layout.addWidget(prompt)
        self.input = QLineEdit()  # no placeholder: it would look already typed
        layout.addWidget(self.input)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.delete_btn = QPushButton(action)
        self.delete_btn.setEnabled(False)
        self.delete_btn.setAutoDefault(False)
        self.delete_btn.setStyleSheet(
            "QPushButton:enabled { background: #a33a3a; color: white; }")
        self.cancel_btn = QPushButton("Cancel")
        # no default button: Enter confirms only with the word typed (see _enter); Esc cancels
        self.cancel_btn.setAutoDefault(False)
        buttons.addWidget(self.delete_btn)
        buttons.addWidget(self.cancel_btn)
        layout.addLayout(buttons)
        self.input.textChanged.connect(self._check)
        self.input.returnPressed.connect(self._enter)
        self.delete_btn.clicked.connect(lambda _checked=False: self.accept())
        self.cancel_btn.clicked.connect(lambda _checked=False: self.reject())
        self.input.setFocus()

    def matches(self) -> bool:
        return self.input.text().strip().lower() == self.word.lower()

    def _check(self) -> None:
        self.delete_btn.setEnabled(self.matches())

    def _enter(self) -> None:
        if self.matches():
            self.accept()  # Enter after typing the word confirms; otherwise nothing


def confirm_delete(parent: QWidget | None, title: str, text: str) -> bool:
    """True only when the user typed the confirm word and pressed Delete."""
    return ConfirmDeleteDialog(parent, title, text).exec() == QDialog.DialogCode.Accepted
