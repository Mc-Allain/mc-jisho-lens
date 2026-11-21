from jisho_lens.core.ocr.metrics import char_accuracy, levenshtein, normalize


def test_normalize_drops_spaces_and_folds_width():
    assert normalize("ＡＢＣ　あ い\nう") == "ABCあいう"


def test_levenshtein():
    assert levenshtein("村長の家", "村長の家") == 0
    assert levenshtein("村長の家", "村長家") == 1
    assert levenshtein("", "abc") == 3


def test_char_accuracy():
    assert char_accuracy("村長の家に寄るぞ。", "村長の家に寄るぞ。") == 1.0
    assert char_accuracy("村長の家に寄るそ。", "村長の家に寄るぞ。") == 1 - 1 / 9
    assert char_accuracy("", "") == 1.0
    assert char_accuracy("x", "") == 0.0
    assert char_accuracy("completely wrong and much longer", "あ") == 0.0
