"""Edge cases of Phase 4: damaged files, odd packs, empty text, own packs, nothing chosen."""

import json
import zipfile

import pytest
from PIL import Image, ImageDraw

from jisho_lens.core.ocr_data import (
    OcrDataStore,
    PackError,
    apply_export,
    apply_import,
    apply_merge,
    export_pack,
    read_pack,
    review_export,
    review_import,
    review_merge,
    select,
)
from jisho_lens.core.ocr_data.corrections import CorrectionStore, learn_rules
from jisho_lens.core.ocr_data.provenance import Provenance


def img(text, size=(160, 40)):
    im = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


def person(folder, lines):
    store = OcrDataStore(folder)
    ids = []
    for i, (ocr, fixed) in enumerate(lines):
        sid = store.add_capture(img(f"{ocr}{i}"), ocr, engine="rapid-v6", preset="none",
                                seconds=1, speaker=None)
        store.set_truth(sid, fixed, "edited")
        ids.append(sid)
    return store, ids


def rewrite_pack(src, dst, change):
    """Copy a pack, letting `change(name, data) -> data` alter files."""
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst, "w") as b:
        for info in a.infolist():
            b.writestr(info.filename, change(info.filename, a.read(info)))


# ---------- damaged local files
def test_damaged_sample_file_is_skipped_not_a_crash(tmp_path):
    store, ids = person(tmp_path / "s", [("a", "A")])
    (store.samples_dir / f"{ids[0]}.json").write_text("{not json", encoding="utf-8")
    store._cache = None
    assert store.get(ids[0]) is None and store.all() == []


def test_empty_contributor_file_gets_a_new_id(tmp_path):
    store = OcrDataStore(tmp_path / "s")
    first = store.contributor()
    (store.folder / "contributor.txt").write_text("  ", encoding="utf-8")
    new = store.contributor()
    assert len(new) == 16 and new != "" and first != ""


def test_damaged_provenance_files(tmp_path):
    prov = Provenance(tmp_path)
    (tmp_path / "series.json").write_text('{"series": {"X": {"version": "abc"}}}',
                                          encoding="utf-8")
    (tmp_path / "imports.json").write_text('{"imports": [{"pack_id": "p", "used": "oops"}]}',
                                           encoding="utf-8")
    assert prov.next_version("X") == 1
    assert prov.uses({"a"}) == []
    (tmp_path / "imports.json").write_text("garbage", encoding="utf-8")
    assert prov.records() == []


# ---------- odd packs are refused cleanly (PackError), never a crash
def _good_pack(tmp_path):
    store, _ = person(tmp_path / "src", [("a", "A"), ("b", "B")])
    pack = tmp_path / "good.zip"
    export_pack(store, pack, select(store), "Good")
    return pack


def test_non_number_version_is_refused(tmp_path):
    good = _good_pack(tmp_path)
    bad = tmp_path / "bad.zip"

    def change(name, data):
        if name == "manifest.json":
            m = json.loads(data)
            m["version"] = "one"
            return json.dumps(m).encode()
        return data
    rewrite_pack(good, bad, change)
    with pytest.raises(PackError):
        read_pack(bad)


@pytest.mark.parametrize("field,value", [("truth", 5), ("contributor", ["x"]),
                                         ("speaker", 3), ("truth_source", {}),
                                         ("alternatives", [1, 2])])
def test_wrong_types_in_a_sample_are_refused(tmp_path, field, value):
    good = _good_pack(tmp_path)
    bad = tmp_path / "bad.zip"

    def change(name, data):
        if name.endswith(".json") and name != "manifest.json":
            d = json.loads(data)
            d[field] = value
            return json.dumps(d).encode()
        return data
    rewrite_pack(good, bad, change)
    with pytest.raises(PackError):
        read_pack(bad)


def test_damaged_compressed_data_is_refused(tmp_path):
    good = _good_pack(tmp_path)
    raw = bytearray(good.read_bytes())
    # flip bytes inside the first compressed file's data
    start = raw.find(b"samples/") + 200
    for i in range(start, start + 40):
        raw[i] ^= 0xFF
    bad = tmp_path / "bad.zip"
    bad.write_bytes(bytes(raw))
    with pytest.raises(PackError):
        p = read_pack(bad)
        apply_import(OcrDataStore(tmp_path / "me"), review_import(
            OcrDataStore(tmp_path / "me"), p))


def test_pack_moved_after_review_stops_before_writing(tmp_path):
    good = _good_pack(tmp_path)
    me = OcrDataStore(tmp_path / "me")
    rows = review_import(me, read_pack(good))
    good.rename(tmp_path / "moved.zip")
    with pytest.raises(PackError):
        apply_import(me, rows)
    assert me.all() == []  # nothing half-imported


def test_pack_changed_after_review_stops_before_writing(tmp_path):
    good = _good_pack(tmp_path)
    me = OcrDataStore(tmp_path / "me")
    rows = review_import(me, read_pack(good))
    other, _ = person(tmp_path / "o", [("z", "Z")])
    export_pack(other, good, select(other), "Other")  # another pack saved over the file
    with pytest.raises(PackError):
        apply_import(me, rows)
    assert me.all() == []


# ---------- empty OCR text (OCR read nothing; the user typed the text)
def test_empty_ocr_text_is_not_one_sentence(tmp_path):
    store = OcrDataStore(tmp_path / "s")
    a = store.add_capture(img("one"), "", engine="x", preset="none", seconds=1, speaker=None)
    b = store.add_capture(img("two"), "", engine="x", preset="none", seconds=1, speaker=None)
    assert a != b  # two different screenshots, both unread: two samples
    store.set_truth(a, "一", "edited")
    store.set_truth(b, "二", "edited")
    pack = tmp_path / "p.zip"
    export_pack(store, pack, select(store), "P")
    rows = review_import(OcrDataStore(tmp_path / "me"), read_pack(pack))
    assert [r.status for r in rows] == ["new", "new"]
    assert [r.status for r in review_merge([read_pack(pack)])] == ["new", "new"]
    assert store.remove_duplicates() == {}


# ---------- nothing to export or merge: no empty pack, no version used up
def test_nothing_to_export(tmp_path):
    store, _ = person(tmp_path / "s", [("a", "A")])
    rows = review_export(store)
    rows[0].include = False
    with pytest.raises(PackError):
        apply_export(store, rows, tmp_path / "x.zip", "Mine")
    assert not (tmp_path / "x.zip").exists()
    assert store.provenance.next_version("Mine") == 1


def test_nothing_to_merge(tmp_path):
    good = _good_pack(tmp_path)
    rows = review_merge([read_pack(good)])
    for r in rows:
        r.include = False
    me = OcrDataStore(tmp_path / "me")
    with pytest.raises(PackError):
        apply_merge(rows, tmp_path / "m.zip", me.contributor(), "Mix", me)
    assert not (tmp_path / "m.zip").exists() and me.provenance.next_version("Mix") == 1


# ---------- your own pack, and the same pack twice
def test_reimporting_your_own_pack_is_not_listed_as_a_pack(tmp_path):
    me, _ = person(tmp_path / "me", [("a", "A"), ("b", "B")])
    pack = tmp_path / "Mine-v1.zip"
    export_pack(me, pack, select(me), "Mine")
    apply_import(me, review_import(me, read_pack(pack)))
    assert me.using()[0] == "own data"


def test_merging_the_same_pack_twice(tmp_path):
    from jisho_lens.core.ocr_data.packs import merge_sources, unique_packs

    good = _good_pack(tmp_path)
    copy = tmp_path / "copy of good.zip"
    copy.write_bytes(good.read_bytes())
    packs, dropped = unique_packs([read_pack(good), read_pack(copy)])
    assert len(packs) == 1 and dropped == ["copy of good.zip"]
    assert merge_sources(review_merge(packs)) == "Good v1"


# ---------- learning from a rewrite, not a fix
def test_no_rules_learned_from_a_completely_different_text():
    ocr = ["ﾃﾗﾗ一探しにいく、まえにじっちや村長の"]
    typed = ["そういえば明日は村長の誕生日だったね"]
    assert learn_rules(ocr, typed) == []
    store = CorrectionStore(None)  # never saved: nothing learned
    assert store is not None


def test_learning_still_works_for_small_fixes():
    assert learn_rules(["村長の家に寄るそ。"], ["村長の家に寄るぞ。"]) == [("るそ。", "るぞ。")]
