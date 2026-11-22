"""One-time question: may the app keep captures and corrections to improve OCR?"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

TITLE = "Help improve OCR for your copy of Jisho Lens?"
TEXT = (
    "Allow Jisho Lens to keep your captures and corrections to improve OCR accuracy for "
    "your copy of the app?"
)
DETAILS = (
    "If you allow it, each capture keeps the selected screen area, the text OCR read, the "
    "settings used, and your correction when you use Edit (or ✓ Correct when OCR was right). "
    "Nothing outside the area you select is kept.\n\n"
    "The data stays on this computer. Nothing is sent anywhere unless you export it and "
    "share it yourself.\n\n"
    "You can change this any time in Settings, and delete the collected data there."
)


def ask_consent(parent=None) -> bool:
    box = QMessageBox(parent)
    box.setWindowTitle(TITLE)
    box.setIcon(QMessageBox.Icon.Question)
    box.setText(TEXT)
    box.setInformativeText(DETAILS)
    allow = box.addButton("Allow", QMessageBox.ButtonRole.AcceptRole)
    deny = box.addButton("Don't allow", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(deny)
    box.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
    box.exec()
    return box.clickedButton() is allow
