"""Merge packs list: chosen packs are listed first; Add (more, from other folders),
Remove, Merge (two or more), Cancel; and History's merge flow around it (cancelling a
later step comes back to the list)."""

import shutil

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox

from jisho_lens.core.ocr_data import OcrDataStore, apply_export, read_pack, review_export
from jisho_lens.ui import file_dialogs, history_window
from jisho_lens.ui.merge_list import MergeListDialog
from jisho_lens.ui.pack_review import PackReviewDialog


def img(text):
    im = Image.new("RGB", (160, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


def make_pack(folder, name, lines):
    store = OcrDataStore(folder / f"{name}-data")
    for ocr, fixed in lines:
        sid = store.add_capture(img(ocr), ocr, engine="rapid-v6", preset="none", seconds=1,
                                speaker=None)
        store.set_truth(sid, fixed, "edited")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}-v1.zip"
    apply_export(store, review_export(store), path, name)
    return path


@pytest.fixture
def packs(tmp_path):
    a = make_pack(tmp_path / "downloads", "KaiOCR", [("k1", "K1"), ("k2", "K2")])
    b = make_pack(tmp_path / "downloads", "RavenOCR", [("r1", "R1")])
    c = make_pack(tmp_path / "elsewhere", "MiaOCR", [("m1", "M1"), ("m2", "M2"),
                                                       ("m3", "M3")])
    bad = tmp_path / "elsewhere" / "broken.zip"
    bad.write_bytes(b"not a zip")
    return {"a": a, "b": b, "c": c, "bad": bad}


@pytest.fixture
def chooser(monkeypatch):
    """The file dialog Add opens: answers with the next list of paths; records folders."""
    state = {"answers": [], "folders": []}

    def fake(parent, title, folder, filters):
        state["folders"].append(folder)
        return [str(p) for p in (state["answers"].pop(0) if state["answers"] else [])]

    monkeypatch.setattr(file_dialogs, "open_files", fake)
    return state


@pytest.fixture
def dlg(packs, chooser):
    QApplication.instance() or QApplication([])
    d = MergeListDialog(None, folder=str(packs["a"].parent))
    d.show()
    yield d
    d.close()


def names(d):
    return [d.table.item(r, 0).text() for r in range(d.table.rowCount())]


def click(button):
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)


# ---------- the list window
def test_first_choice_is_listed_and_merge_needs_two(dlg, packs):
    dlg.add_paths([str(packs["a"])])
    assert names(dlg) == ["KaiOCR v1"] and dlg.table.item(0, 1).text() == "2"
    assert not dlg.merge_btn.isEnabled() and "1 more pack" in dlg.requirement.text()
    assert not dlg.remove_btn.isEnabled()  # nothing selected


def test_add_from_another_folder_appends(dlg, packs, chooser):
    dlg.add_paths([str(packs["a"]), str(packs["b"])])
    chooser["answers"] = [[packs["c"]]]
    click(dlg.add_btn)
    assert names(dlg) == ["KaiOCR v1", "RavenOCR v1", "MiaOCR v1"]
    assert chooser["folders"] == [str(packs["a"].parent)]  # opened where the last came from
    chooser["answers"] = [[]]
    click(dlg.add_btn)  # the next Add opens in the folder of the last pack added
    assert chooser["folders"][-1] == str(packs["c"].parent)
    assert dlg.merge_btn.isEnabled() and dlg.requirement.text() == ""


def test_add_cancelled_changes_nothing(dlg, packs, chooser):
    dlg.add_paths([str(packs["a"])])
    chooser["answers"] = [[]]
    click(dlg.add_btn)
    assert names(dlg) == ["KaiOCR v1"] and not dlg.note.isVisible()


def test_add_skips_duplicates_and_damaged_files(dlg, packs, tmp_path, chooser):
    dlg.add_paths([str(packs["a"])])
    copy = tmp_path / "copy" / "KaiOCR-v1 (1).zip"
    copy.parent.mkdir()
    shutil.copy(packs["a"], copy)
    chooser["answers"] = [[packs["a"], copy, packs["bad"], packs["b"]]]
    click(dlg.add_btn)
    assert names(dlg) == ["KaiOCR v1", "RavenOCR v1"]
    note = dlg.note.text()
    assert "Already added" in note and "KaiOCR-v1.zip" in note
    assert "KaiOCR-v1 (1).zip" in note  # the same pack in another folder
    assert "Not added: broken.zip" in note


def test_several_chosen_at_once_with_duplicates_inside(dlg, packs):
    dlg.add_paths([str(packs["a"]), str(packs["a"]), str(packs["b"])])
    assert names(dlg) == ["KaiOCR v1", "RavenOCR v1"]


def test_remove_one_several_all(dlg, packs):
    dlg.add_paths([str(packs[k]) for k in ("a", "b", "c")])
    dlg.table.selectRow(1)
    assert dlg.remove_btn.isEnabled()
    click(dlg.remove_btn)
    assert names(dlg) == ["KaiOCR v1", "MiaOCR v1"]
    assert dlg.merge_btn.isEnabled()
    dlg.table.selectAll()
    click(dlg.remove_btn)
    assert names(dlg) == [] and not dlg.merge_btn.isEnabled()
    assert "2 more packs" in dlg.requirement.text() and not dlg.remove_btn.isEnabled()


def test_removed_pack_can_be_added_again(dlg, packs):
    dlg.add_paths([str(packs["a"]), str(packs["b"])])
    dlg.table.selectRow(0)
    click(dlg.remove_btn)
    assert dlg.add_paths([str(packs["a"])]) == 1
    assert names(dlg) == ["RavenOCR v1", "KaiOCR v1"]


def test_delete_key_removes(dlg, packs):
    dlg.add_paths([str(packs["a"]), str(packs["b"])])
    dlg.table.setFocus()
    dlg.table.selectRow(0)
    QTest.keyClick(dlg.table, Qt.Key.Key_Delete)
    assert names(dlg) == ["RavenOCR v1"]


def test_merge_and_cancel_buttons(dlg, packs):
    dlg.add_paths([str(packs["a"]), str(packs["b"])])
    click(dlg.merge_btn)
    assert dlg.result() == QDialog.DialogCode.Accepted
    dlg.show()
    click(dlg.cancel_btn)
    assert dlg.result() == QDialog.DialogCode.Rejected


def test_merge_disabled_click_does_nothing(dlg, packs):
    dlg.add_paths([str(packs["a"])])
    click(dlg.merge_btn)
    assert dlg.isVisible()


# ---------- History's merge flow
@pytest.fixture
def history(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("JISHO_LENS_HOME", str(tmp_path / "home"))
    from jisho_lens.core.history import HistoryStore
    from jisho_lens.core.settings import Settings

    store = OcrDataStore(tmp_path / "home" / "ocr-data")
    hist = HistoryStore(tmp_path / "home" / "history.db")
    w = history_window.HistoryWindow(hist, store, Settings.load(), None)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    yield w
    w.close()
    hist.close()


def script(monkeypatch, cls, steps):
    """`cls.exec` runs the next step (gets the dialog; returns its result)."""
    calls = []

    def run(dialog):
        packs = getattr(dialog, "packs", None) or getattr(dialog, "_packs", [])
        calls.append([p.label for p in packs])
        return steps.pop(0)(dialog)

    monkeypatch.setattr(cls, "exec", run)
    return calls


def test_flow_first_dialog_cancelled(history, monkeypatch):
    monkeypatch.setattr(history_window, "open_files", lambda *a: [])
    calls = script(monkeypatch, MergeListDialog, [])
    history._merge()
    assert calls == []  # no list without packs


def test_flow_list_cancelled_writes_nothing(history, packs, monkeypatch, tmp_path):
    monkeypatch.setattr(history_window, "open_files", lambda *a: [str(packs["a"])])
    calls = script(monkeypatch, MergeListDialog,
                   [lambda d: (click(d.cancel_btn), d.result())[1]])
    history._merge()
    assert calls == [["KaiOCR v1"]]


def test_flow_review_cancelled_comes_back_to_the_list(history, packs, monkeypatch, chooser,
                                                      tmp_path):
    monkeypatch.setattr(history_window, "open_files",
                        lambda *a: [str(packs["a"]), str(packs["b"])])
    chooser["answers"] = [[packs["c"]]]

    def add_then_merge(d):
        click(d.add_btn)
        click(d.merge_btn)
        return d.result()

    def cancel(d):
        click(d.cancel_btn)
        return d.result()

    lists = script(monkeypatch, MergeListDialog, [add_then_merge, cancel])
    reviews = script(monkeypatch, PackReviewDialog,
                     [lambda d: QDialog.DialogCode.Rejected])
    history._merge()
    assert lists == [["KaiOCR v1", "RavenOCR v1"],
                     ["KaiOCR v1", "RavenOCR v1", "MiaOCR v1"]]  # still all three
    assert reviews == [["KaiOCR v1", "RavenOCR v1", "MiaOCR v1"]]
    assert list((tmp_path / "home").glob("**/*-v1.zip")) == []


def test_flow_name_or_save_cancelled_comes_back(history, packs, monkeypatch):
    monkeypatch.setattr(history_window, "open_files",
                        lambda *a: [str(packs["a"]), str(packs["b"])])
    merge = lambda d: (click(d.merge_btn), d.result())[1]  # noqa: E731
    cancel = lambda d: (click(d.cancel_btn), d.result())[1]  # noqa: E731
    lists = script(monkeypatch, MergeListDialog, [merge, merge, cancel])
    script(monkeypatch, PackReviewDialog, [lambda d: QDialog.DialogCode.Accepted] * 2)
    names_given = [("", False), ("Mix", True)]
    monkeypatch.setattr(QInputDialog, "getText",
                        staticmethod(lambda *a, **k: names_given.pop(0)))
    monkeypatch.setattr(history_window, "save_file", lambda *a, **k: "")
    history._merge()
    assert len(lists) == 3  # name cancelled -> list; save cancelled -> list; Cancel


def test_flow_merged(history, packs, monkeypatch, tmp_path):
    out = tmp_path / "out" / "Mix-v1.zip"
    out.parent.mkdir()
    monkeypatch.setattr(history_window, "open_files",
                        lambda *a: [str(packs["a"]), str(packs["c"])])
    lists = script(monkeypatch, MergeListDialog,
                   [lambda d: (click(d.merge_btn), d.result())[1]])
    script(monkeypatch, PackReviewDialog, [lambda d: QDialog.DialogCode.Accepted])
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mix", True)))
    monkeypatch.setattr(history_window, "save_file", lambda *a, **k: str(out))
    history._merge()
    assert len(lists) == 1  # done: the list closes
    merged = read_pack(out)
    assert len(merged.samples) == 5 and merged.info.label == "Mix v1"
