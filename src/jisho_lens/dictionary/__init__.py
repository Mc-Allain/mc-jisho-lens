"""Offline dictionary: JMdict words and KANJIDIC2 kanji (EDRDG, CC BY-SA 4.0).

Each source is an optional component (jisho_lens.components); Phase 7 makes them modules.
"""

from jisho_lens.dictionary.db import (
    Dictionary,
    DictionaryMissing,
    Entry,
    KanjiInfo,
    Sense,
    optional_dictionary,
    reset_shared,
    shared_dictionary,
)

__all__ = ["Dictionary", "DictionaryMissing", "Entry", "KanjiInfo", "Sense",
           "optional_dictionary", "reset_shared", "shared_dictionary"]
