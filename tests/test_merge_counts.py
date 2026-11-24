"""Merge review: how many records each pack brings, red when none, and packs bringing
nothing left out of the merged pack's sources and history log."""

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from jisho_lens.core.ocr_data import OcrDataStore, apply_export, read_pack, review_export
from jisho_lens.core.ocr_data.packs import (
    ALL_ANSWERS,
    DIFFERS,
    SAME_SENTENCE,
    apply_merge,
    merge_contributions,
    merge_sources,
    review_merge,
)
from jisho_lens.ui.pack_review import COL_CHOICE, COL_INCLUDE, PackReviewDialog

RED = "#e05555"


def img(text):
    im = Image.new("RGB", (160, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


def make_pack(tmp, name, lines):
    """lines: (picture, OCR text, fix)."""
    store = OcrDataStore(tmp / f"{name}-data")
    for picture, ocr, fixed in lines:
        sid = store.add_capture(img(picture), ocr, engine="rapid-v6", preset="none",
                                seconds=1, speaker=None)
        store.set_truth(sid, fixed, "edited")
    path = tmp / f"{name}-v1.zip"
    apply_export(store, review_export(store), path, name)
    return read_pack(path)


@pytest.fixture
def tmp(tmp_path):
    QApplication.instance() or QApplication([])
    return tmp_path


def counts(rows, packs):
    c = merge_contributions(rows)
    return [c.get(id(p), 0) for p in packs]


def log_names(path):
    return sorted({e.name for e in read_pack(path).info.log})


def merged(tmp, rows, me_name="Mix"):
    me = OcrDataStore(tmp / "me")
    out = tmp / f"{me_name}-out.zip"
    apply_merge(rows, out, me.contributor(), me_name, me)
    return out


# ---------- counting
def test_each_pack_counts_its_own_records(tmp):
    a = make_pack(tmp, "KaiOCR", [("k1", "k1", "K1"), ("k2", "k2", "K2")])
    b = make_pack(tmp, "RavenOCR", [("r1", "r1", "R1")])
    rows = review_merge([a, b])
    assert counts(rows, [a, b]) == [2, 1]
    assert merge_sources(rows) == "KaiOCR v1 + RavenOCR v1"
    assert log_names(merged(tmp, rows)) == ["KaiOCR", "Mix", "RavenOCR"]


def test_a_pack_that_only_repeats_brings_nothing(tmp):
    a = make_pack(tmp, "KaiOCR", [("k1", "k1", "K1"), ("k2", "k2", "K2")])
    b = make_pack(tmp, "RavenOCR", [("k1", "k1", "K1")])  # the same image and answer
    rows = review_merge([a, b])
    assert counts(rows, [a, b]) == [2, 0]
    assert merge_sources(rows) == "KaiOCR v1"
    assert log_names(merged(tmp, rows)) == ["KaiOCR", "Mix"]


def test_unticking_all_of_a_packs_rows(tmp):
    a = make_pack(tmp, "KaiOCR", [("k1", "k1", "K1")])
    b = make_pack(tmp, "RavenOCR", [("r1", "r1", "R1"), ("r2", "r2", "R2")])
    rows = review_merge([a, b])
    for r in rows:
        r.include = r.pack is a
    assert counts(rows, [a, b]) == [1, 0]
    assert merge_sources(rows) == "KaiOCR v1"
    assert log_names(merged(tmp, rows)) == ["KaiOCR", "Mix"]
    rows[1].include = True  # one of them back: in again, partial
    assert counts(rows, [a, b]) == [1, 1]
    assert merge_sources(rows) == "KaiOCR v1 + RavenOCR v1 (partial)"


def test_different_answers_keep_all_or_choose_one(tmp):
    a = make_pack(tmp, "KaiOCR", [("x1", "x1", "X-kai")])
    b = make_pack(tmp, "RavenOCR", [("x1", "x1", "X-raven")])
    rows = review_merge([a, b])
    assert [r.status for r in rows] == [DIFFERS] and rows[0].choice == ALL_ANSWERS
    assert counts(rows, [a, b]) == [1, 1]  # both answers kept
    rows[0].choice = 0  # use Kai's
    assert counts(rows, [a, b]) == [1, 0]
    assert log_names(merged(tmp, rows)) == ["KaiOCR", "Mix"]
    rows[0].choice = 1  # use Raven's (the image is the same one)
    assert counts(rows, [a, b]) == [0, 1]
    assert merge_sources(rows) == "RavenOCR v1"
    assert log_names(merged(tmp, rows, "Mix2")) == ["Mix2", "RavenOCR"]


def test_another_crop_of_the_same_sentence(tmp):
    a = make_pack(tmp, "KaiOCR", [("crop-a", "same sentence", "Same")])
    b = make_pack(tmp, "RavenOCR", [("crop-b", "same sentence", "Same")])
    rows = review_merge([a, b])
    assert rows[1].status == SAME_SENTENCE and not rows[1].include
    assert counts(rows, [a, b]) == [1, 0]  # excluded by default
    rows[1].include = True
    assert counts(rows, [a, b]) == [1, 1]


def test_three_packs_one_brings_nothing(tmp):
    a = make_pack(tmp, "KaiOCR", [("k1", "k1", "K1")])
    b = make_pack(tmp, "RavenOCR", [("k1", "k1", "K1")])
    c = make_pack(tmp, "MiaOCR", [("m1", "m1", "M1")])
    rows = review_merge([a, b, c])
    assert counts(rows, [a, b, c]) == [1, 0, 1]
    assert merge_sources(rows) == "KaiOCR v1 + MiaOCR v1"
    assert log_names(merged(tmp, rows)) == ["KaiOCR", "MiaOCR", "Mix"]


# ---------- the review window (live, through its own controls)
def review(rows, packs):
    d = PackReviewDialog(rows, "merge", title="Review merge", packs=packs,
                         preview=lambda: ("", merge_sources(rows)), show_images=False)
    d.show()
    return d


def header(d, pack):
    label = next(lb for p, lb in d._pack_labels if p is pack)
    return label.text(), RED in label.styleSheet()


def test_review_shows_counts_and_red(tmp):
    a = make_pack(tmp, "KaiOCR", [("k1", "k1", "K1"), ("k2", "k2", "K2")])
    b = make_pack(tmp, "RavenOCR", [("k1", "k1", "K1")])
    c = make_pack(tmp, "MiaOCR", [("m1", "m1", "M1")])
    d = review(review_merge([a, b, c]), [a, b, c])
    text, red = header(d, a)
    assert "2 records in this merge" in text and not red
    text, red = header(d, b)
    assert "0 records in this merge" in text and "not in the history log" in text and red
    text, red = header(d, c)
    assert "1 record in this merge" in text and not red
    d.close()


def test_review_updates_when_unticking_and_ticking(tmp):
    a = make_pack(tmp, "KaiOCR", [("k1", "k1", "K1")])
    b = make_pack(tmp, "RavenOCR", [("r1", "r1", "R1")])
    rows = review_merge([a, b])
    d = review(rows, [a, b])
    i = next(n for n, r in enumerate(rows) if r.pack is b)
    d.table.item(i, COL_INCLUDE).setCheckState(Qt.CheckState.Unchecked)  # the tick box
    assert header(d, b)[1] and "0 records" in header(d, b)[0]
    assert merge_sources(rows) == "KaiOCR v1"
    d.table.item(i, COL_INCLUDE).setCheckState(Qt.CheckState.Checked)
    assert not header(d, b)[1] and "1 record in this merge" in header(d, b)[0]
    d.close()


def test_review_updates_when_choosing_an_answer(tmp):
    a = make_pack(tmp, "KaiOCR", [("x1", "x1", "X-kai")])
    b = make_pack(tmp, "RavenOCR", [("x1", "x1", "X-raven")])
    rows = review_merge([a, b])
    d = review(rows, [a, b])
    box = d.table.cellWidget(0, COL_CHOICE)
    box.setCurrentIndex(box.findData(1))  # Use RavenOCR
    assert header(d, a)[1] and not header(d, b)[1]
    box.setCurrentIndex(box.findData(ALL_ANSWERS))
    assert not header(d, a)[1] and not header(d, b)[1]
    d.close()


def test_import_and_export_reviews_show_no_counts(tmp):
    a = make_pack(tmp, "KaiOCR", [("k1", "k1", "K1")])
    me = OcrDataStore(tmp / "me")
    from jisho_lens.core.ocr_data import review_import

    d = PackReviewDialog(review_import(me, a), "import", title="Import", packs=[a],
                         show_images=False)
    assert "in this merge" not in d._pack_labels[0][1].text()
    d.close()
