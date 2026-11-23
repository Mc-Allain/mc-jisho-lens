"""Source pack of each sample: set on import, cleared by your edits; edits and deletes make
the source pack (partial)."""

import json

from PIL import Image, ImageDraw

from jisho_lens.core.ocr_data import (
    KEEP_ALTERNATIVE,
    USE_THEIRS,
    OcrDataStore,
    apply_import,
    export_pack,
    read_pack,
    review_export,
    review_import,
    select,
)


def img(text):
    im = Image.new("RGB", (160, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


def person(folder, lines):
    store = OcrDataStore(folder)
    ids = []
    for ocr, fixed in lines:
        sid = store.add_capture(img(ocr), ocr, engine="x", preset="none", seconds=1,
                                speaker=None)
        store.set_truth(sid, fixed, "edited")
        ids.append(sid)
    return store, ids


def kai_pack(tmp_path, lines=(("k1", "K1"), ("k2", "K2"), ("k3", "K3"))):
    kai, ids = person(tmp_path / "kai", list(lines))
    pack = tmp_path / "KaiOCR-v1.zip"
    export_pack(kai, pack, select(kai), "KaiOCR")
    return pack, ids


def test_import_sets_the_source_pack(tmp_path):
    pack, ids = kai_pack(tmp_path)
    me = OcrDataStore(tmp_path / "me")
    apply_import(me, review_import(me, read_pack(pack)))
    s = me.get(ids[0])
    assert (s.source_pack, s.source_label) == ("KaiOCR v1", "KaiOCR v1")
    assert s.source_pack_id == read_pack(pack).info.pack_id
    mine = me.add_capture(img("own"), "own", engine="x", preset="none", seconds=1,
                          speaker=None)
    assert me.get(mine).source_label == "own data"


def test_deleting_one_record_makes_the_pack_partial(tmp_path):
    pack, ids = kai_pack(tmp_path)
    me = OcrDataStore(tmp_path / "me")
    apply_import(me, review_import(me, read_pack(pack)))
    assert me.using()[0] == "KaiOCR v1"
    me.delete(ids[1])
    assert me.using()[0] == "KaiOCR v1 (partial)"
    assert "1 deleted since" in me.using_details()


def test_editing_a_pack_record_makes_it_yours_and_the_pack_partial(tmp_path):
    pack, ids = kai_pack(tmp_path)
    me = OcrDataStore(tmp_path / "me")
    apply_import(me, review_import(me, read_pack(pack)))
    me.set_truth(ids[0], "K1 fixed", "edited")  # Edit in the text window or Manage
    s = me.get(ids[0])
    assert (s.source_pack, s.source_label) == ("", "own data")
    assert me.using()[0] == "KaiOCR v1 (partial) + own data"
    assert "1 changed by you" in me.using_details()
    # the same text again (e.g. ✓ Correct) doesn't change the source
    me.set_truth(ids[1], "K2", "confirmed")
    assert me.get(ids[1]).source_label == "KaiOCR v1"


def test_use_theirs_and_alternative(tmp_path):
    pack, ids = kai_pack(tmp_path, (("k1", "K1"), ("k2", "K2")))
    me, _ = person(tmp_path / "me", [("k1", "mine1"), ("k2", "mine2")])
    rows = review_import(me, read_pack(pack))
    by = {r.sid: r for r in rows}
    by[ids[0]].choice = USE_THEIRS
    by[ids[1]].choice = KEEP_ALTERNATIVE
    apply_import(me, rows)
    assert me.get(ids[0]).source_label == "KaiOCR v1"  # their answer now
    assert me.get(ids[1]).source_label == "own data"  # your answer stays
    assert me.using()[0] == "KaiOCR v1 + own data"


def test_same_records_are_not_partial(tmp_path):
    pack, ids = kai_pack(tmp_path, (("k1", "K1"),))
    me, _ = person(tmp_path / "me", [("k1", "K1")])  # identical already
    apply_import(me, review_import(me, read_pack(pack)))
    assert me.get(ids[0]).source_label == "own data"
    assert me.using()[0] == "KaiOCR v1 + own data"


def test_export_review_shows_the_source(tmp_path):
    pack, ids = kai_pack(tmp_path, (("k1", "K1"),))
    me, mine = person(tmp_path / "me", [("m1", "M1")])
    apply_import(me, review_import(me, read_pack(pack)))
    sources = {r.sid: r.sample.source_label for r in review_export(me)}
    assert sources == {ids[0]: "KaiOCR v1", mine[0]: "own data"}


def test_backfill_for_samples_imported_before(tmp_path):
    pack, ids = kai_pack(tmp_path, (("k1", "K1"), ("k2", "K2")))
    me, mine = person(tmp_path / "me", [("m1", "M1")])
    apply_import(me, review_import(me, read_pack(pack)))
    # make it look like before: no source on samples, everything in "used"
    for sid in ids + mine:  # older data: no source field on any sample
        path = me.samples_dir / f"{sid}.json"
        d = json.loads(path.read_text(encoding="utf-8"))
        d.pop("source_pack"), d.pop("source_pack_id")
        path.write_text(json.dumps(d), encoding="utf-8")
    imports = me.folder / "imports.json"
    data = json.loads(imports.read_text(encoding="utf-8"))
    data["imports"][0]["used"] += mine
    data["imports"][0].pop("same", None)
    imports.write_text(json.dumps(data), encoding="utf-8")
    me._cache = None
    assert me.using()[0] == "KaiOCR v1 + own data"  # backfilled on first use
    assert me.get(ids[0]).source_label == "KaiOCR v1"
    assert me.get(mine[0]).source_label == "own data"
    assert (me.folder / "sources-1.done").exists()
