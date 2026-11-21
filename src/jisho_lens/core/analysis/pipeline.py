"""Text -> words -> dictionary data, following Settings > Word splitting and the installed
components.

  splitting "none"            -> plain text: no words, no dictionary
  splitting "lite" / "full"   -> words, readings, furigana, romaji, grammar
    + installed dictionaries  -> meanings (JMdict, Wiktionary), kanji details (KANJIDIC2),
                                 dictionary-based split fixes
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from jisho_lens.components import on_before_change
from jisho_lens.core.analysis.analyzer import (
    DictionaryMissing,
    Token,
    reset_shared,
    shared_analyzer,
)

log = logging.getLogger(__name__)


def _release_dictionary() -> None:
    from jisho_lens.dictionary.db import reset_shared as reset_dictionary

    reset_dictionary()


# Release MeCab and SQLite files before components are installed or removed (Windows
# can't delete open files), so the next analysis loads the new set.
on_before_change(reset_shared)
on_before_change(_release_dictionary)


@dataclass
class TextAnalysis:
    tokens: list[list[Token]] = field(default_factory=list)  # empty = plain text
    dictionary: object | None = None  # dictionary.enrich.PageDictionary, or None
    warning: str | None = None  # e.g. "UniDic-lite is not installed …"

    @property
    def has_words(self) -> bool:
        return bool(self.tokens)


def analyze_text(lines: list[str], splitting: str, use_dictionary: bool) -> TextAnalysis:
    if splitting == "none" or not lines:
        return TextAnalysis()
    try:
        analyzer = shared_analyzer(splitting, use_dictionary)
    except DictionaryMissing as exc:
        log.warning("word splitting unavailable: %s", exc)
        return TextAnalysis(warning=str(exc))
    tokens = analyzer.analyze(lines)
    if not use_dictionary:
        return TextAnalysis(tokens=tokens)
    from jisho_lens.dictionary import optional_dictionary
    from jisho_lens.dictionary.enrich import enrich

    d = optional_dictionary()
    if d is None:  # no dictionary component installed: words without meanings
        return TextAnalysis(tokens=tokens)
    return TextAnalysis(tokens=tokens, dictionary=enrich(d, lines, tokens))
