import json
import zipfile

import pytest
from PIL import Image, ImageDraw

from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data import (
    OcrDataStore,
    PackError,
    export_pack,
    import_pack,
    merge_packs,
    select,
    to_test_set,
)
from jisho_lens.core.settings import Settings


def img(text: str = "a", size=(120, 40)) -> Image.Image:
    im = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


# ---------- settings ----------
def test_collection_is_off_until_asked():
    s = Settings()
    assert s.data.collect == "ask" and not s.data.collecting
    s.data.collect = "yes"
    assert s.data.collecting


# ---------- history ----------
def test_history_add_edit_retention(tmp_path):
    h = HistoryStore(tmp_path)
    ids = [h.add(img(str(i)), f"text {i}", engine="rapid-v6", preset="none", seconds=1.0)
           for i in range(5)]
    h.set_edited(ids[-1], "fixed text")
    newest = h.list()[0]
    assert newest.id == ids[-1] and newest.text == "fixed text" and newest.image_path.exists()
    assert h.enforce_retention(3) == 2
    assert h.count() == 3 and h.get(ids[0]) is None
    h.delete_all()
    assert h.count() == 0 and not list((tmp_path / "captures").glob("*.png"))
    h.close()


# ---------- collection ----------
def test_samples_dedupe_and_truth(tmp_path):
    store = OcrDataStore(tmp_path / "a")
    sid = store.add_capture(img("x"), "そうだ", engine="rapid-v6", preset="none", seconds=1.2,
                            speaker="テララ")
    assert store.add_capture(img("x"), "そうだ!", engine="windows", preset="none",
                             seconds=0.1, speaker="テララ") == sid  # same image, same sample
    assert store.stats()["samples"] == 1 and store.get(sid).category == "dialogue"
    store.set_truth(sid, "そうだ！", "edited")
    s = store.get(sid)
    assert s.checked and s.truth_source == "edited" and s.engine == "windows"
    assert len(store.contributor()) == 16


# ---------- packs ----------
def make_store(path, texts, truths):
    store = OcrDataStore(path)
    ids = []
    for t, truth in zip(texts, truths, strict=True):
        sid = store.add_capture(img(t), t, engine="rapid-v6", preset="none", seconds=1.0,
                                speaker=None, game="Azur Promilia")
        if truth is not None:
            store.set_truth(sid, truth, "confirmed")
        ids.append(sid)
    return store, ids


def test_export_import_round_trip(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two", "three"], ["一", None, "三"])
    assert len(select(a, "checked")) == 2 and len(select(a, "all")) == 3
    assert len(select(a, "all", game="azur promilia")) == 3
    pack = tmp_path / "a.zip"
    assert export_pack(a, pack, select(a, "checked")) == 2
    b = OcrDataStore(tmp_path / "b")
    r = import_pack(b, pack)
    assert (r.added, r.duplicates, r.conflicts) == (2, 0, 0)
    assert b.get(ids[0]).truth == "一" and b.png_path(ids[0]).exists()
    # importing again adds nothing
    r = import_pack(b, pack)
    assert (r.added, r.duplicates) == (0, 2)


def test_merge_fills_answers_and_flags_conflicts(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two"], ["一", None])
    b, _ = make_store(tmp_path / "b", ["one", "two"], ["壱", "二"])  # disagree on "one"
    pa, pb = tmp_path / "a.zip", tmp_path / "b.zip"
    export_pack(a, pa, a.all())
    export_pack(b, pb, b.all())
    r = import_pack(a, pb)
    assert r.answers_added == 1 and r.conflicts == 1
    one = a.get(ids[0])
    assert one.truth == "一" and one.needs_review
    assert [x["truth"] for x in one.alternatives] == ["壱"]
    assert a.get(ids[1]).truth == "二"
    merged = tmp_path / "merged.zip"
    count, total = merge_packs([pa, pb], merged)
    assert count == 2 and total.conflicts == 1


def test_test_set_export(tmp_path):
    a, _ = make_store(tmp_path / "a", ["one", "two"], ["一", None])
    out = tmp_path / "set"
    assert to_test_set(a, out) == 1
    txt = next(out.glob("*.txt"))
    assert txt.name.startswith("text__") and txt.read_text(encoding="utf-8") == "一"


@pytest.mark.parametrize("bad", ["../evil.png", "samples/../../x.json", "other.txt"])
def test_rejects_unexpected_files(tmp_path, bad):
    pack = tmp_path / "bad.zip"
    with zipfile.ZipFile(pack, "w") as zf:
        zf.writestr("manifest.json", json.dumps({"format": "jisho-lens-ocr-pack", "version": 1}))
        zf.writestr(bad, "x")
    with pytest.raises(PackError):
        import_pack(OcrDataStore(tmp_path / "s"), pack)


def test_rejects_tampered_image(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one"], ["一"])
    good = tmp_path / "a.zip"
    export_pack(a, good, a.all())
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            if info.filename.endswith(".png"):
                import io

                buf = io.BytesIO()
                img("tampered").save(buf, format="PNG")
                data = buf.getvalue()  # no longer matches its hash name
            dst.writestr(info.filename, data)
    with pytest.raises(PackError, match="doesn't match"):
        import_pack(OcrDataStore(tmp_path / "s"), bad)


def test_rejects_non_pack(tmp_path):
    junk = tmp_path / "junk.zip"
    junk.write_bytes(b"not a zip")
    with pytest.raises(PackError):
        import_pack(OcrDataStore(tmp_path / "s"), junk)
