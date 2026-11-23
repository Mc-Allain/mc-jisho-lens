import json
import zipfile

import pytest
from PIL import Image, ImageDraw

from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data import (
    ALL_ANSWERS,
    DIFFERS,
    KEEP_ALTERNATIVE,
    KEEP_MINE,
    NEW,
    SAME,
    SAME_SENTENCE,
    USE_THEIRS,
    OcrDataStore,
    PackError,
    apply_import,
    apply_merge,
    export_pack,
    import_pack,
    merge_packs,
    read_pack,
    review_import,
    review_merge,
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
def make_store(path, texts, truths, source="edited"):
    store = OcrDataStore(path)
    ids = []
    for t, truth in zip(texts, truths, strict=True):
        sid = store.add_capture(img(t), t, engine="rapid-v6", preset="none", seconds=1.0,
                                speaker=None, game="Azur Promilia")
        if truth is not None:
            store.set_truth(sid, truth, source)
        ids.append(sid)
    return store, ids


def test_export_only_edit_fixed(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two", "three"], ["一", None, "三"])
    a.set_truth(ids[2], "three", "confirmed")  # OCR was right: stays on this computer
    assert [s.id for s in select(a)] == [ids[0]]
    assert len(select(a, game="azur promilia")) == 1 and select(a, game="other") == []
    pack = tmp_path / "a.zip"
    assert export_pack(a, pack, a.all()) == 1  # export leaves the others out anyway
    assert set(read_pack(pack).samples) == {ids[0]}


def test_export_import_round_trip(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two", "three"], ["一", "二", None])
    pack = tmp_path / "a.zip"
    assert export_pack(a, pack, select(a)) == 2
    b = OcrDataStore(tmp_path / "b")
    r = import_pack(b, pack)
    assert (r.added, r.duplicates, r.conflicts) == (2, 0, 0)
    assert b.get(ids[0]).truth == "一" and b.png_path(ids[0]).exists()
    r = import_pack(b, pack)  # importing again adds nothing
    assert (r.added, r.skipped) == (0, 2)


def test_old_packs_with_unfixed_samples_are_filtered(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two", "three"], ["一", None, "三"],
                        source="confirmed")
    a.set_truth(ids[0], "壱", "edited")
    pack = tmp_path / "old.zip"
    with zipfile.ZipFile(pack, "w") as zf:  # like a pack from before: everything exported
        zf.writestr("manifest.json", json.dumps({"format": "jisho-lens-ocr-pack",
                                                 "version": 1}))
        for s in a.all():
            zf.write(a.png_path(s.id), f"samples/{s.id}.png")
            zf.writestr(f"samples/{s.id}.json", s.to_json())
    p = read_pack(pack)
    assert set(p.samples) == {ids[0]} and p.skipped == 2
    r = import_pack(OcrDataStore(tmp_path / "b"), pack)
    assert r.added == 1 and r.unanswered == 2


def test_review_import_statuses_and_choices(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two", "three", "four"],
                        ["一", "二", "三", "四"])
    pack = tmp_path / "a.zip"
    export_pack(a, pack, a.all())
    # mine: "one" same answer, "two" another answer, "three" without an answer,
    # "four" is another crop of the same sentence; "five" missing
    b = OcrDataStore(tmp_path / "b")
    b.save(a.get(ids[0]), a.png_path(ids[0]).read_bytes())
    two = a.get(ids[1])
    two.truth = "弐"
    b.save(two, a.png_path(ids[1]).read_bytes())
    three = a.get(ids[2])
    three.truth = three.truth_source = None
    b.save(three, a.png_path(ids[2]).read_bytes())
    b.add_capture(img("four", size=(130, 40)), "four", engine="x", preset="none",
                  seconds=1, speaker=None)
    rows = {r.sid: r for r in review_import(b, read_pack(pack))}
    assert rows[ids[0]].status == SAME and not rows[ids[0]].include
    assert rows[ids[1]].status == DIFFERS and rows[ids[1]].before == "弐" \
        and rows[ids[1]].after == "二" and rows[ids[1]].choice == KEEP_MINE
    assert rows[ids[2]].status == NEW and rows[ids[2]].before is None
    assert rows[ids[3]].status == SAME_SENTENCE and not rows[ids[3]].include
    assert all(r.size > 0 for r in rows.values())

    # nothing is written before apply
    assert b.get(ids[3]) is None and b.get(ids[2]).truth is None
    rows[ids[1]].choice = USE_THEIRS
    r = apply_import(b, list(rows.values()))
    assert (r.added, r.answers_added, r.replaced, r.skipped) == (0, 1, 1, 2)
    assert b.get(ids[1]).truth == "二"
    assert [x["truth"] for x in b.get(ids[1]).alternatives] == ["弐"]  # yours kept
    assert b.get(ids[2]).truth == "三" and b.get(ids[3]) is None


def test_review_import_keep_alternative_and_exclude(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two"], ["一", "二"])
    pack = tmp_path / "a.zip"
    export_pack(a, pack, a.all())
    b, _ = make_store(tmp_path / "b", ["one"], ["壱"])
    rows = {r.sid: r for r in review_import(b, read_pack(pack))}
    rows[ids[0]].choice = KEEP_ALTERNATIVE
    rows[ids[1]].include = False  # excluded: not imported
    r = apply_import(b, list(rows.values()))
    one = b.get(ids[0])
    assert one.truth == "壱" and one.needs_review and one.alternatives[0]["truth"] == "一"
    assert b.get(ids[1]) is None and (r.alternatives, r.skipped) == (1, 1)


def test_import_can_teach_corrections(tmp_path):
    from jisho_lens.core.ocr_data.corrections import CorrectionStore

    a, ids = make_store(tmp_path / "a", ["そうた、探しに"], ["そうだ、探しに"])
    pack = tmp_path / "a.zip"
    export_pack(a, pack, a.all())
    corrections = CorrectionStore(tmp_path / "c")
    r = apply_import(OcrDataStore(tmp_path / "b"),
                     review_import(OcrDataStore(tmp_path / "b"), read_pack(pack)),
                     corrections)
    rule = corrections.all()[0]
    assert r.learned == 1 and (rule.wrong, rule.right) == ("うた、", "うだ、")


def test_merge_review(tmp_path):
    a, ids = make_store(tmp_path / "a", ["one", "two"], ["一", "二"])
    b, _ = make_store(tmp_path / "b", ["one", "two"], ["壱", "二"])  # disagree on "one"
    c = OcrDataStore(tmp_path / "c")
    sid = c.add_capture(img("two", size=(140, 40)), "two", engine="x", preset="none",
                        seconds=1, speaker=None)  # another crop of "two"
    c.set_truth(sid, "二", "edited")
    packs = []
    for store, name in ((a, "a"), (b, "b"), (c, "c")):
        export_pack(store, tmp_path / f"{name}.zip", store.all())
        packs.append(read_pack(tmp_path / f"{name}.zip"))
    rows = {r.sid: r for r in review_merge(packs)}
    one = rows[ids[0]]
    assert one.status == DIFFERS and [x.truth for x in one.answers] == ["一", "壱"]
    assert [x.pack for x in one.answers] == ["a.zip", "b.zip"] and one.choice == ALL_ANSWERS
    assert rows[ids[1]].status == NEW
    assert rows[sid].status == SAME_SENTENCE and not rows[sid].include
    merged = tmp_path / "merged.zip"
    assert apply_merge(list(rows.values()), merged) == 2
    m = read_pack(merged)
    assert m.samples[ids[0]].truth == "一" and m.samples[ids[0]].needs_review
    assert m.samples[ids[0]].alternatives[0]["truth"] == "壱"
    one.choice = 1  # pick b's answer only
    apply_merge(list(rows.values()), merged)
    m = read_pack(merged)
    assert m.samples[ids[0]].truth == "壱" and not m.samples[ids[0]].alternatives
    count, total = merge_packs([p.path for p in packs], tmp_path / "m2.zip")
    assert count == 2 and total.alternatives == 1


def test_test_set_export(tmp_path):
    a, _ = make_store(tmp_path / "a", ["one", "two"], ["一", None], source="confirmed")
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
