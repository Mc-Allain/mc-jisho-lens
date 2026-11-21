"""Split Japanese text into words with readings, furigana and romaji (SPEC §3.1 Text analysis).

Uses fugashi (MeCab) with UniDic-lite for word splitting and context-correct readings, and
cutlet for Hepburn romaji. Romaji follows the kana (スター -> "sutaa", not "star"), because
the point is learning to read.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

from jisho_lens.core.analysis.furigana import Segment, align
from jisho_lens.core.analysis.kana import has_japanese, has_kanji, is_all_kana, to_hiragana

POS_EN = {
    "名詞": "noun",
    "代名詞": "pronoun",
    "動詞": "verb",
    "形容詞": "i-adjective",
    "形状詞": "na-adjective",
    "副詞": "adverb",
    "連体詞": "pre-noun adjectival",
    "接続詞": "conjunction",
    "感動詞": "interjection",
    "助詞": "particle",
    "助動詞": "auxiliary verb",
    "接頭辞": "prefix",
    "接尾辞": "suffix",
    "補助記号": "symbol",
    "記号": "symbol",
    "空白": "space",
}
POS2_EN = {"固有名詞": "proper noun", "数詞": "number"}
_NOT_WORDS = {"補助記号", "記号", "空白"}
_MAPPING_FIXES = {"うぃ": "wi", "うぇ": "we", "うぉ": "wo", "くぁ": "kwa", "いぇ": "ye"}
# Particles whose pronunciation differs from their kana
_PARTICLE_PRON = {"は": "wa", "へ": "e", "を": "o"}


@dataclass
class Token:
    surface: str
    reading: str | None  # hiragana reading in this sentence
    romaji: str
    pos: str  # Japanese POS (UniDic pos1)
    pos_en: str
    base: str | None  # dictionary form, as written (e.g. 食べる)
    base_reading: str | None
    conjugation: str | None  # e.g. "下一段-バ行 / 未然形-一般"
    note: str | None  # e.g. 'particle は is pronounced "wa"'
    furigana: list[Segment] = field(default_factory=list)
    clickable: bool = False
    known: bool = True  # False when UniDic didn't know the word
    space_after: bool = False

    def to_dict(self) -> dict:
        return {
            "s": self.surface,
            "r": self.reading,
            "ro": self.romaji,
            "pos": self.pos,
            "posEn": self.pos_en,
            "base": self.base,
            "baseR": self.base_reading,
            "conj": self.conjugation,
            "note": self.note,
            "known": self.known,
        }


_GRAMMAR_POS = {"助詞", "助動詞", "接尾辞", "接頭辞"}


def _is_katakana_word(text: str) -> bool:
    return bool(text) and all(0x30A1 <= ord(c) <= 0x30FA or c == "ー" for c in text)


class DictionaryMissing(RuntimeError):
    pass


def check_dictionary() -> str:
    """Make sure full UniDic is installed and downloaded; returns its folder."""
    import os

    try:
        import unidic
    except ImportError as exc:
        raise DictionaryMissing("The UniDic package is not installed.") from exc
    if not os.path.exists(os.path.join(unidic.DICDIR, "sys.dic")):
        raise DictionaryMissing(
            "The UniDic dictionary hasn't been downloaded yet. Run: python -m unidic download"
        )
    return unidic.DICDIR


def _clean(value) -> str | None:
    if value is None or value in ("", "*"):
        return None
    return str(value)


class Analyzer:
    """Thread-safe wrapper around one fugashi tagger + cutlet."""

    def __init__(self) -> None:
        import cutlet

        check_dictionary()
        # fugashi finds the `unidic` package (full UniDic 3.1) on its own.
        self._cutlet = cutlet.Cutlet(use_foreign_spelling=False)
        self._cutlet.use_wo = False  # を -> "o" (Hepburn)
        # cutlet drops the w/y in these loanword combinations (ウィスパー -> "isupaa")
        for kana, romaji in _MAPPING_FIXES.items():
            self._cutlet.update_mapping(kana, romaji)
        self._tagger = self._cutlet.tagger
        self._lock = threading.Lock()

    def analyze_line(self, text: str) -> list[Token]:
        with self._lock:
            words = self._tagger(text)
            romaji = self._cutlet.romaji_tokens(words, capitalize=False)
        tokens = []
        gaps = []  # real whitespace in the text before the next word
        for idx, (word, rom) in enumerate(zip(words, romaji, strict=True)):
            tokens.append(
                self._token(word, rom.surface.lower(), rom.space or bool(word.white_space))
            )
            nxt = words[idx + 1] if idx + 1 < len(words) else None
            gaps.append(bool(nxt is not None and nxt.white_space))
        return self._merge_split_names(tokens, gaps)

    def _merge_split_names(self, tokens: list[Token], gaps: list[bool]) -> list[Token]:
        """UniDic splits unknown katakana names into pieces (テララ -> テ + ララ,
        リリカ -> リリ + カ). Join a run of adjacent katakana tokens back into one word when
        the run contains a one-character piece or a grammar word, which real katakana
        compounds (スター + リンク) never do."""
        out: list[Token] = []
        i = 0
        while i < len(tokens):
            j = i
            while (j < len(tokens) and _is_katakana_word(tokens[j].surface)
                   and (j == i or not gaps[j - 1])):
                j += 1
            run = tokens[i:j]
            if len(run) >= 2 and any(
                len(t.surface) == 1 or t.pos in _GRAMMAR_POS for t in run
            ):
                surface = "".join(t.surface for t in run)
                reading = to_hiragana(surface)
                with self._lock:
                    romaji = self._cutlet.map_kana(reading)
                out.append(Token(
                    surface=surface, reading=reading, romaji=romaji, pos="名詞",
                    pos_en="unknown word (maybe a name or game term)", base=None,
                    base_reading=None,
                    conjugation=None, note=None, furigana=[(surface, None)], clickable=True,
                    known=False, space_after=run[-1].space_after,
                ))
                i = j
            else:
                out.append(tokens[i])
                i += 1
        return out

    def analyze(self, lines: list[str]) -> list[list[Token]]:
        return [self.analyze_line(line) for line in lines]

    def _token(self, word, romaji: str, space_after: bool) -> Token:
        f = word.feature
        surface = word.surface
        pos1 = _clean(f.pos1) or ""
        pos2 = _clean(f.pos2)
        kana = _clean(f.kana)
        known = not word.is_unk
        if kana is not None:
            reading = to_hiragana(kana)
        elif is_all_kana(surface):
            reading = to_hiragana(surface)
        else:
            reading = None

        base = _clean(f.orthBase)
        base_kana = _clean(f.kanaBase)
        conj = None
        if _clean(f.cType):
            conj = f"{f.cType} / {f.cForm}"

        note = None
        if pos1 == "助詞" and surface in _PARTICLE_PRON:
            note = f"As a particle, {surface} is pronounced “{_PARTICLE_PRON[surface]}”."

        clickable = pos1 not in _NOT_WORDS and has_japanese(surface)
        pos_en = POS2_EN.get(pos2 or "", POS_EN.get(pos1, pos1))
        return Token(
            surface=surface,
            reading=reading,
            romaji=romaji,
            pos=pos1,
            pos_en=pos_en,
            base=base if base != surface or conj else None,
            base_reading=to_hiragana(base_kana) if base_kana else None,
            conjugation=conj,
            note=note,
            furigana=align(surface, reading) if has_kanji(surface) else [(surface, None)],
            clickable=clickable,
            known=known,
            space_after=space_after,
        )


_shared: Analyzer | None = None
_shared_lock = threading.Lock()


def shared_analyzer() -> Analyzer:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Analyzer()
        return _shared
