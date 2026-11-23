"""Shared test setup: the typed delete confirmation is answered by typing into the real
dialog and clicking its real buttons (a modal dialog would otherwise wait forever)."""

import pytest


class TypedConfirm:
    """What the next typed confirmations get: `answer` is typed (None = Cancel clicked
    without typing); every dialog shown is recorded in `shown` (title, text, accepted)."""

    def __init__(self) -> None:
        self.answer: str | None = "delete"
        self.shown: list[tuple[str, str, bool]] = []


@pytest.fixture(autouse=True)
def typed_confirm(monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QDialog, QLabel

    from jisho_lens.ui import confirm_dialog

    QApplication.instance() or QApplication([])
    state = TypedConfirm()

    def scripted(dialog):
        if state.answer is not None:
            QTest.keyClicks(dialog.input, state.answer)
        if dialog.delete_btn.isEnabled():
            QTest.mouseClick(dialog.delete_btn, Qt.MouseButton.LeftButton)
        else:
            QTest.mouseClick(dialog.cancel_btn, Qt.MouseButton.LeftButton)
        text = dialog.findChildren(QLabel)[0].text()
        accepted = dialog.result() == QDialog.DialogCode.Accepted
        state.shown.append((dialog.windowTitle(), text, accepted))
        return dialog.result()

    monkeypatch.setattr(confirm_dialog.ConfirmDeleteDialog, "exec", scripted)
    return state
