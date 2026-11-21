"""Attach dictionary information to analysed text, ready for the popup.

Per word: JMdict entries (meanings by part of speech), longer dictionary words starting at
that word (攻撃 -> 攻撃力), and a reading guess for coined kanji compounds missing from JMdict
(炎 + 核 -> えんかく?). Per page: KANJIDIC2 details for every kanji shown.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from jisho_lens.core.analysis import Token
from jisho_lens.core.analysis.kana import has_kanji, is_kanji, to_hiragana
from jisho_lens.dictionary.db import Dictionary, Entry

log = logging.getLogger(__name__)

_MAX_SENSES = 6
_COMPOUND_POS = {"名詞", "接尾辞", "接頭辞"}


@dataclass
class PageDictionary:
    """Dictionary data for one page of text. `words` is parallel to the flat token list."""

    available: bool
    words: list[dict] = field(default_factory=list)
    has_words: bool = False  # a word dictionary (JMdict or Wiktionary) is installed
    kanji: dict[str, dict] = field(default_factory=dict)


def _entry_dict(d: Dictionary, e: Entry) -> dict:
    senses = []
    for s in e.senses[:_MAX_SENSES]:
        senses.append({
            "pos": [d.pos_label(p) for p in s.pos if p not in ("vt", "vi")],
            "gloss": s.glosses,
            "misc": [d.misc_label(m) for m in s.misc],
            "info": s.info,
            "src": [f"{x['lang']}: {x['text']}" if x["text"] else x["lang"] for x in s.lsource],
        })
    return {
        "forms": [k for k, _ in e.kanji[:3]],
        "readings": [r for r, _ in e.readings[:3]],
        "common": e.common,
        "source": e.source,
        "senses": senses,
        "more": max(0, len(e.senses) - _MAX_SENSES),
    }


def _all_kanji_token(t: Token) -> bool:
    return bool(t.surface) and all(is_kanji(c) for c in t.surface) and t.pos in _COMPOUND_POS


def _compound_runs(d: Dictionary, tokens: list[Token]) -> dict[int, dict]:
    """Runs of adjacent kanji-only nouns/affixes that together aren't a JMdict word, where
    every piece is a single kanji or some piece isn't a word either (炎 + 核, 翼 + 人)."""
    out: dict[int, dict] = {}
    i = 0
    while i < len(tokens):
        j = i
        while j < len(tokens) and _all_kanji_token(tokens[j]) and (
            j == i or tokens[j].start == tokens[j - 1].start + len(tokens[j - 1].surface)
        ):
            j += 1
        run = tokens[i:j]
        if len(run) >= 2:
            text = "".join(t.surface for t in run)
            all_single = all(len(t.surface) == 1 for t in run)
            some_unknown = any(not d.is_word(t.surface) for t in run)
            if not d.is_word(text) and (all_single or some_unknown):
                guess = []
                for ch in text:
                    k = d.kanji(ch)
                    if k is None or not k.onyomi:
                        guess = []
                        break
                    guess.append(to_hiragana(k.onyomi[0]))
                info = {"text": text, "guess": "".join(guess) or None}
                for idx in range(i, j):
                    out[idx] = info
        i = max(j, i + 1)
    return out


def _kanji_dict(d: Dictionary, ch: str) -> dict | None:
    k = d.kanji(ch)
    if k is None:
        return None
    return {
        "on": k.onyomi,
        "kun": k.kunyomi,
        "meanings": k.meanings,
        "strokes": k.strokes,
        "grade": k.grade,
        "jlpt": k.jlpt,
        "freq": k.freq,
        "examples": [list(x) for x in d.example_words(ch)],
    }


def enrich(d: Dictionary | None, lines: list[str], tokens: list[list[Token]]) -> PageDictionary:
    if d is None:
        return PageDictionary(available=False,
                              words=[{} for line in tokens for _ in line])
    page = PageDictionary(available=True, has_words=d.has_jmdict or d.has_wiktionary)
    for line_text, line_tokens in zip(lines, tokens, strict=False):
        # coined-compound guesses need a word list (to know it isn't a word) and kanji readings
        compounds = (_compound_runs(d, line_tokens)
                     if page.has_words and d.has_kanjidic else {})
        for idx, t in enumerate(line_tokens):
            info: dict = {}
            if t.clickable:
                try:
                    entries = d.lookup(t.lookup_keys, t.base_reading or t.reading, t.pos)
                    info["entries"] = [_entry_dict(d, e) for e in entries[:2]]
                    if has_kanji(t.surface) and d.has_jmdict:
                        longer = d.longer_words(line_text, t.start, len(t.surface))
                        shown = {f for e in entries for f, _ in e.kanji}
                        info["longer"] = [
                            {"word": e.headword, "reading": e.readings[0][0],
                             "gloss": "; ".join(e.senses[0].glosses[:3]) if e.senses else ""}
                            for e in longer if e.headword not in shown
                        ]
                    if idx in compounds:
                        info["compound"] = compounds[idx]
                except Exception:  # noqa: BLE001
                    log.exception("dictionary lookup failed for %r", t.surface)
            page.words.append(info)
            for ch in t.surface:
                if is_kanji(ch) and ch not in page.kanji:
                    if (k := _kanji_dict(d, ch)) is not None:
                        page.kanji[ch] = k
    return page
