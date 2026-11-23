"""History captures and OCR data samples stay linked by the text you see: a capture of a
sentence links to the sample whose answer is its text; favorites protect that sample; edits
in Manage show in History. (Found with real data: a favorite was linked to an older sample
with a wrong answer, and Clear all deleted the sample with the favorite's text.)"""

from PIL import Image, ImageDraw

from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data import OcrDataStore
from jisho_lens.core.ocr_data.corrections import CorrectionStore
from jisho_lens.core.ocr_data.store import png_bytes
from jisho_lens.core.storage import clear_all, relink_captures

OCR = "テララ\nそうた、村長の家に寄るそ。"
WRONG = "そうだ、村長の家に寄るそ。た！"  # an older, wrong fix
RIGHT = "そうだ、村長の家に寄るぞ。"  # what the favorite shows


def img(n):
    im = Image.new("RGB", (200, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), f"crop {n}", fill=(255, 255, 255))
    return im


def setup(tmp_path):
    data = OcrDataStore(tmp_path / "ocr-data")
    history = HistoryStore(tmp_path)
    a = data.add_capture(img(1), OCR, engine="x", preset="none", seconds=1, speaker="テララ")
    data.set_truth(a, WRONG, "edited")
    # a second crop kept before duplicates were merged, with the right text
    from jisho_lens.core.ocr_data.store import Sample, sample_id

    png = png_bytes(img(2))
    b = sample_id(png)
    data.save(Sample(id=b, ocr_text=OCR, truth=RIGHT, truth_source="edited",
                     created="2026-11-22T22:40:00", contributor=data.contributor(),
                     source_pack_id=""), png)
    return data, history, a, b


def test_new_capture_links_to_the_sample_with_its_text(tmp_path):
    data, history, a, b = setup(tmp_path)
    # a later crop: OCR read the same, your corrections made it RIGHT
    sid = data.add_capture(img(3), OCR, engine="x", preset="none", seconds=1,
                           speaker="テララ", shown=RIGHT)
    assert sid == b
    # without a matching answer it still links to a checked one
    assert data.add_capture(img(4), OCR, engine="x", preset="none", seconds=1,
                            speaker="テララ") in (a, b)
    history.close()


def test_repair_relinks_the_favorite_and_clear_all_keeps_the_right_sample(tmp_path):
    data, history, a, b = setup(tmp_path)
    fav = history.add(img(3), RIGHT, speaker="テララ", sample_id=a)  # the old, wrong link
    history.set_favorite(fav, True)
    assert relink_captures(history, data) == (1, 0)
    assert history.get(fav).sample_id == b  # the sample with the favorite's text
    captures, samples, kept = clear_all(history, data, CorrectionStore(tmp_path / "c"))
    assert {s.id for s in data.all()} == {b}  # the right one stays, the wrong one is gone
    history.close()


def test_repair_keeps_the_favorites_own_picture_when_no_sample_has_its_text(tmp_path):
    data, history, a, b = setup(tmp_path)
    data.delete(b)  # e.g. Clear all deleted it before this fix
    fav = history.add(img(3), RIGHT, speaker="テララ", sample_id=a)
    history.set_favorite(fav, True)
    assert relink_captures(history, data) == (1, 1)
    new = history.get(fav).sample_id
    assert new != a and data.get(new).truth == RIGHT
    assert data.get(new).ocr_text == OCR and data.get(new).source_label == "own data"
    # the wrong sample is no longer protected: it can go
    assert a not in history.favorite_sample_ids()
    history.close()


def test_unstarred_unedited_captures_are_left_alone(tmp_path):
    data, history, a, _b = setup(tmp_path)
    data.delete(_b)
    cid = history.add(img(3), RIGHT, sample_id=a)  # auto-corrected text, not yours
    assert relink_captures(history, data) == (0, 0)
    assert history.get(cid).sample_id == a
    history.close()


def test_answer_changes_show_in_history(tmp_path):
    data, history, a, _b = setup(tmp_path)
    c1 = history.add(img(3), WRONG, sample_id=a)
    c2 = history.add(img(4), "something else", sample_id=a)
    data.set_truth(a, RIGHT, "edited")
    assert history.sync_text(a, RIGHT) == 2
    assert history.get(c1).text == RIGHT and history.get(c2).text == RIGHT
    assert history.sync_text(a, RIGHT) == 0  # already the same
    history.close()
