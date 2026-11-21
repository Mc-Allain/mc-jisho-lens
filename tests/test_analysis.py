import pytest

from jisho_lens.core.analysis import Analyzer
from jisho_lens.core.analysis.furigana import align
from jisho_lens.core.analysis.kana import has_kanji, is_kanji, to_hiragana


@pytest.fixture(scope="module")
def an():
    return Analyzer()


def by_surface(tokens):
    return {t.surface: t for t in tokens}


# ---------- kana ----------
def test_kana_helpers():
    assert to_hiragana("キョウ") == "きょう"
    assert to_hiragana("スター") == "すたー"
    assert is_kanji("々") and is_kanji("ヶ") and not is_kanji("ケ")
    assert has_kanji("食べる") and not has_kanji("たべる")


# ---------- furigana ----------
@pytest.mark.parametrize(
    "surface, reading, expected",
    [
        ("食べ", "たべ", [("食", "た"), ("べ", None)]),
        ("今日", "きょう", [("今日", "きょう")]),
        ("取り扱い", "とりあつかい", [("取", "と"), ("り", None), ("扱", "あつか"), ("い", None)]),
        ("聞い", "キイ", [("聞", "き"), ("い", None)]),
        ("ヶ月", "かげつ", [("ヶ月", "かげつ")]),
        ("人々", "ひとびと", [("人々", "ひとびと")]),
        ("たべる", "たべる", [("たべる", None)]),
        ("お茶", "おちゃ", [("お", None), ("茶", "ちゃ")]),
        ("食べ", "のむ", [("食べ", "のむ")]),  # mismatch -> whole word
        ("鍵", None, [("鍵", None)]),
    ],
)
def test_align(surface, reading, expected):
    assert align(surface, reading) == expected


# ---------- analyzer ----------
def test_context_reading_and_particles(an):
    toks = by_surface(an.analyze_line("今日は村長の家へ行く。"))
    assert toks["今日"].reading == "きょう"
    assert toks["今日"].furigana == [("今日", "きょう")]
    assert toks["は"].romaji == "wa" and "wa" in toks["は"].note
    assert toks["へ"].romaji == "e"
    assert toks["村長"].romaji == "sonchou"
    assert not toks["。"].clickable


def test_wo_is_o(an):
    toks = by_surface(an.analyze_line("宝箱を開けますか？"))
    assert toks["を"].romaji == "o"
    assert toks["開け"].base == "開ける"
    assert toks["開け"].furigana == [("開", "あ"), ("け", None)]


def test_conjugation_and_small_tsu(an):
    toks = an.analyze_line("食べられなかった")
    assert [t.surface for t in toks] == ["食べ", "られ", "なかっ", "た"]
    assert "".join(t.romaji for t in toks) == "taberarenakatta"
    assert toks[0].base == "食べる"
    assert toks[0].conjugation is not None


def test_loanwords_follow_kana(an):
    toks = an.analyze_line("キボとスターリンクする")
    romaji = {t.surface: t.romaji for t in toks}
    assert romaji["スター"] == "sutaa"
    assert romaji["リンク"] == "rinku"
    toks = an.analyze_line("ウィスパーフラワー")
    assert "".join(t.romaji for t in toks) == "wisupaafurawaa"


def test_unknown_names_and_numbers(an):
    toks = by_surface(an.analyze_line("テララ！貝殻10個で交換 7/20"))
    assert toks["テララ"].reading == "てらら" and toks["テララ"].romaji == "terara"
    assert toks["テララ"].clickable
    assert not toks["10"].clickable and not toks["/"].clickable
    assert toks["個"].reading == "こ"


def test_split_katakana_names_are_rejoined(an):
    for name in ["テララ", "リリカ"]:
        toks = an.analyze_line(f"{name}は困っているようだ。")
        assert toks[0].surface == name, [t.surface for t in toks]
        assert toks[0].reading == to_hiragana(name)
        assert not toks[0].known
    # real katakana compounds stay as separate words
    surfaces = [t.surface for t in an.analyze_line("ウィスパーフラワー")]
    assert surfaces == ["ウィスパー", "フラワー"]


def test_symbols_pass_through(an):
    line = "【鍵×1】を消費して宝箱を開けますか？"
    toks = an.analyze_line(line)
    assert "".join(t.surface for t in toks) == line
    clickable = [t.surface for t in toks if t.clickable]
    assert "【" not in clickable and "×" not in clickable and "鍵" in clickable


@pytest.mark.parametrize(
    "line",
    [
        "そうだ、探しに行くまえにじっちゃ……村長の家に寄るぞ。",
        "森の異変のことを報告して、ついでに準備も手伝ってもらうんだ！",
        "コホン。いいか、あたしのことは「ルミィさま」と呼ぶのだ。",
        "普通の火元素と異なり、炎核に満ちたエネルギーは武器と共鳴し、強化することができる。",
        "対応する生産設備に派遣すると、レシピの生産効率が418%上昇する",
        "ガヤックはおとなしくて力持ち。大陸で最も頼りになる貨物運送手段の一種——ただし、おなかがいっぱいのときに限ります。",
    ],
)
def test_real_game_lines_round_trip(an, line):
    toks = an.analyze_line(line)
    # nothing lost or duplicated
    assert "".join(t.surface for t in toks) == line
    for t in toks:
        if any(is_kanji(c) for c in t.surface) and t.reading:
            # furigana segments rebuild the word, and kanji segments carry a reading
            assert "".join(s for s, _ in t.furigana) == t.surface
            assert all(r for s, r in t.furigana if has_kanji(s))
        if t.clickable:
            assert t.romaji


def test_specific_readings(an):
    toks = by_surface(an.analyze_line("村長の家に寄るぞ。最も頼りになる"))
    assert toks["寄る"].reading == "よる"
    assert toks["最も"].reading == "もっとも"
    assert toks["頼り"].furigana == [("頼", "たよ"), ("り", None)]
