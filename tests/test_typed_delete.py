"""Deleting samples fixed with Edit needs the word typed: the dialog itself (real typing,
real keys) and every way to delete them (Manage, Clear all, Delete collected data), with
what must stay when the deletion is cancelled."""

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

sys.path.insert(0, str(Path(__file__).parent))
from app_harness import AppHarness  # noqa: E402

from jisho_lens.ui.confirm_dialog import ConfirmDeleteDialog, fixes_note  # noqa: E402

SPK = "ルルカ"
OCR = ["村長の家に寄るそ。"]
FIX = ["村長の家に寄るぞ。"]


# ---------- the dialog (real, shown, keyboard and mouse)
@pytest.fixture
def dialog():
    QApplication.instance() or QApplication([])
    d = ConfirmDeleteDialog(None, "Delete", "Delete 1 sample?")
    d.show()
    yield d
    d.close()


def test_delete_button_needs_the_word(dialog):
    assert not dialog.delete_btn.isEnabled()
    for wrong in ("d", "delet", "deletes", "remove", "yes"):
        dialog.input.clear()
        QTest.keyClicks(dialog.input, wrong)
        assert not dialog.delete_btn.isEnabled(), wrong
    QTest.mouseClick(dialog.delete_btn, Qt.MouseButton.LeftButton)  # disabled: no effect
    assert dialog.isVisible()
    for right in ("delete", "DELETE", "Delete", "  delete "):
        dialog.input.clear()
        QTest.keyClicks(dialog.input, right)
        assert dialog.delete_btn.isEnabled(), right


def test_enter_without_the_word_does_nothing(dialog):
    QTest.keyClick(dialog.input, Qt.Key.Key_Return)
    assert dialog.isVisible()
    QTest.keyClicks(dialog.input, "dele")
    QTest.keyClick(dialog.input, Qt.Key.Key_Return)
    assert dialog.isVisible()


def test_enter_with_the_word_deletes(dialog):
    QTest.keyClicks(dialog.input, "delete")
    QTest.keyClick(dialog.input, Qt.Key.Key_Return)
    assert not dialog.isVisible() and dialog.result() == dialog.DialogCode.Accepted


def test_esc_and_cancel_never_delete(dialog):
    QTest.keyClicks(dialog.input, "delete")
    QTest.keyClick(dialog.input, Qt.Key.Key_Escape)
    assert dialog.result() == dialog.DialogCode.Rejected
    dialog.show()
    QTest.mouseClick(dialog.cancel_btn, Qt.MouseButton.LeftButton)
    assert dialog.result() == dialog.DialogCode.Rejected


def test_fixes_note_counts():
    assert "1 of them is fixed with Edit" in fixes_note(1)
    assert "3 of them are fixed with Edit" in fixes_note(3)


# ---------- every way to delete fixes
@pytest.fixture
def h(tmp_path):
    with AppHarness(tmp_path) as harness:
        yield harness


def fix(h, crop="crop1", ocr=OCR, fixed=FIX):
    h.capture(crop, SPK, ocr)
    h.edit(fixed)
    assert h.sample.is_fix


def unchanged(h, samples, rules):
    """Nothing was deleted: samples, learned corrections, History, the next capture."""
    assert len(h.lens.ocr_data.all()) == samples and len(h.rules()) == rules
    h.capture("again", SPK, OCR)
    assert h.shown == (SPK, FIX)


def click_clear_all(h):
    h.lens.open_history()
    h.pump()
    btn = next(b for b in h.lens._history_window.findChildren(QPushButton)
               if b.text() == "Clear all…")
    btn.click()
    h.pump()


def click_delete_collected(h):
    h.lens.open_settings()
    h.pump()
    h.lens._settings_window.delete_data_btn.click()
    h.pump()


@pytest.mark.parametrize("answer", [None, "", "delet", "yes"])
def test_manage_delete_of_a_fix_cancelled(h, typed_confirm, answer):
    fix(h)
    typed_confirm.answer = answer
    h.manage_delete(h.lens._sample_id)
    assert len(typed_confirm.shown) == 1 and not typed_confirm.shown[0][2]
    assert "1 of them is fixed with Edit" in typed_confirm.shown[0][1]
    unchanged(h, 1, 1)


def test_manage_delete_of_a_fix_typed(h, typed_confirm):
    fix(h)
    h.manage_delete(h.lens._sample_id)
    assert typed_confirm.shown and typed_confirm.shown[0][2]
    assert h.lens.ocr_data.all() == [] and h.rules() == []


def test_manage_delete_without_fixes_asks_yes_no_only(h, typed_confirm):
    h.capture("crop1", SPK, ["準備する。"])  # not fixed
    h.capture("crop2", SPK, ["行こう。"])
    h.confirm()  # ✓ Correct: checked, but not fixed with Edit
    h.capture("crop3", SPK, ["待って。"])
    h.edit(["待って。"])  # Edit with no change from OCR: not a fix
    for sid in [s.id for s in h.lens.ocr_data.all()]:
        h.manage_delete(sid)
    assert typed_confirm.shown == [] and h.lens.ocr_data.all() == []


def test_manage_delete_of_several_counts_only_the_fixes(h, typed_confirm):
    fix(h, "crop1")
    fix(h, "crop2", ["待ってくたさい。"], ["待ってください。"])  # another misread
    h.capture("crop3", SPK, ["準備する。"])
    dm = h.manage()
    dm.table.clearSelection()
    dm.table.selectAll()
    typed_confirm.answer = None
    dm.delete_btn.click()
    h.pump()
    assert "2 of them are fixed with Edit" in typed_confirm.shown[0][1]
    assert len(h.lens.ocr_data.all()) == 3


def test_manage_delete_skipping_a_favorites_fix_asks_yes_no(h, typed_confirm):
    fix(h)
    h.favorite(True)  # this fix can't be deleted: nothing of yours is lost
    sid = h.lens._sample_id
    h.capture("crop2", SPK, ["準備する。"])
    dm = h.manage()
    dm.table.selectAll()
    dm.delete_btn.click()
    h.pump()
    assert typed_confirm.shown == []
    assert [s.id for s in h.lens.ocr_data.all()] == [sid]


@pytest.mark.parametrize("answer", [None, "delet"])
def test_clear_all_with_fixes_cancelled(h, typed_confirm, answer):
    fix(h)
    typed_confirm.answer = answer
    click_clear_all(h)
    assert typed_confirm.shown[0][0] == "Clear all" and not typed_confirm.shown[0][2]
    assert len(h.lens.history.list()) == 1  # History is untouched too
    unchanged(h, 1, 1)


def test_clear_all_with_fixes_typed(h, typed_confirm):
    fix(h)
    click_clear_all(h)
    assert typed_confirm.shown[0][2]
    assert h.lens.ocr_data.all() == [] and h.rules() == [] and h.lens.history.list() == []


def test_clear_all_when_the_only_fix_is_a_favorite_asks_yes_no(h, typed_confirm):
    fix(h)
    h.favorite(True)
    h.capture("crop2", SPK, ["準備する。"])
    click_clear_all(h)
    assert typed_confirm.shown == []
    assert [s.is_fix for s in h.lens.ocr_data.all()] == [True]


def test_clear_all_without_fixes_asks_yes_no(h, typed_confirm):
    h.capture("crop1", SPK, ["準備する。"])
    click_clear_all(h)
    assert typed_confirm.shown == [] and h.lens.ocr_data.all() == []


@pytest.mark.parametrize("answer", [None, "delet"])
def test_delete_collected_with_fixes_cancelled(h, typed_confirm, answer):
    fix(h)
    typed_confirm.answer = answer
    click_delete_collected(h)
    assert typed_confirm.shown[0][0] == "Delete collected data"
    assert not typed_confirm.shown[0][2]
    unchanged(h, 1, 1)


def test_delete_collected_with_fixes_typed(h, typed_confirm):
    fix(h)
    click_delete_collected(h)
    assert typed_confirm.shown[0][2]
    assert h.lens.ocr_data.all() == [] and h.rules() == []
    assert len(h.lens.history.list()) == 1  # History is kept


def test_delete_collected_without_fixes_asks_yes_no(h, typed_confirm):
    h.capture("crop1", SPK, ["準備する。"])
    click_delete_collected(h)
    assert typed_confirm.shown == [] and h.lens.ocr_data.all() == []
