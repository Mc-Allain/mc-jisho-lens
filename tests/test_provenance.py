"""Pack names, versions, history logs and the "Using:" label."""

import json
import zipfile

from PIL import Image, ImageDraw

from jisho_lens.core.ocr_data import (
    DIFFERS,
    KEEP_MINE,
    OcrDataStore,
    apply_import,
    apply_merge,
    export_pack,
    read_pack,
    review_import,
    review_merge,
    select,
)
from jisho_lens.core.ocr_data.provenance import clean_name, file_name


def img(text, size=(160, 40)):
    im = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


def person(folder, lines, size=(160, 40)):
    """A user's data: (ocr text, fixed text) pairs, all fixed with Edit."""
    store = OcrDataStore(folder)
    ids = []
    for ocr, fixed in lines:
        sid = store.add_capture(img(ocr, size), ocr, engine="rapid-v6", preset="none",
                                seconds=1, speaker=None)
        store.set_truth(sid, fixed, "edited")
        ids.append(sid)
    return store, ids


def test_names_are_safe_for_files():
    assert clean_name('  Raven/OCR: "best"  ') == "RavenOCR best"
    assert len(clean_name("x" * 99)) == 40
    assert file_name("Raven OCR", 3) == "Raven-OCR-v3.zip"


def test_versions_and_history_log(tmp_path):
    raven, _ = person(tmp_path / "raven", [("a1", "A1"), ("b1", "B1")])
    p1 = tmp_path / file_name("RavenOCR", 1)
    export_pack(raven, p1, select(raven), "RavenOCR")
    info = read_pack(p1).info
    assert (info.label, info.version) == ("RavenOCR v1", 1)
    assert info.log[0].sources == "own data" and info.log[0].samples == 2
    assert raven.provenance.last_name() == "RavenOCR"
    assert raven.provenance.next_version("RavenOCR") == 2
    p2 = tmp_path / file_name("RavenOCR", 2)
    export_pack(raven, p2, select(raven), "RavenOCR")
    info = read_pack(p2).info
    assert info.label == "RavenOCR v2"
    assert [e.version for e in info.log] == [2, 1]  # the history since v1
    assert info.log[0].contributor == raven.contributor()
    assert "by " + raven.contributor()[:8] in info.history_text()
    # a new name starts its own series
    p3 = tmp_path / "x.zip"
    export_pack(raven, p3, select(raven), "OtherName")
    assert read_pack(p3).info.label == "OtherName v1"


def test_using_label(tmp_path):
    kai, kai_ids = person(tmp_path / "kai", [("k1", "K1"), ("k2", "K2"), ("k3", "K3")])
    pack = tmp_path / "KaiOCR-v1.zip"
    export_pack(kai, pack, select(kai), "KaiOCR")

    me = OcrDataStore(tmp_path / "me")
    assert me.using()[0] == "no data yet"
    # only their pack, all of it
    apply_import(me, review_import(me, read_pack(pack)))
    assert me.using()[0] == "KaiOCR v1"
    # + one sample of my own
    me.add_capture(img("mine"), "mine", engine="x", preset="none", seconds=1, speaker=None)
    assert me.using()[0] == "KaiOCR v1 + own data"
    # deleting one of their samples makes it partial
    me.delete(kai_ids[0])
    assert me.using()[0] == "KaiOCR v1 (partial) + own data"
    assert "1 deleted since" in me.using_details()
    # deleting all of them removes the pack from the label
    me.delete(kai_ids[1])
    me.delete(kai_ids[2])
    assert me.using()[0] == "own data"


def test_partial_only_by_your_choice(tmp_path):
    kai, kai_ids = person(tmp_path / "kai", [("k1", "K1"), ("k2", "K2"), ("k3", "K3")])
    pack = tmp_path / "KaiOCR-v1.zip"
    export_pack(kai, pack, select(kai), "KaiOCR")
    # I already have k1 with another answer, and another crop of k2's sentence
    me, _ = person(tmp_path / "me", [("k1", "mine")])
    me.add_capture(img("k2", (170, 40)), "k2", engine="x", preset="none", seconds=1,
                   speaker=None)
    rows = review_import(me, read_pack(pack))
    # defaults: k1 Different answer -> Keep mine (your choice: partial)
    assert any(r.status == DIFFERS and r.choice == KEEP_MINE for r in rows)
    apply_import(me, rows)
    assert me.using()[0] == "KaiOCR v1 (partial) + own data"

    # skipped duplicates alone don't make it partial
    me2 = OcrDataStore(tmp_path / "me2")
    me2.add_capture(img("k2", (170, 40)), "k2", engine="x", preset="none", seconds=1,
                    speaker=None)
    apply_import(me2, review_import(me2, read_pack(pack)))
    assert me2.using()[0] == "KaiOCR v1 + own data"

    # unticking a sample: partial
    me3 = OcrDataStore(tmp_path / "me3")
    rows = review_import(me3, read_pack(pack))
    rows[0].include = False
    apply_import(me3, rows)
    assert me3.using()[0] == "KaiOCR v1 (partial)"


def test_export_carries_imported_logs(tmp_path):
    kai, _ = person(tmp_path / "kai", [("k1", "K1")])
    kpack = tmp_path / "KaiOCR-v1.zip"
    export_pack(kai, kpack, select(kai), "KaiOCR")
    me, _ = person(tmp_path / "me", [("m1", "M1")])
    apply_import(me, review_import(me, read_pack(kpack)))
    out = tmp_path / "RavenOCR-v1.zip"
    export_pack(me, out, select(me), "RavenOCR")
    info = read_pack(out).info
    assert info.log[0].sources == "KaiOCR v1 + own data"
    assert {e.name for e in info.log} == {"RavenOCR", "KaiOCR"}


def test_merge_name_sources_and_logs(tmp_path):
    raven, rid = person(tmp_path / "raven", [("x1", "X1"), ("y1", "Y1")])
    kai, _ = person(tmp_path / "kai", [("x1", "X-one"), ("z1", "Z1")])  # disagree on x1
    pr, pk = tmp_path / "RavenOCR-v1.zip", tmp_path / "KaiOCR-v1.zip"
    export_pack(raven, pr, select(raven), "RavenOCR")
    export_pack(kai, pk, select(kai), "KaiOCR")
    me = OcrDataStore(tmp_path / "me")
    rows = review_merge([read_pack(pr), read_pack(pk)])
    out = tmp_path / "MyMix-v1.zip"
    apply_merge(rows, out, me.contributor(), "MyMix", me)
    info = read_pack(out).info
    assert info.label == "MyMix v1" and info.log[0].action == "merged"
    assert info.log[0].sources == "RavenOCR v1 + KaiOCR v1"
    assert {e.name for e in info.log} == {"MyMix", "RavenOCR", "KaiOCR"}
    # using only Raven's answer for x1 makes Kai's pack partial; next version is v2
    x1 = next(r for r in rows if r.sid == rid[0])
    x1.choice = 0
    out2 = tmp_path / "MyMix-v2.zip"
    apply_merge(rows, out2, me.contributor(), "MyMix", me)
    info = read_pack(out2).info
    assert info.label == "MyMix v2" and info.log[0].sources == "RavenOCR v1 + KaiOCR v1 (partial)"


def test_old_packs_use_the_file_name(tmp_path):
    raven, _ = person(tmp_path / "raven", [("a1", "A1")])
    pack = tmp_path / "friends pack.zip"
    with zipfile.ZipFile(pack, "w") as zf:  # a pack from before names existed
        zf.writestr("manifest.json", json.dumps({"format": "jisho-lens-ocr-pack",
                                                 "version": 1}))
        for s in raven.all():
            zf.write(raven.png_path(s.id), f"samples/{s.id}.png")
            zf.writestr(f"samples/{s.id}.json", s.to_json())
    info = read_pack(pack).info
    assert info.label == "friends pack" and not info.has_history
    me = OcrDataStore(tmp_path / "me")
    apply_import(me, review_import(me, read_pack(pack)))
    assert me.using()[0] == "friends pack"
    # importing the same pack again is recognised (same samples), not counted twice
    apply_import(me, review_import(me, read_pack(pack)))
    assert len(me.provenance.records()) == 1


def test_delete_all_clears_imports_but_keeps_versions(tmp_path):
    raven, _ = person(tmp_path / "raven", [("a1", "A1")])
    export_pack(raven, tmp_path / "r1.zip", select(raven), "RavenOCR")
    me = OcrDataStore(tmp_path / "me")
    apply_import(me, review_import(me, read_pack(tmp_path / "r1.zip")))
    me.delete_all()
    assert me.provenance.records() == [] and me.using()[0] == "no data yet"
    raven.delete_all()
    assert raven.provenance.next_version("RavenOCR") == 2  # versions keep counting


def test_use_theirs_is_not_partial(tmp_path):
    from jisho_lens.core.ocr_data import USE_THEIRS
    from jisho_lens.core.ocr_data.packs import preview_import_label

    kai, _ = person(tmp_path / "kai", [("k1", "K1"), ("k2", "K2")])
    pack = tmp_path / "KaiOCR-v1.zip"
    export_pack(kai, pack, select(kai), "KaiOCR")
    me, _ = person(tmp_path / "me", [("k1", "mine")])
    rows = review_import(me, read_pack(pack))
    assert preview_import_label(me, rows)[1] == "KaiOCR v1 (partial) + own data"  # Keep mine
    next(r for r in rows if r.status == DIFFERS).choice = USE_THEIRS
    # your only sample takes their answer: no own data left
    assert preview_import_label(me, rows) == ("own data", "KaiOCR v1")
    apply_import(me, rows)
    assert me.using()[0] == "KaiOCR v1"
