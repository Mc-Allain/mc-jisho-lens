"""Merging versions of one pack (newest first, records a newer version removed) and adding /
removing packs inside the merge review (rows update at once, choices kept, the Merge packs
list follows)."""

import pytest
from PIL import Image, ImageDraw
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QInputDialog, QMessageBox, QPushButton

from jisho_lens.core.ocr_data import OcrDataStore, apply_export, read_pack, review_export
from jisho_lens.core.ocr_data.packs import (
    ALL_ANSWERS,
    DIFFERS,
    NEW,
    REMOVED,
    apply_merge,
    merge_contributions,
    merge_sources,
    order_packs,
    review_merge,
)
from jisho_lens.ui import history_window
from jisho_lens.ui.merge_list import MergeListDialog
from jisho_lens.ui.pack_review import COL_CHOICE, COL_INCLUDE, COL_STATUS, PackReviewDialog


def img(text):
    im = Image.new("RGB", (160, 40), (20, 20, 20))
    ImageDraw.Draw(im).text((5, 10), text, fill=(255, 255, 255))
    return im


class Person:
    """Someone's OCR data; each release() exports the next version of their pack."""

    def __init__(self, tmp, name):
        self.tmp, self.name = tmp, name
        self.store = OcrDataStore(tmp / f"{name}-{id(self)}")
        self.ids = {}

    def fix(self, picture, answer):
        sid = self.store.add_capture(img(picture), picture, engine="rapid-v6", preset="none",
                                     seconds=1, speaker=None)
        self.store.set_truth(sid, answer, "edited")
        self.ids[picture] = sid
        return self

    def drop(self, picture):
        self.store.delete(self.ids.pop(picture))
        return self

    def release(self):
        n = len(list(self.tmp.glob(f"{self.name}-*.zip"))) + 1
        path = self.tmp / f"{self.name}-{n}-{id(self)}.zip"
        apply_export(self.store, review_export(self.store), path, self.name)
        return read_pack(path)


@pytest.fixture
def tmp(tmp_path):
    QApplication.instance() or QApplication([])
    return tmp_path


def by_pic(rows):
    return {r.ocr_text: r for r in rows}


def counts(rows, packs):
    c = merge_contributions(rows)
    return [c.get(id(p), 0) for p in packs]


# ---------- order: newest first among versions of the same pack
def test_newest_version_first_others_keep_their_order(tmp):
    kai, mia = Person(tmp, "KaiOCR"), Person(tmp, "MiaOCR")
    k1 = kai.fix("a", "A").release()
    k2 = kai.fix("b", "B").release()
    k3 = kai.fix("c", "C").release()
    m1 = mia.fix("m", "M").release()
    assert [p.label for p in (k1, k2, k3)] == ["KaiOCR v1", "KaiOCR v2", "KaiOCR v3"]
    assert order_packs([k1, m1, k3, k2]) == [k3, k2, k1, m1]
    assert order_packs([m1, k2, k1]) == [m1, k2, k1]


def test_same_name_by_someone_else_is_another_pack(tmp):
    kai, other = Person(tmp, "KaiOCR"), Person(tmp, "KaiOCR")  # two people, one name
    a1 = kai.fix("a", "A").release()
    b1 = other.fix("b", "B").release()
    b2 = other.fix("c", "C").release()
    assert order_packs([a1, b1, b2]) == [a1, b2, b1]  # only b's versions are sorted
    rows = review_merge([a1, b1])
    assert all(r.status == NEW for r in rows)  # a1 didn't "remove" anything of b1


def test_order_decides_credit_and_the_answer_used(tmp):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A-old").fix("b", "B").release()
    kai.store.set_truth(kai.ids["a"], "A-new", "edited")
    k2 = kai.release()
    rows = review_merge([k1, k2])  # chosen older first: still newest first
    a = by_pic(rows)["a"]
    assert a.status == DIFFERS and a.answers[0].truth == "A-new"
    assert a.choice == ALL_ANSWERS  # Keep all: the newer answer is the answer
    assert counts(rows, [k2, k1]) == [2, 1]  # k1 only brings its old answer of "a"
    a.choice = 0  # use the newer answer: the older version brings nothing
    assert counts(rows, [k2, k1]) == [2, 0]
    assert merge_sources(rows) == "KaiOCR v2"


# ---------- Option B: records a newer version removed
def test_removed_in_newer_version_is_listed_unticked(tmp):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A").fix("b", "B").release()
    k2 = kai.drop("b").fix("c", "C").release()
    rows = review_merge([k1, k2])
    b = by_pic(rows)["b"]
    assert b.status == REMOVED and not b.include and b.removed_in == "KaiOCR v2"
    assert counts(rows, [k2, k1]) == [2, 0]
    assert merge_sources(rows) == "KaiOCR v2"
    b.include = True  # bring it back on purpose
    assert counts(rows, [k2, k1]) == [2, 1]
    assert merge_sources(rows) == "KaiOCR v2 + KaiOCR v1"
    out = tmp / "Mix.zip"
    apply_merge(rows, out, "c0ffee00", "Mix", OcrDataStore(tmp / "me"))
    assert sorted(s.truth for s in read_pack(out).samples.values()) == ["A", "B", "C"]


def test_removed_but_another_pack_brings_it(tmp):
    kai, mia = Person(tmp, "KaiOCR"), Person(tmp, "MiaOCR")
    k1 = kai.fix("a", "A").fix("b", "B-kai").release()
    k2 = kai.drop("b").release()
    m1 = mia.fix("b", "B-mia").release()
    rows = review_merge([k1, k2, m1])
    b = by_pic(rows)["b"]
    assert b.status == NEW and b.include and [x.truth for x in b.answers] == ["B-mia"]
    assert counts(rows, [k2, k1, m1]) == [1, 0, 1]  # Kai's dropped answer isn't offered


def test_dropped_then_added_back_in_a_later_version(tmp):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A").fix("b", "B").release()
    k2 = kai.drop("b").release()
    k3 = kai.fix("b", "B").release()
    rows = review_merge([k1, k2, k3])
    assert by_pic(rows)["b"].status == NEW  # the newest has it again
    assert REMOVED not in {r.status for r in rows}


def test_removed_with_three_versions(tmp):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A").fix("b", "B").release()
    k2 = kai.fix("c", "C").release()
    k3 = kai.drop("b").release()
    rows = review_merge([k2, k1, k3])
    b = [r for r in rows if r.ocr_text == "b"]
    assert len(b) == 1 and b[0].status == REMOVED and b[0].removed_in == "KaiOCR v3"
    assert b[0].pack is k2  # listed once, from the newest version that had it


def test_only_an_older_version_removes_nothing(tmp):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A").fix("b", "B").release()
    kai.drop("b").release()  # v2 exists but isn't in this merge
    mia = Person(tmp, "MiaOCR").fix("m", "M").release()
    assert {r.status for r in review_merge([k1, mia])} == {NEW}


# ---------- adding / removing packs inside the review
@pytest.fixture
def three(tmp):
    kai, mia, raven = Person(tmp, "KaiOCR"), Person(tmp, "MiaOCR"), Person(tmp, "RavenOCR")
    k = kai.fix("x", "X-kai").fix("k", "K").release()
    m = mia.fix("x", "X-mia").fix("m", "M").release()
    r = raven.fix("r", "R").fix("r2", "R2").release()
    return k, m, r


def review(packs, add=None):
    rows = review_merge(packs)
    d = PackReviewDialog(rows, "merge", packs=packs, show_images=False, rebuild=review_merge,
                         add_packs=add, preview=lambda: ("", ""))
    d.show()
    return d


def answer_remove(monkeypatch, yes=True):
    button = QMessageBox.StandardButton.Yes if yes else QMessageBox.StandardButton.No
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: button))


def remove_button(d, label):
    return next(b for b in d.findChildren(QPushButton)
                if b.objectName() == "remove_pack" and b.property("pack_label") == label
)


def row_of(d, pic):
    return next(i for i, r in enumerate(d.rows) if r.ocr_text == pic)


def test_remove_a_pack_updates_rows_and_keeps_choices(tmp, three, monkeypatch):
    k, m, r = three
    d = review([k, m, r])
    answer_remove(monkeypatch)
    d.table.item(row_of(d, "r2"), COL_INCLUDE).setCheckState(Qt.CheckState.Unchecked)
    d.table.item(row_of(d, "k"), COL_INCLUDE).setCheckState(Qt.CheckState.Unchecked)
    remove_button(d, "MiaOCR v1").click()
    QApplication.processEvents()
    assert [p.label for p in d.packs] == ["KaiOCR v1", "RavenOCR v1"]
    assert sorted(x.ocr_text for x in d.rows) == ["k", "r", "r2", "x"]
    x = d.rows[row_of(d, "x")]
    assert x.status == NEW and [a.truth for a in x.answers] == ["X-kai"]  # no longer differs
    assert not d.rows[row_of(d, "r2")].include and not d.rows[row_of(d, "k")].include
    assert d.rows[row_of(d, "r")].include
    assert d.table.cellWidget(row_of(d, "x"), COL_CHOICE) is None
    assert d.table.rowCount() == 4 and d.ok_btn.isEnabled()
    d.close()


def test_chosen_answer_survives_removing_another_pack(tmp, three, monkeypatch):
    k, m, r = three
    d = review([k, m, r])
    answer_remove(monkeypatch)
    box = d.table.cellWidget(row_of(d, "x"), COL_CHOICE)
    box.setCurrentIndex(box.findData(1))  # use Mia's answer
    remove_button(d, "RavenOCR v1").click()
    x = d.rows[row_of(d, "x")]
    assert x.status == DIFFERS and x.answers[x.choice].truth == "X-mia"
    assert d.table.cellWidget(row_of(d, "x"), COL_CHOICE).currentData() == x.choice
    d.close()


def test_remove_answered_no_changes_nothing(tmp, three, monkeypatch):
    k, m, r = three
    d = review([k, m, r])
    answer_remove(monkeypatch, yes=False)
    remove_button(d, "MiaOCR v1").click()
    assert len(d.packs) == 3 and len(d.rows) == 5
    d.close()


def test_remove_down_to_one_and_zero(tmp, three, monkeypatch):
    k, m, r = three
    d = review([k, m])
    answer_remove(monkeypatch)
    remove_button(d, "MiaOCR v1").click()
    assert not d.ok_btn.isEnabled() and "two or more packs" in d.blocked.text()
    remove_button(d, "KaiOCR v1").click()
    assert d.packs == [] and d.rows == [] and d.table.rowCount() == 0
    assert not d.ok_btn.isEnabled()
    d.close()


def test_add_packs_in_the_review(tmp, three, monkeypatch):
    k, m, r = three
    kai_next = Person(tmp, "KaiOCR")  # unrelated person: just another pack
    extra = kai_next.fix("e", "E").release()
    offered = [[r], [], [extra]]
    d = review([k, m], add=lambda parent: (offered.pop(0), "a note" if not offered else ""))
    d.table.item(row_of(d, "k"), COL_INCLUDE).setCheckState(Qt.CheckState.Unchecked)
    d.add_packs_btn.click()
    assert [p.label for p in d.packs] == ["KaiOCR v1", "MiaOCR v1", "RavenOCR v1"]
    assert sorted(x.ocr_text for x in d.rows) == ["k", "m", "r", "r2", "x"]
    assert not d.rows[row_of(d, "k")].include  # kept
    d.add_packs_btn.click()  # nothing chosen: unchanged
    assert len(d.packs) == 3
    d.close()


def test_adding_a_newer_version_in_the_review_marks_removed(tmp, monkeypatch):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A").fix("b", "B").release()
    k2 = kai.drop("b").release()
    mia = Person(tmp, "MiaOCR").fix("m", "M").release()
    d = review([k1, mia], add=lambda parent: ([k2], ""))
    assert d.rows[row_of(d, "b")].include
    d.add_packs_btn.click()
    assert [p.label for p in d.packs] == ["KaiOCR v2", "KaiOCR v1", "MiaOCR v1"]
    b = row_of(d, "b")
    assert d.rows[b].status == REMOVED and not d.rows[b].include
    assert "Removed in KaiOCR v2" in d.table.item(b, COL_STATUS).data(Qt.ItemDataRole.UserRole + 10)
    assert d.status_filter.findText("Removed in newer version (1)") >= 0
    labels = dict((p.label, lb) for p, lb in d._pack_labels)
    assert "0 records in this merge" in labels["KaiOCR v1"].text()
    d.close()


# ---------- History's flow: the list follows the review
@pytest.fixture
def history(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    monkeypatch.setenv("JISHO_LENS_HOME", str(tmp_path / "home"))
    from jisho_lens.core.history import HistoryStore
    from jisho_lens.core.settings import Settings

    hist = HistoryStore(tmp_path / "home" / "history.db")
    w = history_window.HistoryWindow(hist, OcrDataStore(tmp_path / "home" / "ocr-data"),
                                     Settings.load(), None)
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))
    yield w
    w.close()
    hist.close()


def test_list_follows_packs_removed_and_added_in_the_review(history, three, monkeypatch,
                                                           tmp):
    k, m, r = three
    monkeypatch.setattr(history_window, "open_files", lambda *a: [str(k.path), str(m.path)])
    answer_remove(monkeypatch)
    lists = []

    def list_step(d):
        lists.append([p.label for p in d.packs])
        if len(lists) == 1:
            d.merge_btn.click()
        else:
            d.cancel_btn.click()
        return d.result()

    def review_step(d):
        monkeypatch.setattr("jisho_lens.ui.file_dialogs.open_files",
                            lambda *a: [str(r.path), str(k.path)])
        d.add_packs_btn.click()  # Raven added; Kai again is left out with a note
        assert "Already added" in d.pack_note.text()
        remove_button(d, "MiaOCR v1").click()
        return QDialog.DialogCode.Rejected

    monkeypatch.setattr(MergeListDialog, "exec", list_step)
    monkeypatch.setattr(PackReviewDialog, "exec", review_step)
    history._merge()
    assert lists == [["KaiOCR v1", "MiaOCR v1"], ["KaiOCR v1", "RavenOCR v1"]]


def test_merge_saved_from_the_review_s_packs(history, three, monkeypatch, tmp):
    k, m, r = three
    out = tmp / "Mix-v1.zip"
    monkeypatch.setattr(history_window, "open_files",
                        lambda *a: [str(k.path), str(m.path), str(r.path)])
    answer_remove(monkeypatch)
    monkeypatch.setattr(MergeListDialog, "exec",
                        lambda d: (d.merge_btn.click(), d.result())[1])

    def review_step(d):
        remove_button(d, "MiaOCR v1").click()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(PackReviewDialog, "exec", review_step)
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Mix", True)))
    monkeypatch.setattr(history_window, "save_file", lambda *a, **k: str(out))
    history._merge()
    merged = read_pack(out)
    assert sorted(s.truth for s in merged.samples.values()) == ["K", "R", "R2", "X-kai"]
    names = {e.name for e in merged.info.log}
    assert names == {"Mix", "KaiOCR", "RavenOCR"}  # Mia was removed: not in the log


def test_merge_list_shows_newest_version_first(tmp):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A").release()
    k2 = kai.fix("b", "B").release()
    mia = Person(tmp, "MiaOCR").fix("m", "M").release()
    d = MergeListDialog(None)
    d.add_paths([str(k1.path), str(mia.path)])
    d.add_paths([str(k2.path)])  # added later, still listed before v1
    assert [d.table.item(i, 0).text() for i in range(3)] == ["KaiOCR v2", "KaiOCR v1",
                                                            "MiaOCR v1"]
    d.close()


def test_review_shows_newest_version_first(tmp):
    kai = Person(tmp, "KaiOCR")
    k1 = kai.fix("a", "A").release()
    k2 = kai.fix("b", "B").release()
    mia = Person(tmp, "MiaOCR").fix("m", "M").release()
    d = review([k1, mia, k2])
    assert [p.label for p in d.packs] == ["KaiOCR v2", "KaiOCR v1", "MiaOCR v1"]
    assert [p.label for p, _ in d._pack_labels] == ["KaiOCR v2", "KaiOCR v1", "MiaOCR v1"]
    d.close()


# ---------- the pack list scrolls instead of growing the window
def many(tmp, n):
    return [Person(tmp, f"Pack{i}").fix(f"p{i}", f"P{i}").release() for i in range(n)]


def scroll_state(d):
    QApplication.processEvents()
    bar = d.packs_scroll.verticalScrollBar()
    return d.packs_scroll.height(), bar.maximum() > 0


def test_pack_list_scrolls_after_four(tmp, monkeypatch):
    h = {}
    for n in (1, 4, 5, 9):
        d = review(many(tmp / str(n), n))
        h[n], scrolls = scroll_state(d)
        assert scrolls == (n > 4), n
        assert len(d._pack_labels) == n  # every pack is still there to scroll to
        d.close()
    assert h[1] < h[4] == h[5] == h[9]  # never taller than four rows


def test_pack_list_height_follows_add_and_remove(tmp, monkeypatch):
    packs = many(tmp, 6)
    d = review(packs[:2], add=lambda parent: (packs[2:], ""))
    small, scrolls = scroll_state(d)
    assert not scrolls
    window = d.sizeHint().height()
    d.add_packs_btn.click()
    full, scrolls = scroll_state(d)
    assert scrolls and full > small
    assert d.sizeHint().height() - window == full - small  # grows only up to four rows
    answer_remove(monkeypatch)
    for label in ("Pack5 v1", "Pack4 v1", "Pack3 v1", "Pack2 v1"):
        remove_button(d, label).click()
    assert scroll_state(d) == (small, False)
    d.close()
