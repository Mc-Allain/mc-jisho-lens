"""A capture of a sentence you already fixed shows your fix; Manage edits behave like Edit.

Edge cases: the speaker line, fixes equal to OCR, several samples of a sentence, the latest
fix, empty text, a longer sentence, collection off, the Manage editor's starting text, and
Manage edits teaching corrections. (Found with real data: a fix made in Manage kept the
speaker line and wasn't shown when the same sentence was captured again.)"""

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from jisho_lens.core.ocr_data import OcrDataStore
from jisho_lens.ui import data_manager as dm

RAW = "ルルカ\nわたしたちを導いてくださる神さまでもあります"  # OCR reads the speaker too
SHOWN = ["わたしたちを導いてくださる神さまでもあります"]  # the window shows it without


def img(n):
    im = Image.new("RGB", (200, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), f"crop {n}", fill=(255, 255, 255))
    return im


def sample(store, n, raw=RAW, truth=None, source="edited", created=None, speaker="ルルカ"):
    sid = store.add_capture(img(n), raw, engine="x", preset="none", seconds=1,
                            speaker=speaker)
    if truth is not None:
        store.set_truth(sid, truth, source)
    if created:
        s = store.get(sid)
        s.created = created
        store.save(s)
    return sid


def test_shows_the_fix_without_the_speaker_line(tmp_path):
    store = OcrDataStore(tmp_path)
    sample(store, 1, truth="ルルカ\nわたしたちを導いてくださる神さまでもあります。")
    assert store.known_fix(RAW, SHOWN) == ["わたしたちを導いてくださる神さまでもあります。"]


def test_no_fix_cases(tmp_path):
    store = OcrDataStore(tmp_path)
    assert store.known_fix(RAW, SHOWN) is None  # nothing saved yet
    sample(store, 1)  # captured, not checked
    assert store.known_fix(RAW, SHOWN) is None
    store2 = OcrDataStore(tmp_path / "b")
    sample(store2, 1, truth="わたしたちを導いてくださる神さまでもあります", source="edited")
    assert store2.known_fix(RAW, SHOWN) is None  # the "fix" is what OCR read
    assert store2.known_fix("", []) is None  # OCR read nothing
    store3 = OcrDataStore(tmp_path / "c")
    sample(store3, 1, truth="ルルカ")  # only a speaker line
    assert store3.known_fix(RAW, SHOWN) is None


def test_a_fix_wins_over_a_checked_sample_and_the_latest_fix_wins(tmp_path):
    store = OcrDataStore(tmp_path)
    # a ✓ sample of another crop, an older fix, a newer fix (kept before duplicates
    # were merged)
    from jisho_lens.core.ocr_data.store import Sample, png_bytes, sample_id

    def keep(n, truth, source, created):
        png = png_bytes(img(n))
        store.save(Sample(id=sample_id(png), ocr_text=RAW, speaker="ルルカ", truth=truth,
                          truth_source=source, created=created, source_pack_id=""), png)

    keep(1, SHOWN[0], "confirmed", "2026-11-23T10:00:00")
    keep(2, "わたしたちを導いてくださる神さまでもあります。", "edited", "2026-11-23T11:00:00")
    keep(3, "わたしたちを導いてくださる神様でもあります。", "edited", "2026-11-23T12:00:00")
    assert store.known_fix(RAW, SHOWN) == ["わたしたちを導いてくださる神様でもあります。"]


def test_only_the_exact_sentence(tmp_path):
    store = OcrDataStore(tmp_path)
    sample(store, 1, truth="ルルカ\nわたしたちを導いてくださる神さまでもあります。")
    longer = RAW + "よ"
    assert store.known_fix(longer, [SHOWN[0] + "よ"]) is None
    # spaces and line breaks don't matter
    assert store.known_fix("ルルカ\nわたしたちを 導いてくださる\n神さまでもあります",
                           ["わたしたちを 導いてくださる", "神さまでもあります"]) == [
        "わたしたちを導いてくださる神さまでもあります。"]


def test_already_shown_fix_is_not_reapplied(tmp_path):
    store = OcrDataStore(tmp_path)
    sample(store, 1, truth="ルルカ\nわたしたちを導いてくださる神さまでもあります。")
    assert store.known_fix(RAW, ["わたしたちを導いてくださる神さまでもあります。"]) is None


# ---------- Manage OCR data
@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize("truth,speaker,expected", [
    (None, "ルルカ", SHOWN[0]),  # no answer yet: what OCR read, without the speaker
    ("ルルカ\nわたしたち。", "ルルカ", "わたしたち。"),  # an answer saved with the speaker
    ("わたしたち。", "ルルカ", "わたしたち。"),
    (None, None, RAW),  # no speaker detected: nothing removed
])
def test_manage_editor_starts_without_the_speaker_line(tmp_path, qapp, truth, speaker,
                                                       expected):
    store = OcrDataStore(tmp_path)
    sid = sample(store, 1, truth=truth, speaker=speaker)
    dlg = dm.EditAnswersDialog(store, [store.get(sid)])
    assert dlg.editor.toPlainText() == expected
    dlg.close()


def test_manage_edit_teaches_corrections_and_syncs_history(tmp_path, qapp, monkeypatch):
    store = OcrDataStore(tmp_path)
    sid = sample(store, 1)
    calls = []
    win = dm.DataManagerWindow(store, on_answer=lambda s, t, sp=None: calls.append((s, t)))

    def fake_exec(self):
        self.editor.setPlainText(SHOWN[0] + "。")
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(dm.EditAnswersDialog, "exec", fake_exec)
    win.table.item(0, dm.COL_TICK).setCheckState(Qt.CheckState.Checked)
    win.edit_btn.click()
    assert calls == [(sid, SHOWN[0] + "。")]
    assert store.get(sid).answer_lines() == [SHOWN[0] + "。"]
    assert store.known_fix(RAW, SHOWN) == [SHOWN[0] + "。"]
    win.close()


# ---------- the app: Manage edits learn only while collecting
@pytest.mark.parametrize("collect,learned", [("yes", True), ("no", False)])
def test_manage_edit_learning_follows_collection(tmp_path, collect, learned):
    from jisho_lens.app import JishoLens
    from jisho_lens.core.ocr_data.corrections import CorrectionStore
    from jisho_lens.core.settings import Settings

    store = OcrDataStore(tmp_path)
    sid = sample(store, 1, raw="ルルカ\n村長の家に寄るそ。")
    store.set_truth(sid, "村長の家に寄るぞ。", "edited")
    lens = JishoLens.__new__(JishoLens)  # just the parts this method uses
    lens.settings = Settings()
    lens.settings.data.collect = collect
    lens.ocr_data = store
    lens.corrections = CorrectionStore(tmp_path / "c")
    synced = []
    lens.history = type("H", (), {"sync_text": lambda self, s, t: synced.append((s, t)),
                                  "sync_speaker": lambda self, s, sp: None})()
    lens._on_answer_managed(sid, "村長の家に寄るぞ。")
    assert synced == [(sid, "村長の家に寄るぞ。")]  # History always follows
    rules = [(r.wrong, r.right) for r in lens.corrections.all()]
    assert (rules == [("るそ。", "るぞ。")]) is learned
