import pytest

from jisho_lens.core.analysis import Analyzer
from jisho_lens.dictionary import Dictionary, DictionaryMissing

try:
    DICT = Dictionary()
except DictionaryMissing:  # pragma: no cover
    DICT = None

pytestmark = pytest.mark.skipif(
    DICT is None, reason="no dictionary component installed (tools/components.py install ...)")


@pytest.fixture(scope="module")
def checked():
    return Analyzer(word_checker=DICT)


def surfaces(tokens):
    return [t.surface for t in tokens]


# ---------- lookups ----------
def test_lookup_uses_reading_and_pos():
    assert DICT.lookup(["家"], "いえ", "名詞")[0].readings[0][0] == "いえ"
    particle = DICT.lookup(["は"], "は", "助詞")
    assert particle and "topic" in particle[0].senses[0].glosses[0]
    suru = DICT.lookup(["為る", "する"], "する", "動詞")
    assert suru[0].readings[0][0] == "する"


def test_word_status():
    assert DICT.word_status("元素") == (True, True)
    assert DICT.word_status("火元") == (True, False)
    assert DICT.word_status("炎核") == (False, False)


def test_longer_words():
    longer = DICT.longer_words("攻撃力が上がる", 0, 2)
    assert longer and longer[0].headword == "攻撃力"


def test_kanji():
    k = DICT.kanji("炎")
    assert k.onyomi == ["エン"] and "flame" in k.meanings
    assert DICT.example_words("炎")


# ---------- boundary check ----------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("普通の火元素と異なり", ["普通", "の", "火", "元素", "と", "異なり"]),
        ("大陸中を旅する", ["大陸", "中", "を", "旅", "する"]),
    ],
)
def test_boundary_fixes(checked, text, expected):
    assert surfaces(checked.analyze_line(text)) == expected


@pytest.mark.parametrize(
    "text, word",
    [("攻撃力が上がる", "攻撃"), ("日本人です", "日本"), ("経験値を獲得", "経験"),
     ("強化素材を集める", "素材"), ("生産効率が上昇", "効率")],
)
def test_boundary_leaves_common_words_alone(checked, text, word):
    toks = checked.analyze_line(text)
    assert word in surfaces(toks)
    assert not any(t.boundary_fixed for t in toks)


@pytest.mark.parametrize(
    "text, word",
    [("オイラ、ほんとはわざとやってたんじゃないんだ。", "ほんと"),  # real word, not ほん + と
     ("おばあちゃんとじっちゃ", "ちゃん")],  # no stray kana (おば + あ)
)
def test_boundary_keeps_real_words(checked, text, word):
    toks = checked.analyze_line(text)
    assert word in surfaces(toks)
    assert "あ" not in surfaces(toks)


# ---------- Wiktionary words (words JMdict doesn't have) ----------
def test_wiktionary_lookup():
    entries = DICT.lookup(["じっちゃ"], "じっちゃ", "名詞")
    assert entries and entries[0].source == "wiktionary"
    assert "grandpa" in entries[0].senses[0].glosses[0]
    assert DICT.is_extra("じっちゃ") and not DICT.is_extra("元素")
    assert DICT.word_status("じっちゃ") == (True, False)


@pytest.mark.parametrize(
    "text", ["探しに行くまえにじっちゃ……村長の家に寄るぞ。", "じっちゃは元気？"])
def test_user_dictionary_splits_jitcha(text):
    from jisho_lens.core.analysis.analyzer import user_dictionary_path

    userdic = user_dictionary_path("lite")
    if userdic is None:
        pytest.skip("Wiktionary component not installed")
    an = Analyzer(word_checker=DICT, mode="lite", userdic=userdic)
    toks = an.analyze_line(text)
    assert "じっちゃ" in surfaces(toks)
    jit = next(t for t in toks if t.surface == "じっちゃ")
    assert jit.reading == "じっちゃ" and jit.romaji == "jitcha"


# ---------- grammar ----------
def test_conjugation_breakdown(checked):
    toks = checked.analyze_line("食べられなかった")
    g = [(p.surface, p.label) for p in toks[0].grammar]
    assert toks[0].phrase == "食べられなかった"
    assert g[0][0] == "食べ" and "ichidan" in g[0][1]
    assert [label for _, label in g[1:]] == ["passive / potential", "negative", "past"]


def test_te_helper(checked):
    toks = checked.analyze_line("手伝ってもらうんだ")
    head = toks[0]
    assert head.phrase == "手伝ってもらう"
    assert any("てもらう" in p.label for p in head.grammar)


def test_particle_notes(checked):
    toks = {t.surface: t for t in checked.analyze_line("村長の家へ行く")}
    assert "“e”" in toks["へ"].note
    assert "Possessive" in toks["の"].note
