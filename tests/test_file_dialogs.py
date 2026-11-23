"""File dialogs: start in Downloads; only one open at a time."""

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QFileDialog

from jisho_lens.ui import file_dialogs as fd


def _visible() -> list[str]:
    return [w.windowTitle() for w in QApplication.topLevelWidgets()
            if isinstance(w, QFileDialog) and w.isVisible()]


def test_downloads_dir():
    d = fd.downloads_dir()
    assert d.is_dir() and (d.name.lower() == "downloads" or d == Path.home())


def test_opening_another_closes_the_old_one():
    app = QApplication.instance() or QApplication([])
    seen: dict = {}

    def open_second():
        seen["before"] = _visible()
        QTimer.singleShot(200, check_second)
        seen["second"] = fd.open_files(None, "Merge", str(fd.downloads_dir()), "*.zip")

    def check_second():
        seen["during"] = _visible()
        for w in QApplication.topLevelWidgets():
            if isinstance(w, QFileDialog) and w.isVisible():
                w.reject()

    QTimer.singleShot(200, open_second)
    first = fd.open_file(None, "Import", str(fd.downloads_dir()), "*.zip")
    assert seen["before"] == ["Import"]
    assert seen["during"] == ["Merge"]  # the old one was closed
    assert first == "" and seen["second"] == []  # both ended as "cancelled"
    assert _visible() == [] and fd._open == []
    assert app is not None
