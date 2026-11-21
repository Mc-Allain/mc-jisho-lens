"""Align a word's reading to its kanji so furigana sits only over the kanji.

  align("食べ", "たべ")       -> [("食", "た"), ("べ", None)]
  align("取り扱い", "とりあつかい") -> [("取", "と"), ("り", None), ("扱", "あつか"), ("い", None)]
  align("今日", "きょう")     -> [("今日", "きょう")]   (whole-word reading)
"""

from __future__ import annotations

import re
from itertools import groupby

from jisho_lens.core.analysis.kana import has_kanji, is_kanji, to_hiragana

Segment = tuple[str, str | None]


def align(surface: str, reading: str | None) -> list[Segment]:
    if not reading or not has_kanji(surface):
        return [(surface, None)]
    reading = to_hiragana(reading)
    groups = [(k, "".join(g)) for k, g in groupby(surface, key=is_kanji)]
    pattern = "".join("(.+?)" if k else f"({re.escape(to_hiragana(text))})" for k, text in groups)
    match = re.fullmatch(pattern, reading)
    if match is None:
        # reading doesn't line up with the kana in the word: put it over the whole word
        return [(surface, reading)]
    segments: list[Segment] = []
    for (kanji, text), part in zip(groups, match.groups(), strict=True):
        segments.append((text, part) if kanji else (text, None))
    return segments
