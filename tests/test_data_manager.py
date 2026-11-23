"""Manage OCR data window, driven through its real buttons (clicked() passes Qt's
"checked" value, which once crashed Edit)."""

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

from jisho_lens.core.ocr_data import OcrDataStore
from jisho_lens.ui import data_manager as dm


def img(text):
    im = Image.new("RGB", (160, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


@pytest.fixture
def window(tmp_path, monkeypatch):
    _app = QApplication.instance() or QApplication([])
    store = OcrDataStore(tmp_path / "data")
    for i, (ocr, fixed) in enumerate([("そうた", "そうだ"), ("寄るそ", "寄るぞ"),
                                      ("ついてに", "ついでに")]):
        sid = store.add_capture(img(f"picture {i}"), ocr, engine="x", preset="none",
                                seconds=1, speaker=None)
        store.set_truth(sid, fixed, "edited")
        s = store.get(sid)
        s.created = f"2026-11-23T1{i}:00:00"
        store.save(s)
    assert len(store.all()) == 3
    win = dm.DataManagerWindow(store)
    seen = {}

    def fake_exec(self):  # what the user does in the editor
        seen.setdefault("opened", []).append(
            ([s.ocr_text for s in self.samples], self.samples[self.index].ocr_text))
        seen["diff"] = self.diff.text()
        self.editor.setPlainText(self.editor.toPlainText() + "！")
        if len(self.samples) > 1:
            self.next_btn.click()
            seen["after_next"] = self.position.text()
            self.prev_btn.click()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dm.EditAnswersDialog, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "question",
                        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    yield win, store, seen
    win.close()


def test_highlighted_row_without_ticks(window):
    win, store, seen = window
    assert not win.edit_btn.isEnabled()
    win.table.selectRow(1)  # highlight one row, nothing ticked
    assert win.edit_btn.isEnabled() and win.delete_btn.isEnabled()
    assert "1 selected" in win.count.text()
    win.edit_btn.click()  # the real button
    assert seen["opened"] == [(["寄るそ"], "寄るそ")]
    assert store.get(win.samples[1].id).truth == "寄るぞ！"
    win.table.selectRow(0)
    win.label_box.setEditText("Azur Promilia JP")
    win.label_box.lineEdit().returnPressed.emit()  # pressing Enter in the box
    assert store.get(win.samples[0].id).category == "Azur Promilia JP"
    win.table.selectRow(0)
    assert win.remove_category_btn.isEnabled()
    win.remove_category_btn.click()  # the real button
    assert store.get(win.samples[0].id).category == ""
    assert "category removed from 1" in win.note.text()
    win.table.selectRow(2)
    win.delete_btn.click()
    assert len(store.all()) == 2


def test_ticked_rows_edit_with_prev_next(window):
    win, store, seen = window
    for row in (0, 2):
        win.table.item(row, dm.COL_TICK).setCheckState(Qt.CheckState.Checked)
    assert win.edit_btn.text() == "Edit answers (2)…"
    win.edit_btn.click()
    order, first = seen["opened"][0]
    assert first == order[0] == "ついてに"  # the latest ticked record first
    assert seen["after_next"] == "2 of 2"
    assert store.get(win.samples[0].id).truth.endswith("！")
    win.delete_btn.click()
    assert len(store.all()) == 1


def test_differences_are_highlighted(window):
    win, _store, seen = window
    row = next(i for i, s in enumerate(win.samples) if s.ocr_text == "そうた")
    ocr = win.table.item(row, dm.COL_OCR).data(dm._HTML)
    answer = win.table.item(row, dm.COL_ANSWER).data(dm._HTML)
    assert "background" in ocr and "た" in ocr  # removed: た
    assert "background" in answer and "だ" in answer  # added: だ
    win.table.selectRow(row)
    win.edit_btn.click()
    assert "→" in seen["diff"] and "background" in seen["diff"]


def test_remove_category_in_export_review(tmp_path):
    from jisho_lens.core.ocr_data import label_rows, review_export
    from jisho_lens.ui.pack_review import COL_INCLUDE, PackReviewDialog

    _app = QApplication.instance() or QApplication([])
    store = OcrDataStore(tmp_path / "d")
    for i in range(3):
        sid = store.add_capture(img(f"picture {i}"), f"ocr{i}", engine="x", preset="none",
                                seconds=1, speaker=None)
        store.set_truth(sid, f"fix{i}", "edited")
    rows = review_export(store)
    label_rows(rows, "Azur Promilia JP", only=rows)
    dlg = PackReviewDialog(rows, "export")
    assert dlg.remove_category_btn.isVisible() or not dlg.isVisible()
    dlg.table.item(2, COL_INCLUDE).setCheckState(Qt.CheckState.Unchecked)
    dlg.remove_category_btn.click()  # the real button: ticked rows lose their category
    assert [r.category for r in rows] == ["", "", "Azur Promilia JP"]
    assert "category removed from 2" in dlg.label_note.text()
    dlg.close()
