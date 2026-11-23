"""Drive the real Jisho Lens app in tests: real windows, real buttons, a stand-in OCR.

    with AppHarness(tmp_path) as h:
        h.capture("crop1", "ルルカ", ["わたしたち"])   # OCR "reads" this from picture crop1
        h.edit(text=["わたしたち。"], speaker="リリカ")  # Edit -> type -> Save Edit (real clicks)
        h.capture("crop2", "ルルカ", ["わたしたち"])   # the same sentence, another crop

The stand-in OCR returns the text the test gives for a picture, through the app's own
cleanup/analysis path (OcrOutcome), so everything after OCR is the real app.
"""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from jisho_lens.core.analysis.pipeline import analyze_text
from jisho_lens.core.ocr.base import OcrLine, OcrResult
from jisho_lens.core.ocr.cleanup import CleanText
from jisho_lens.core.ocr.worker import OcrJob, OcrOutcome


def picture(name: str) -> Image.Image:
    """A distinct picture per name (different crops of a line are different pictures)."""
    im = Image.new("RGB", (220, 50), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 15), name, fill=(255, 255, 255))
    im.info["test_name"] = name
    return im


class FakeOcr(QObject):
    finished = Signal(object)
    failed = Signal(int, str)
    engine_ready = Signal(str, float)
    engine_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.readings: dict[str, tuple[str | None, list[str]]] = {}
        self._next = 0

    def preload(self, *_a, **_k) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def submit(self, image, engine, preset, remove_key_icons=True, detect_speaker=True,
               splitting="none", dictionary=False) -> int:
        self._next += 1
        job = OcrJob(self._next, image, engine, preset, remove_key_icons, detect_speaker,
                     splitting, dictionary)
        speaker, lines = self.readings[image.info["test_name"]]
        raw = OcrResult([OcrLine(t) for t in ([speaker] if speaker else []) + lines])
        cleaned = CleanText(speaker, list(lines))
        outcome = OcrOutcome(job, raw, cleaned, analyze_text(cleaned.lines, "none", False),
                             0.01)
        QTimer.singleShot(0, lambda: self.finished.emit(outcome))
        return self._next


class AppHarness:
    def __init__(self, folder: Path, collect: str = "yes") -> None:
        self.folder = Path(folder)
        self.collect = collect

    # ---------- setup
    def __enter__(self) -> AppHarness:
        os.environ["JISHO_LENS_HOME"] = str(self.folder)
        from jisho_lens.core.settings import Settings

        s = Settings.load()
        s.data.collect = self.collect
        s.analysis.word_splitting = "none"
        s.capture.show_hotkey = ""
        s.save()
        self.qapp = QApplication.instance() or QApplication([])
        self.qapp.setQuitOnLastWindowClosed(False)
        import jisho_lens.app as appmod

        self.appmod = appmod
        self._real_service = appmod.OcrService
        self.ocr = FakeOcr()
        appmod.OcrService = lambda: self.ocr
        self.lens = appmod.JishoLens(self.qapp)
        self.lens.hotkeys.unregister()  # don't hold the user's hotkeys during tests
        self.w = self.lens.window
        self.w.show()
        self._answers: dict = {}
        self._patch_dialogs()
        return self

    def __exit__(self, *exc) -> None:
        self.appmod.OcrService = self._real_service
        for window in (self.lens._history_window, getattr(self.lens, "_data_manager", None)):
            if window is not None:
                window.close()
        self.lens.history.close()
        self.w.close()
        self.w.deleteLater()
        self.lens.tray.hide()
        self.lens.server.close()
        self.pump()

    def _patch_dialogs(self) -> None:
        """Message boxes answer Yes; the Manage editor and other dialogs are scripted."""
        self._orig_question = QMessageBox.question
        QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
        QMessageBox.information = staticmethod(lambda *a, **k: None)

    def pump(self, rounds: int = 20) -> None:
        for _ in range(rounds):
            self.qapp.processEvents()

    # ---------- actions (real buttons)
    def capture(self, name: str, speaker: str | None, lines: list[str]) -> None:
        """A capture of picture `name` that OCR reads as `speaker` + `lines`."""
        self.ocr.readings[name] = (speaker, list(lines))
        self.lens._read(picture(name))
        for _ in range(200):
            self.pump(2)
            if self.lens._pending_job is None:
                break
        self.pump()

    def edit(self, text: list[str] | None = None, speaker: str | None = "keep",
             cancel: bool = False) -> None:
        """Edit -> type -> Save Edit (or Cancel), with the real buttons."""
        self.w.edit_btn.click()
        if text is not None:
            self.w.editor.setPlainText("\n".join(text))
        if speaker != "keep":
            self.w.speaker_edit.setText(speaker or "")
        (self.w.cancel_edit_btn if cancel else self.w.edit_btn).click()
        self.pump()

    def undo_fix(self) -> None:
        assert self.w.undo_btn.isVisible(), "Undo Fix isn't offered"
        self.w.undo_btn.click()
        self.pump()

    def redo_fix(self) -> None:
        assert self.w.redo_btn.isVisible(), "Redo Fix isn't offered"
        self.w.redo_btn.click()
        self.pump()

    def confirm(self) -> None:
        """✓ Correct / Save Undo."""
        assert self.w.confirm_btn.isVisible() and self.w.confirm_btn.isEnabled()
        self.w.confirm_btn.click()
        self.pump()

    def favorite(self, on: bool = True) -> None:
        if self.w.favorite_btn.isChecked() != on:
            self.w.favorite_btn.click()
        self.pump()

    # ---------- Manage OCR data (real buttons; the editor is scripted)
    def manage(self):
        self.lens.open_data_manager()
        self.pump()
        return self.lens._data_manager

    def manage_select(self, sample_id: str):
        dm = self.manage()
        row = next(i for i, s in enumerate(dm.samples) if s.id == sample_id)
        dm.table.clearSelection()
        dm.table.selectRow(row)
        return dm

    def manage_edit(self, sample_id: str, text: list[str] | None = None,
                    speaker: str | None = "keep") -> None:
        from jisho_lens.ui import data_manager

        dm = self.manage_select(sample_id)

        def scripted(dialog):
            if text is not None:
                dialog.editor.setPlainText("\n".join(text))
            if speaker != "keep":
                dialog.speaker_box.setText(speaker or "")
            return QDialog.DialogCode.Accepted

        original = data_manager.EditAnswersDialog.exec
        data_manager.EditAnswersDialog.exec = scripted
        try:
            dm.edit_btn.click()
        finally:
            data_manager.EditAnswersDialog.exec = original
        self.pump()

    def manage_delete(self, sample_id: str) -> None:
        dm = self.manage_select(sample_id)
        dm.delete_btn.click()
        self.pump()

    # ---------- what the app shows / has
    @property
    def shown(self) -> tuple[str | None, list[str]]:
        return (self.w._speaker or None, list(self.w._lines))

    @property
    def status(self) -> str:
        return self.w.status_label.text()

    @property
    def sample(self):
        return self.lens.ocr_data.get(self.lens._sample_id) if self.lens._sample_id else None

    @property
    def capture_row(self):
        return self.lens.history.get(self.lens._capture_id)

    def rules(self) -> list[tuple[str, str]]:
        return [(r.wrong, r.right) for r in self.lens.corrections.all()]

    def confirm_text(self) -> str:
        return self.w.confirm_btn.text()
