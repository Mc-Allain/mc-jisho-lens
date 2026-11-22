"""Remember my corrections: learning fixes from Edit and applying them to later captures."""

from jisho_lens.core.ocr_data.corrections import (
    LINE,
    Correction,
    CorrectionStore,
    apply_rules,
    learn_rules,
)
from jisho_lens.core.ocr_data.store import Sample

OCR = ["そうた、探しに行くまえにじっちゃ……村長の家に寄るそ。",
       "森の異変のことを報告して、ついてに準備も手伝ってもらうんた！"]
FIXED = ["そうだ、探しに行くまえにじっちゃ……村長の家に寄るぞ。",
         "森の異変のことを報告して、ついでに準備も手伝ってもらうんだ！"]


def test_learns_each_fix_with_context():
    assert learn_rules(OCR, FIXED) == [
        ("うた、", "うだ、"), ("るそ。", "るぞ。"), ("いてに", "いでに"), ("んた！", "んだ！")]


def test_applies_to_a_new_capture_but_not_elsewhere():
    rules = [Correction(w, r) for w, r in learn_rules(OCR, FIXED)]
    result = apply_rules(OCR, rules)
    assert result.lines == FIXED and len(result.used) == 4
    # た without the learned surroundings is left alone
    other = apply_rules(["また会おうた。", "食べた、"], rules)
    assert other.lines == ["また会おうた。", "食べた、"] and other.used == []


def test_line_start_is_context():
    rules = learn_rules(["たべた"], ["だべた"])
    assert rules == [(LINE + "たべた", LINE + "だべた")]
    applied = apply_rules(["たべた", "またたべた"], [Correction(*rules[0])])
    assert applied.lines == ["だべた", "またたべた"]


def test_skips_tiny_lines_big_rewrites_and_line_joins():
    assert learn_rules(["あ"], ["い"]) == []
    assert learn_rules(["これはぜんぜんちがうぶんしょう"], ["まったくべつのテキストですよね"]) == []
    assert learn_rules(["あいう", "えお"], ["あいうえお"]) == []


def test_store_learns_counts_forgets_and_persists(tmp_path):
    store = CorrectionStore(tmp_path)
    assert store.learn(OCR, FIXED) == 4
    store.learn(["寄るそ。"], ["寄るぞ。"])
    assert next(r for r in store.all() if r.wrong == "るそ。").count == 2
    result = store.apply(OCR)
    assert result.lines == FIXED
    # reloaded from disk
    again = CorrectionStore(tmp_path)
    assert len(again.all()) == 4 and all(r.used == 1 for r in again.all())
    # the user undid one (put the OCR text back) while fixing something else
    undone = [FIXED[0].replace("寄るぞ", "寄るそ"), FIXED[1]]
    again.learn(FIXED, undone, applied=result.used)
    assert "るそ。" not in {r.wrong for r in again.all()}
    # ✓ after Undo: the OCR text was right, so the applied corrections go
    store3 = CorrectionStore(tmp_path)
    used = store3.apply(OCR).used
    assert store3.forget(used, OCR) == len(used)
    assert store3.all() == []


def test_newest_answer_wins_and_delete(tmp_path):
    store = CorrectionStore(tmp_path)
    store.learn(["そうた、"], ["そうだ、"])
    store.learn(["そうた、"], ["そうか、"])
    rule = store.all()[0]
    assert (rule.wrong, rule.right) == (LINE + "そうた", LINE + "そうか") or \
        rule.right.endswith("か、")
    store.delete(rule.wrong)
    assert store.all() == []
    store.learn(OCR, FIXED)
    store.delete_all()
    assert store.all() == [] and not store.path.exists()


def test_learn_from_saved_samples(tmp_path):
    raw = "テララ\n" + "\n".join(OCR)  # raw OCR keeps the speaker line
    samples = [Sample(id="a" * 64, ocr_text=raw, truth="\n".join(FIXED), truth_source="edited"),
               Sample(id="b" * 64, ocr_text="ほげ", truth="ほげ", truth_source="confirmed")]
    store = CorrectionStore(tmp_path)
    assert store.learn_from_samples(samples) == 4
    assert store.path.exists()
