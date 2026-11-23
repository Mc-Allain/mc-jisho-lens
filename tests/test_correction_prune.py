"""Learned corrections live only as long as a fix they came from. (Found with real data:
the sample with a fix was deleted in Manage, but its learned correction was still applied
to the next captures of that text.)"""

import json

from PIL import Image, ImageDraw

from jisho_lens.core.ocr_data import OcrDataStore
from jisho_lens.core.ocr_data.corrections import CorrectionStore

RAW = "ルルカ\nわたしたちを導いてくださる神さまでもあります。"
SHOWN = ["わたしたちを導いてくださる神さまでもあります。"]
FIXED = ["わたしたちを導いてくださる神さまでもあります。す。"]


def img(n):
    im = Image.new("RGB", (200, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), f"crop {n}", fill=(255, 255, 255))
    return im


def fixed_sample(store, n=1, raw=RAW, fix=FIXED):
    sid = store.add_capture(img(n), raw, engine="x", preset="none", seconds=1,
                            speaker="ルルカ")
    store.set_truth(sid, "\n".join(fix), "edited")
    return sid


def setup(tmp_path):
    store = OcrDataStore(tmp_path / "d")
    corrections = CorrectionStore(tmp_path / "c")
    sid = fixed_sample(store)
    corrections.learn(SHOWN, FIXED, sample_id=sid)  # Edit in the text window
    assert corrections.apply(SHOWN).lines == FIXED
    return store, corrections, sid


def test_deleting_the_sample_forgets_its_correction(tmp_path):
    store, corrections, sid = setup(tmp_path)
    store.delete(sid)
    assert corrections.prune(store.all()) == 1
    assert corrections.apply(SHOWN).lines == SHOWN  # not applied any more


def test_undoing_or_changing_the_fix_forgets_it(tmp_path):
    store, corrections, sid = setup(tmp_path)
    store.set_truth(sid, SHOWN[0], "edited")  # back to what OCR read
    assert corrections.prune(store.all()) == 1
    store2, corrections2, sid2 = setup(tmp_path / "b")
    store2.set_truth(sid2, "まったく別の答え。", "edited")  # another answer entirely
    assert corrections2.prune(store2.all()) == 1


def test_a_correction_with_two_samples_stays_until_both_are_gone(tmp_path):
    store, corrections, sid = setup(tmp_path)
    # another sentence that teaches the same correction
    other = fixed_sample(store, 2, raw="ルルカ\nこれもあります。", fix=["これもあります。す。"])
    assert other != sid
    corrections.learn(["これもあります。"], ["これもあります。す。"], sample_id=other)
    store.delete(sid)
    assert corrections.prune(store.all()) == 0 and corrections.all()[0].samples == [other]
    store.delete(other)
    assert corrections.prune(store.all()) == 1


def test_older_corrections_without_samples(tmp_path):
    store = OcrDataStore(tmp_path / "d")
    corrections = CorrectionStore(tmp_path / "c")
    sid = fixed_sample(store)
    # a corrections file from before (no "samples"), plus a rule nothing supports
    corrections.path.parent.mkdir(parents=True, exist_ok=True)
    corrections.path.write_text(json.dumps({"format": 1, "rules": [
        {"wrong": "ます。\n", "right": "ます。す。\n", "count": 1, "used": 0,
         "created": "", "last_used": ""},
        {"wrong": "うた、", "right": "うだ、", "count": 1, "used": 0, "created": "",
         "last_used": ""}]}), encoding="utf-8")
    corrections._rules = None
    assert len(corrections.all()) == 2  # old format loads
    assert corrections.prune(store.all()) == 1
    kept = corrections.all()
    assert [r.wrong for r in kept] == ["ます。\n"] and kept[0].samples == [sid]


def test_a_correction_learned_on_top_of_another_survives(tmp_path):
    store = OcrDataStore(tmp_path / "d")
    corrections = CorrectionStore(tmp_path / "c")
    raw = "テララ\nそうた、村長の家に寄るそ。"
    sid = store.add_capture(img(1), raw, engine="x", preset="none", seconds=1,
                            speaker="テララ")
    store.set_truth(sid, "そうだ、村長の家に寄るそ。", "edited")
    corrections.learn(["そうた、村長の家に寄るそ。"], ["そうだ、村長の家に寄るそ。"],
                      sample_id=sid)
    # later: the first correction applied, then the user fixed the rest
    shown = corrections.apply(["そうた、村長の家に寄るそ。"]).lines
    store.set_truth(sid, "そうだ、村長の家に寄るぞ。", "edited")
    corrections.learn(shown, ["そうだ、村長の家に寄るぞ。"], sample_id=sid)
    assert corrections.prune(store.all()) == 0
    assert corrections.apply(["そうた、村長の家に寄るそ。"]).lines == ["そうだ、村長の家に寄るぞ。"]


def test_name_only_fix_teaches_nothing_and_delete_all(tmp_path):
    store, corrections, sid = setup(tmp_path)
    other = store.add_capture(img(3), "テララ\nおはよう", engine="x", preset="none",
                              seconds=1, speaker="テララ")
    store.set_speaker(other, "リリカ")
    s = store.get(other)
    assert corrections.learn(s.ocr_lines(), s.answer_lines(), sample_id=other) == 0
    corrections.delete_all()
    assert corrections.prune(store.all()) == 0 and corrections.all() == []
