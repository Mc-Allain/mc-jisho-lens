"""Categories: labelling samples when exporting or merging, filters, the history log."""

import json

from PIL import Image, ImageDraw

from jisho_lens.core.categories import category_suggestions, category_summary, clean_category
from jisho_lens.core.ocr_data import (
    OcrDataStore,
    Sample,
    apply_export,
    apply_import,
    apply_merge,
    label_rows,
    read_pack,
    review_export,
    review_import,
    review_merge,
)


def img(text, size=(160, 40)):
    im = Image.new("RGB", size, (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


def person(folder, lines):
    store = OcrDataStore(folder)
    ids = []
    for ocr, fixed in lines:
        sid = store.add_capture(img(ocr), ocr, engine="rapid-v6", preset="none", seconds=1,
                                speaker=None)
        store.set_truth(sid, fixed, "edited")
        ids.append(sid)
    return store, ids


def test_defaults_and_summary():
    assert category_suggestions() == ["Azur Promilia JP"]
    assert category_suggestions("azur promilia jp", "Menus", "") == ["Azur Promilia JP", "Menus"]
    assert clean_category("  Azur   Promilia JP ") == "Azur Promilia JP"
    assert category_summary(["A", "A", "", "B"]) == "Categories: A 2, B 1, none 1"
    assert category_summary([]) == ""


def test_old_samples_keep_their_text_type():
    old = {"id": "a" * 64, "ocr_text": "x", "category": "dialogue"}  # before categories
    s = Sample.from_dict(old)
    assert (s.text_type, s.category) == ("dialogue", "")
    new = Sample.from_dict({"id": "a" * 64, "ocr_text": "x", "text_type": "text",
                            "category": "Azur Promilia JP"})
    assert (new.text_type, new.category) == ("text", "Azur Promilia JP")


def test_export_review_labels_and_excludes(tmp_path):
    me, ids = person(tmp_path / "me", [("a1", "A1"), ("b1", "B1"), ("c1", "C1")])
    rows = review_export(me)
    assert len(rows) == 3 and all(r.include and r.category == "" for r in rows)
    assert rows[0].before == rows[0].ocr_text and rows[0].after  # OCR read -> your fix
    assert label_rows(rows, "Azur Promilia JP", only=rows[:2]) == 2
    rows[2].include = False  # excluded from this export
    pack = tmp_path / "MyOCR-v1.zip"
    assert apply_export(me, rows, pack, "MyOCR") == 2
    p = read_pack(pack)
    assert {s.category for s in p.samples.values()} == {"Azur Promilia JP"}
    assert p.info.log[0].categories == "Categories: Azur Promilia JP 2"
    assert "Categories: Azur Promilia JP 2" in p.info.history_text()
    # labels are kept on your samples for the next export; the excluded one has none
    assert me.get(rows[0].sid).category == "Azur Promilia JP"
    assert me.get(rows[2].sid).category == "" and len(ids) == 3
    assert me.categories() == ["Azur Promilia JP"]
    assert review_export(me)[0].category in ("Azur Promilia JP", "")


def test_blank_category_stays_blank(tmp_path):
    me, _ = person(tmp_path / "me", [("a1", "A1")])
    pack = tmp_path / "x.zip"
    apply_export(me, review_export(me), pack, "MyOCR")
    p = read_pack(pack)
    assert next(iter(p.samples.values())).category == ""
    assert p.info.log[0].categories == "Categories: none 1"


def test_categories_travel_through_import_and_merge(tmp_path):
    kai, kid = person(tmp_path / "kai", [("k1", "K1"), ("k2", "K2")])
    rows = review_export(kai)
    label_rows(rows, "Azur Promilia JP", only=rows[:1])
    kpack = tmp_path / "KaiOCR-v1.zip"
    apply_export(kai, rows, kpack, "KaiOCR")
    me = OcrDataStore(tmp_path / "me")
    irows = review_import(me, read_pack(kpack))
    assert sorted(r.category for r in irows) == ["", "Azur Promilia JP"]
    apply_import(me, irows)
    assert me.get(kid[0]).category == "Azur Promilia JP"

    raven, _ = person(tmp_path / "raven", [("r1", "R1")])
    rpack = tmp_path / "RavenOCR-v1.zip"
    apply_export(raven, review_export(raven), rpack, "RavenOCR")
    mrows = review_merge([read_pack(kpack), read_pack(rpack)])
    # label the merge rows without a category
    label_rows(mrows, "Menus", only=[r for r in mrows if not r.category])
    out = tmp_path / "Mix-v1.zip"
    apply_merge(mrows, out, me.contributor(), "Mix", me)
    m = read_pack(out)
    assert sorted(s.category for s in m.samples.values()) == ["Azur Promilia JP", "Menus",
                                                              "Menus"]
    assert m.info.log[0].categories == "Categories: Menus 2, Azur Promilia JP 1"


def test_pack_json_has_both_fields(tmp_path):
    me, ids = person(tmp_path / "me", [("a1", "A1")])
    me.set_category(ids[0], "Azur Promilia JP")
    data = json.loads((me.samples_dir / f"{ids[0]}.json").read_text(encoding="utf-8"))
    assert data["category"] == "Azur Promilia JP" and data["text_type"] == "text"
