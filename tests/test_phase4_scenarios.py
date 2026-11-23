"""Phase 4 scenarios: every way to change OCR data, in combination, through the real app
(real windows and buttons; a stand-in OCR). After each step: what the next capture of the
sentence shows, and what depends on the data (learned corrections, History, Manage,
export, the "Using:" label, favorites).

The misread used throughout: OCR reads 「村長の家に寄るそ。」; the fix is 「寄るぞ。」.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from app_harness import AppHarness, picture  # noqa: E402
from PySide6.QtWidgets import QComboBox, QPushButton, QWidget  # noqa: E402

SPK = "ルルカ"
OCR = ["村長の家に寄るそ。"]
FIX = ["村長の家に寄るぞ。"]
OTHER_OCR = ["あの店に寄るそ。"]  # another sentence with the same misread
OTHER_FIX = ["あの店に寄るぞ。"]


@pytest.fixture
def h(tmp_path):
    with AppHarness(tmp_path) as harness:
        yield harness


def fix_with_edit(h, crop="crop1"):
    h.capture(crop, SPK, OCR)
    h.edit(FIX)
    assert h.sample.is_fix and h.rules()


def recapture(h, crop):
    h.capture(crop, SPK, OCR)
    return h.shown


# ---------- the reported bug: editing the fix back by hand
def test_edit_the_fix_back_to_the_ocr_text(h):
    fix_with_edit(h)
    assert recapture(h, "crop2") == (SPK, FIX) and "Your fix" in h.status
    h.edit(OCR)  # by hand, instead of Undo Fix + Save Undo
    assert not h.sample.is_fix and h.sample.state == "same"
    assert h.rules() == []  # no correction left, and no reverse one learned
    assert recapture(h, "crop3") == (SPK, OCR)
    assert "Your fix" not in h.status and "Applied" not in h.status
    assert h.confirm_text() == "✓ Saved"  # the saved answer is what OCR read


def test_undo_fix_then_save_undo(h):
    fix_with_edit(h)
    recapture(h, "crop2")
    h.undo_fix()
    assert h.shown == (SPK, OCR) and h.confirm_text() == "Save Undo"
    h.confirm()
    assert h.rules() == [] and recapture(h, "crop3") == (SPK, OCR)


def test_undo_redo_saves_nothing(h):
    fix_with_edit(h)
    recapture(h, "crop2")
    before = h.sample.to_json()
    h.undo_fix()
    h.redo_fix()
    h.undo_fix()
    h.redo_fix()
    assert h.sample.to_json() == before and h.shown == (SPK, FIX)
    assert recapture(h, "crop3") == (SPK, FIX)


def test_undo_fix_then_new_capture_keeps_the_fix(h):
    fix_with_edit(h)
    recapture(h, "crop2")
    h.undo_fix()  # only looking, not saving
    assert recapture(h, "crop3") == (SPK, FIX)


# ---------- Undo Fix, then Edit -> Save Edit (reported: the fix kept correcting)
def test_undo_fix_then_edit_done_same_sentence(h):
    fix_with_edit(h)
    recapture(h, "crop2")
    h.undo_fix()
    h.edit()  # the editor already has the OCR text; Save Edit without typing
    assert h.shown == (SPK, OCR) and not h.sample.is_fix
    assert h.confirm_text() == "✓ Saved" and "no fix" in h.status
    assert h.capture_row.edited_text == OCR[0]  # History shows the undone text
    assert h.rules() == [] and recapture(h, "crop3") == (SPK, OCR)


def test_undo_fix_then_edit_done_learned_correction(h):
    fix_with_edit(h)
    h.capture("other1", SPK, OTHER_OCR)
    assert h.shown == (SPK, OTHER_FIX)
    h.undo_fix()
    h.edit()  # Save Edit with the OCR text the editor shows
    assert h.rules() == []
    h.capture("other2", SPK, OTHER_OCR)
    assert h.shown == (SPK, OTHER_OCR) and "Applied" not in h.status
    h.capture("other3", SPK, ["川に寄るそ。"])  # a third sentence: not corrected either
    assert h.shown == (SPK, ["川に寄るそ。"])
    assert recapture(h, "crop9") == (SPK, FIX)  # your own fix of the first sentence stays


def test_undo_fix_then_edit_only_the_name(h):
    fix_with_edit(h)
    h.capture("other1", SPK, OTHER_OCR)
    h.undo_fix()
    h.edit(speaker="リリカ")  # the text kept as OCR read it, only the name changed
    assert h.shown == ("リリカ", OTHER_OCR) and h.rules() == []
    h.capture("other2", SPK, ["川に寄るそ。"])
    assert h.shown == (SPK, ["川に寄るそ。"])


def test_undo_fix_then_edit_cancel_or_retype_the_fix(h):
    fix_with_edit(h)
    h.capture("other1", SPK, OTHER_OCR)
    h.undo_fix()
    h.edit(cancel=True)  # Cancel saves nothing: still only looking
    assert h.confirm_text() == "Save Undo" and h.rules()
    h.edit(OTHER_FIX)  # typed the fix again: the correction was right
    assert h.rules()
    h.capture("other2", SPK, ["川に寄るそ。"])
    assert h.shown == (SPK, ["川に寄るぞ。"])


def test_undo_redo_then_edit_done_keeps_the_fix(h):
    fix_with_edit(h)
    h.capture("other1", SPK, OTHER_OCR)
    h.undo_fix()
    h.redo_fix()
    h.edit()  # Save Edit on the fixed text: nothing undone
    assert h.rules()
    h.capture("other2", SPK, ["川に寄るそ。"])
    assert h.shown == (SPK, ["川に寄るぞ。"])


def test_cancel_and_unchanged_edit_change_nothing(h):
    h.capture("crop1", SPK, OCR)
    h.edit(FIX, cancel=True)
    assert h.sample.truth is None and h.rules() == []
    h.edit(OCR)  # Save Edit without changes
    assert h.sample.truth is None and h.rules() == []


# ---------- Manage OCR data
def test_manage_edit_and_edit_back(h):
    h.capture("crop1", SPK, OCR)
    sid = h.lens._sample_id
    h.manage_edit(sid, FIX)
    assert recapture(h, "crop2") == (SPK, FIX)
    assert h.capture_row.lines == FIX  # History shows it too
    h.manage_edit(sid, OCR)
    assert h.rules() == [] and recapture(h, "crop3") == (SPK, OCR)
    assert all(c.lines == OCR for c in h.lens.history.list())  # every capture follows


def test_manage_delete_forgets_everything_built_from_it(h):
    fix_with_edit(h)
    h.manage_delete(h.lens._sample_id)
    assert h.rules() == []
    assert recapture(h, "crop2") == (SPK, OCR)
    assert len(h.lens.history.list()) == 2  # History captures stay


# ---------- deleting collected data
def test_delete_collected_data_in_settings(h):
    fix_with_edit(h)
    h.lens.open_settings()
    h.lens._settings_window._delete_collected()
    h.pump()
    assert h.lens.ocr_data.all() == [] and h.rules() == []
    assert recapture(h, "crop2") == (SPK, OCR)


def test_clear_all_keeps_a_favorites_fix(h):
    fix_with_edit(h)
    h.favorite(True)
    h.lens.open_history()
    h.lens._history_window._clear_all()
    h.pump()
    assert recapture(h, "crop2") == (SPK, FIX)  # the favorite's sample and fix stay


def test_clear_all_without_favorites(h):
    fix_with_edit(h)
    h.lens.open_history()
    h.lens._history_window._clear_all()
    h.pump()
    assert h.rules() == [] and recapture(h, "crop2") == (SPK, OCR)


# ---------- learned corrections on another sentence
def test_learned_correction_on_another_sentence_and_rejecting_it(h):
    fix_with_edit(h)
    h.capture("other1", SPK, OTHER_OCR)
    assert h.shown == (SPK, OTHER_FIX) and "Applied" in h.status
    h.undo_fix()
    assert h.shown == (SPK, OTHER_OCR)
    h.redo_fix()
    assert h.shown == (SPK, OTHER_FIX)
    h.edit(OTHER_OCR)  # this sentence really ends in そ: reject the correction here
    h.capture("other2", SPK, OTHER_OCR)
    assert h.shown == (SPK, OTHER_OCR)  # not applied again
    assert recapture(h, "crop9") == (SPK, FIX)  # your own fix of the first sentence stays


# ---------- the speaker's name
def test_name_fix_and_back(h):
    h.capture("crop1", SPK, OCR)
    h.edit(speaker="リリカ")
    assert h.sample.is_fix and h.capture_row.speaker == "リリカ"
    assert recapture(h, "crop2") == ("リリカ", OCR)
    h.edit(speaker=SPK)  # back to the name OCR read
    assert not h.sample.is_fix
    assert recapture(h, "crop3") == (SPK, OCR)


def test_name_removed_and_restored_with_save_undo(h):
    h.capture("crop1", SPK, OCR)
    h.edit(FIX, speaker=None)
    assert recapture(h, "crop2") == (None, FIX)
    h.undo_fix()
    assert h.shown == (SPK, OCR)
    h.confirm()  # Save Undo
    assert recapture(h, "crop3") == (SPK, OCR) and not h.sample.is_fix


# ---------- ✓ Correct
def test_confirm_ocr_text(h):
    h.capture("crop1", SPK, OCR)
    h.confirm()
    assert h.sample.state == "same" and h.confirm_text() == "✓ Saved"
    assert recapture(h, "crop2") == (SPK, OCR) and h.confirm_text() == "✓ Saved"


# ---------- History
def test_reopening_from_history_shows_the_current_answer(h):
    fix_with_edit(h)
    first = h.lens._capture_id
    recapture(h, "crop2")
    h.edit(OCR)
    h.lens.open_capture(first)
    h.pump()
    assert h.shown == (SPK, OCR)


# ---------- export follows the data
def test_export_follows_fixes(h, tmp_path):
    from jisho_lens.core.ocr_data import review_export
    from jisho_lens.core.ocr_data.packs import release_preview

    fix_with_edit(h)
    rows = review_export(h.lens.ocr_data)
    assert len(rows) == 1
    from jisho_lens.core.ocr_data import apply_export

    apply_export(h.lens.ocr_data, rows, tmp_path / "p.zip", "Mine")
    h.edit(OCR)  # the fix undone
    assert review_export(h.lens.ocr_data) == []  # nothing to share now
    assert release_preview(h.lens.ocr_data, "Mine", [])[1] == "1 removed"


# ---------- a pack's fix
def test_imported_fix_then_deleted(h, tmp_path):
    from jisho_lens.core.ocr_data import (
        OcrDataStore,
        apply_import,
        export_pack,
        read_pack,
        review_import,
        select,
    )

    kai = OcrDataStore(tmp_path / "kai")
    sid = kai.add_capture(picture("kai1"), SPK + "\n" + OCR[0], engine="x", preset="none",
                          seconds=1, speaker=SPK)
    kai.set_truth(sid, FIX[0], "edited")
    export_pack(kai, tmp_path / "KaiOCR-v1.zip", select(kai), "KaiOCR")
    store = h.lens.ocr_data
    apply_import(store, review_import(store, read_pack(tmp_path / "KaiOCR-v1.zip")))
    h.lens._on_history_changed()
    assert recapture(h, "crop1") == (SPK, FIX)  # the pack's fix is used
    assert "KaiOCR v1" in h.w.data_label.full_text()
    h.manage_delete(sid)
    assert recapture(h, "crop2") == (SPK, OCR)
    assert "KaiOCR" not in h.w.data_label.full_text()


def test_editing_an_imported_fix_makes_it_yours(h, tmp_path):
    from jisho_lens.core.ocr_data import (
        OcrDataStore,
        apply_import,
        export_pack,
        read_pack,
        review_import,
        select,
    )

    kai = OcrDataStore(tmp_path / "kai")
    sid = kai.add_capture(picture("kai1"), SPK + "\n" + OCR[0], engine="x", preset="none",
                          seconds=1, speaker=SPK)
    kai.set_truth(sid, FIX[0], "edited")
    export_pack(kai, tmp_path / "KaiOCR-v1.zip", select(kai), "KaiOCR")
    store = h.lens.ocr_data
    apply_import(store, review_import(store, read_pack(tmp_path / "KaiOCR-v1.zip")))
    h.manage_edit(sid, ["村長の家に寄るぞ！"])
    assert store.get(sid).source_label == "own data"
    assert recapture(h, "crop1") == (SPK, ["村長の家に寄るぞ！"])


# ---------- collection off
def test_collection_off_uses_nothing(tmp_path):
    with AppHarness(tmp_path, collect="no") as h:
        h.capture("crop1", SPK, OCR)
        assert h.sample is None and not h.w.confirm_btn.isVisible()
        h.edit(FIX)  # still edits what's shown and History
        assert h.shown == (SPK, FIX) and h.capture_row.lines == FIX
        assert h.rules() == [] and recapture(h, "crop2") == (SPK, OCR)


# ---------- when the full check of learned corrections runs
def _count_checks(h):
    calls = []
    original = h.lens.corrections.prune

    def counting(samples):
        calls.append(1)
        return original(samples)

    h.lens.corrections.prune = counting
    return calls


def test_full_check_only_after_fix_changes(h):
    fix_with_edit(h)  # learn a correction first
    h.capture("warm", SPK, ["準備する。"])  # settles the check after the edit
    calls = _count_checks(h)
    for i in range(5):  # new captures with no answer: no full check
        h.capture(f"new{i}", SPK, [f"新しい文{i}。"])
    h.capture("crop1", SPK, OCR)  # the same picture, read the same: no fix change
    h.capture("crop2", SPK, OCR)  # another crop of a known sentence: nothing saved
    h.capture("new0", SPK, ["新しい文0。"])  # an unchecked sample again
    assert calls == []
    sid = h.lens._sample_id
    h.lens.ocr_data.set_category(sid, "Azur Promilia JP")  # a category is no fix change
    h.capture("new9", SPK, ["新しい文9。"])
    assert calls == []
    h.edit(["新しい文0！"])  # a fix change: the edit checks, then nothing more
    calls.clear()
    h.capture("new8", SPK, ["新しい文8。"])
    assert calls == []
    h.manage_delete(h.lens._sample_id)  # deleting an unchecked sample: no fix change
    calls.clear()
    h.capture("new7", SPK, ["新しい文7。"])
    assert calls == []


def test_full_check_runs_after_each_kind_of_fix_change(h):
    fix_with_edit(h)
    sid = h.lens._sample_id
    calls = _count_checks(h)
    store = h.lens.ocr_data
    changes = [
        ("an answer saved outside the app's windows", lambda: store.set_truth(
            sid, "村長の家に寄るぞ！", "edited")),
        ("a speaker's name", lambda: store.set_speaker(sid, "リリカ")),
        ("a sample with an answer deleted", lambda: store.delete(sid)),
    ]
    for label, change in changes:
        calls.clear()
        change()
        h.capture(f"after-{label}", SPK, ["準備する。"])
        assert calls == [1], label
    assert h.rules() == []  # the deleted fix's correction is gone


def test_full_check_after_the_same_picture_reads_differently(h):
    fix_with_edit(h)
    h.capture("warm", SPK, ["準備する。"])
    calls = _count_checks(h)
    h.capture("crop1", SPK, ["村長の家に寄るそ！"])  # same picture, another reading
    assert calls == []  # checked before the reading was saved
    h.capture("warm", SPK, ["準備する。"])
    assert calls == [1]  # the saved new reading is checked once
    h.capture("warm", SPK, ["準備する。"])
    assert calls == [1]


def test_edit_button_reads_save_edit_while_editing(h):
    h.capture("crop1", SPK, OCR)
    h.w.edit_btn.click()
    assert h.w.edit_btn.text() == "Save Edit" and h.w.cancel_edit_btn.isVisible()
    assert h.w.edit_btn.width() >= h.w.edit_btn.sizeHint().width()  # the text fits
    h.w.edit_btn.click()
    h.pump()
    assert h.w.edit_btn.text() == "Edit" and not h.w.cancel_edit_btn.isVisible()


def _bottom_controls_rects(w):
    from PySide6.QtCore import QPoint, QRect

    rects = []
    for bar in (w.actions_bar, w.ocr_bar):
        for c in bar.findChildren(QWidget):
            if c.isVisibleTo(w) and isinstance(c, (QPushButton, QComboBox)):
                rects.append((c, QRect(c.mapTo(w, QPoint(0, 0)), c.size())))
    return rects


@pytest.mark.parametrize("width", [900, 680, 520, 440, 380])
def test_bottom_buttons_never_overlap(h, width):
    h.capture("crop1", SPK, OCR)  # ✓ and Favorite showing
    for editing in (False, True):
        if editing:
            h.w.edit_btn.click()
        h.w.resize(width, 300)
        h.pump(40)
        rects = _bottom_controls_rects(h.w)
        assert len(rects) >= 10
        for i, (a, ra) in enumerate(rects):
            assert h.w.rect().contains(ra), (a.text() if hasattr(a, "text") else a, width)
            for b, rb in rects[i + 1:]:
                assert not ra.intersects(rb), (a.objectName() or a, b, width, editing)
    h.w.cancel_edit_btn.click()
