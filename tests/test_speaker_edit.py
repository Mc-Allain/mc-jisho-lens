"""Editing the speaker's name (text window Edit, Manage OCR data).

Edge cases: a corrected name, a removed name, a name added where OCR found none, the same
name typed again, a name-only fix (text unchanged), a pack's sample, recapture of the same
sentence (fixed name shown), History sync, the Manage editor and Speaker column, Cancel /
Esc in the text window, and the speaker box in the window's edit mode."""

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data import OcrDataStore
from jisho_lens.ui import data_manager as dm

RAW = "ルルカ\nわたしたちを導いてくださる神さま"


def img(n):
    im = Image.new("RGB", (200, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), f"crop {n}", fill=(255, 255, 255))
    return im


def add(store, n=1, raw=RAW, speaker="ルルカ"):
    return store.add_capture(img(n), raw, engine="x", preset="none", seconds=1,
                             speaker=speaker)


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


# ---------- the data
def test_corrected_name_is_a_fix_and_the_read_name_is_kept(tmp_path):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    store.set_speaker(sid, "ルルカ")  # OCR misread ル as ル? (any correction)
    store.set_speaker(sid, "リリカ")
    s = store.get(sid)
    assert (s.speaker, s.speaker_fix, s.shown_speaker) == ("ルルカ", "リリカ", "リリカ")
    assert s.speaker_fixed and s.is_fix and s.state == "edited"
    assert s.answer_lines() == ["わたしたちを導いてくださる神さま"]  # text unchanged
    assert s.ocr_lines() == ["わたしたちを導いてくださる神さま"]  # still strips the read name


def test_same_name_typed_again_is_no_fix(tmp_path):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    store.set_speaker(sid, " ルルカ ")
    s = store.get(sid)
    assert s.speaker_fix is None and not s.speaker_fixed and s.truth is None


def test_removed_and_added_names(tmp_path):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    store.set_speaker(sid, None)  # not a speaker after all
    s = store.get(sid)
    assert s.speaker_fix == "" and s.shown_speaker is None and s.is_fix
    other = add(store, 2, raw="おはよう", speaker=None)  # OCR found no speaker
    store.set_speaker(other, "テララ")
    s = store.get(other)
    assert s.shown_speaker == "テララ" and s.is_fix


def test_name_change_on_a_pack_sample_makes_it_yours(tmp_path):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    s = store.get(sid)
    s.truth, s.truth_source = "わたしたちを導いてくださる神さま。", "edited"
    s.source_pack, s.source_pack_id = "KaiOCR v1", "abc123"
    store.save(s)
    store.set_speaker(sid, "リリカ")
    assert store.get(sid).source_label == "own data"


def test_recapture_shows_the_fixed_name(tmp_path):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    store.set_speaker(sid, "リリカ")
    known = store.known_fix_sample(RAW)
    assert known is not None and known.shown_speaker == "リリカ"
    # a name-only fix: the text is the same as OCR read, still a known fix
    assert store.known_fix(RAW, ["わたしたちを導いてくださる神さま"]) is None
    assert known.id == sid


def test_history_follows_the_name(tmp_path):
    store = OcrDataStore(tmp_path / "d")
    history = HistoryStore(tmp_path)
    sid = add(store)
    c1 = history.add(img(1), "わたし", speaker="ルルカ", sample_id=sid)
    c2 = history.add(img(2), "わたし", speaker="ルルカ", sample_id=sid)
    history.set_speaker(c1, "リリカ")
    assert history.sync_speaker(sid, "リリカ", except_id=c1) == 1
    assert history.get(c2).speaker == "リリカ"
    assert history.sync_speaker(sid, None) == 2  # removed everywhere
    assert history.get(c1).speaker is None
    history.close()


# ---------- Manage OCR data
def test_manage_editor_and_column(tmp_path, qapp, monkeypatch):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    calls = []
    win = dm.DataManagerWindow(store, on_answer=lambda s, t, sp=None: calls.append((s, t, sp)))
    seen = {}

    def fake_exec(self):
        seen["speaker_box"] = self.speaker_box.text()
        self.speaker_box.setText("リリカ")  # only the name changes
        seen["save"] = self.save_btn.isEnabled()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dm.EditAnswersDialog, "exec", fake_exec)
    win.table.selectRow(0)
    win.edit_btn.click()  # the real button
    assert seen == {"speaker_box": "ルルカ", "save": True}
    assert calls == [(sid, "わたしたちを導いてくださる神さま", "リリカ")]
    s = store.get(sid)
    assert s.shown_speaker == "リリカ" and s.is_fix
    ocr = win.table.item(0, dm.COL_OCR).data(dm._HTML)
    answer = win.table.item(0, dm.COL_ANSWER).data(dm._HTML)
    # the read name is the first line of the OCR read cell
    assert "ルルカ" in _plain(ocr).splitlines()[0]
    assert "リ" in answer and "わたしたち" in answer  # your name + the dialogue, one cell
    assert win.table.columnCount() == 9  # no separate Speaker column
    win.close()


def test_manage_editor_unchanged_name_is_no_change(tmp_path, qapp):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    dlg = dm.EditAnswersDialog(store, [store.get(sid)])
    dlg.speaker_box.setText("ルルカ")  # the same name
    assert dlg.changes == {} and not dlg.save_btn.isEnabled()
    dlg.close()


# ---------- the text window
def test_window_edit_mode_speaker_box(qapp):
    from jisho_lens.ui.main_window import MainWindow

    w = MainWindow(22, True, False)
    w.show_text(["わたしたち"], [], "ルルカ", "x")
    edits = []
    w.text_edited.connect(lambda lines, sp: edits.append((lines, sp)))
    w.edit_btn.click()
    assert w.speaker_edit.text() == "ルルカ"
    w.speaker_edit.setText("リリカ")
    w.cancel_edit_btn.click()  # Cancel: nothing saved
    assert edits == []
    w.edit_btn.click()
    assert w.speaker_edit.text() == "ルルカ"  # back to the shown name
    w.speaker_edit.setText("リリカ")
    QTest.keyClick(w.speaker_edit, Qt.Key.Key_Escape)  # Esc in the name box: Cancel too
    assert edits == []
    w.edit_btn.click()
    w.speaker_edit.setText("  リリカ ")
    w.edit_btn.click()  # Done: name-only change is saved
    assert edits == [(["わたしたち"], "リリカ")]
    w.show_text(["わたしたち"], [], "リリカ", "x")
    w.edit_btn.click()
    w.speaker_edit.setText("")
    w.edit_btn.click()  # removing the name
    assert edits[-1] == (["わたしたち"], None)
    w.edit_btn.click()
    w.edit_btn.click()  # Done without changes: nothing emitted
    assert len(edits) == 2
    w.close()



# ---------- one cell: speaker's name on the first line, the dialogue below
def _plain(html):
    import re

    return re.sub(r"<[^>]+>", "", html.replace("<br>", "\n"))


@pytest.mark.parametrize("speaker,fix,truth,ocr_cell,answer_cell", [
    # name as read, text fixed
    ("ルルカ", None, "わたし。", "ルルカ\nわたし", "ルルカ\nわたし。"),
    # name corrected
    ("ルルカ", "リリカ", "わたし", "ルルカ\nわたし", "リリカ\nわたし"),
    # name removed
    ("ルルカ", "", "わたし", "ルルカ\nわたし", "(no speaker)\nわたし"),
    # no name read, one added
    (None, "テララ", "わたし", "わたし", "テララ\nわたし"),
    # no name at all
    (None, None, "わたし。", "わたし", "わたし。"),
    # not checked yet
    ("ルルカ", None, None, "ルルカ\nわたし", "—"),
])
def test_one_cell_display(tmp_path, speaker, fix, truth, ocr_cell, answer_cell):
    from jisho_lens.core.ocr_data.store import Sample
    from jisho_lens.ui.pack_review import sample_html

    raw = (speaker + "\n" if speaker else "") + "わたし"
    s = Sample(id="a" * 64, ocr_text=raw, speaker=speaker, speaker_fix=fix, truth=truth,
               truth_source="edited" if truth else None)
    before, after = sample_html(s)
    assert _plain(before) == ocr_cell and _plain(after) == answer_cell


def test_one_cell_escapes_names(tmp_path):
    from jisho_lens.core.ocr_data.store import Sample
    from jisho_lens.ui.pack_review import sample_html

    s = Sample(id="a" * 64, ocr_text="<b>X</b>\nわたし", speaker="<b>X</b>",
               speaker_fix="<i>Y</i>", truth="わたし", truth_source="edited")
    before, after = sample_html(s)
    assert "<b>X" not in before and "&lt;" in before and "<i>" not in after


def test_export_review_shows_name_and_dialogue_in_one_cell(tmp_path, qapp):
    from jisho_lens.core.ocr_data import review_export
    from jisho_lens.ui.pack_review import COL_AFTER, COL_BEFORE, PackReviewDialog

    store = OcrDataStore(tmp_path)
    sid = add(store)
    store.set_truth(sid, "わたしたちを導いてくださる神さま。", "edited")
    store.set_speaker(sid, "リリカ")
    dlg = PackReviewDialog(review_export(store), "export")
    before = _plain(dlg.table.item(0, COL_BEFORE).data(dm._HTML))
    after = _plain(dlg.table.item(0, COL_AFTER).data(dm._HTML))
    assert before.splitlines() == ["ルルカ", "わたしたちを導いてくださる神さま"]
    assert after.splitlines() == ["リリカ", "わたしたちを導いてくださる神さま。"]
    assert dlg.table.columnCount() == 10  # no Speaker column added
    dlg.close()


def test_editor_preview_follows_the_name_box(tmp_path, qapp):
    store = OcrDataStore(tmp_path)
    sid = add(store)
    dlg = dm.EditAnswersDialog(store, [store.get(sid)])
    dlg.speaker_box.setText("リリカ")
    assert "リ" in _plain(dlg.diff.text()).split("→")[1]
    dlg.close()
