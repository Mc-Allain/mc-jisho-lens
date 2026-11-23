"""File dialogs that open in front of their window.

Windows' own file dialog is not always-on-top, so it can open behind the always-on-top
windows of this app (History, the review window, the text window). Qt's own file dialog is
an ordinary window of the app, so the app's stacking rules put it in front of its parent
(see _ChildrenOnTop in app.py), and it is also raised when shown.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QWidget

_OPTIONS = QFileDialog.Option.DontUseNativeDialog


def downloads_dir() -> Path:
    """C:\\Users\\<user>\\Downloads: where every file dialog starts.

    Asks Windows for the Downloads folder (it may have been moved, e.g. to another drive);
    falls back to <home>\\Downloads, then <home>."""
    try:
        import ctypes
        from ctypes import wintypes

        class GUID(ctypes.Structure):
            _fields_ = [("a", wintypes.DWORD), ("b", wintypes.WORD), ("c", wintypes.WORD),
                        ("d", ctypes.c_ubyte * 8)]

        downloads = GUID(0x374DE290, 0x123F, 0x4565,
                         (ctypes.c_ubyte * 8)(0x91, 0x64, 0xE4, 0xC2, 0xBC, 0xFF, 0xEA, 0x1D))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(downloads), 0, None,
                                                      ctypes.byref(out)) == 0:
            path = Path(out.value)
            ctypes.windll.ole32.CoTaskMemFree(out)
            if path.is_dir():
                return path
    except (AttributeError, OSError):
        pass
    fallback = Path.home() / "Downloads"
    return fallback if fallback.is_dir() else Path.home()


_open: list[QFileDialog] = []  # file dialogs open now (at most one after _run starts)


def close_open_dialogs() -> int:
    """Close (cancel) any file dialog that is open. Returns how many were closed."""
    closed = 0
    for old in list(_open):
        try:
            if old.isVisible():
                old.reject()  # its caller gets "" / [] as if cancelled
                closed += 1
        except RuntimeError:  # already deleted
            pass
    return closed


def _run(dialog: QFileDialog) -> list[str]:
    """Only one file dialog at a time: an open one is cancelled first, to avoid two
    exports or imports getting mixed up."""
    close_open_dialogs()
    _open.append(dialog)
    try:
        dialog.setOption(_OPTIONS, True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        if dialog.exec() != QFileDialog.DialogCode.Accepted:
            return []
        return dialog.selectedFiles()
    finally:
        if dialog in _open:
            _open.remove(dialog)
        dialog.deleteLater()


def open_file(parent: QWidget, title: str, folder: str, filters: str) -> str:
    dlg = QFileDialog(parent, title, folder, filters)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFile)
    files = _run(dlg)
    return files[0] if files else ""


def open_files(parent: QWidget, title: str, folder: str, filters: str) -> list[str]:
    dlg = QFileDialog(parent, title, folder, filters)
    dlg.setFileMode(QFileDialog.FileMode.ExistingFiles)
    return _run(dlg)


def save_file(parent: QWidget, title: str, path: str, filters: str,
              suffix: str = "zip") -> str:
    dlg = QFileDialog(parent, title, path, filters)
    dlg.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dlg.setFileMode(QFileDialog.FileMode.AnyFile)
    dlg.setDefaultSuffix(suffix)
    dlg.selectFile(path)
    files = _run(dlg)
    return files[0] if files else ""


def pick_folder(parent: QWidget, title: str, folder: str) -> str:
    dlg = QFileDialog(parent, title, folder)
    dlg.setFileMode(QFileDialog.FileMode.Directory)
    dlg.setOption(QFileDialog.Option.ShowDirsOnly, True)
    files = _run(dlg)
    return files[0] if files else ""
