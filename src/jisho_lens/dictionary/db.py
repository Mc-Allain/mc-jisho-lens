"""Read-only access to the installed dictionary components (each optional):
JMdict words and KANJIDIC2 kanji (EDRDG, CC BY-SA 4.0), Wiktionary words (CC BY-SA 4.0).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from jisho_lens.components import registry
from jisho_lens.core.analysis.kana import has_kanji, to_hiragana

# Short English labels for the JMdict part-of-speech codes seen most; others fall back to
# the description stored in the database.
POS_LABELS = {
    "n": "noun", "n-suf": "noun (suffix)", "n-pref": "noun (prefix)", "n-adv": "adverbial noun",
    "n-t": "noun (time)", "pn": "pronoun", "num": "number", "ctr": "counter",
    "v1": "ichidan verb", "v1-s": "ichidan verb", "vs": "suru verb", "vs-i": "suru verb",
    "vs-s": "suru verb", "vk": "kuru verb", "vz": "zuru verb", "vt": "transitive",
    "vi": "intransitive", "adj-i": "i-adjective", "adj-ix": "i-adjective (いい/よい)",
    "adj-na": "na-adjective", "adj-no": "no-adjective", "adj-pn": "pre-noun adjectival",
    "adj-t": "taru-adjective", "adj-f": "noun or verb acting prenominally", "adv": "adverb",
    "adv-to": "adverb (と)", "aux": "auxiliary", "aux-v": "auxiliary verb",
    "aux-adj": "auxiliary adjective", "conj": "conjunction", "cop": "copula",
    "exp": "expression", "int": "interjection", "prt": "particle", "pref": "prefix",
    "suf": "suffix", "unc": "unclassified",
}
for _ending in "bgkmnrstu":
    POS_LABELS[f"v5{_ending}"] = "godan verb"
POS_LABELS.update({"v5k-s": "godan verb (行く)", "v5r-i": "godan verb (irregular)",
                   "v5aru": "godan verb (-aru)", "v5u-s": "godan verb"})
MISC_LABELS = {
    "uk": "usually written in kana", "col": "colloquial", "hon": "honorific",
    "hum": "humble", "pol": "polite", "sl": "slang", "arch": "archaic", "obs": "obsolete",
    "rare": "rare", "vulg": "vulgar", "derog": "derogatory", "fam": "familiar",
    "male": "male speech", "fem": "female speech", "joc": "jocular", "abbr": "abbreviation",
    "on-mim": "onomatopoeia", "id": "idiom", "yoji": "four-character idiom",
    "chn": "children's language", "poet": "poetic", "form": "formal",
}


# UniDic part of speech -> JMdict part-of-speech code prefixes that are compatible
_UNIDIC_TO_JMDICT_POS = {
    "助詞": ("prt", "conj"),
    "助動詞": ("aux", "cop", "suf"),
    "動詞": ("v",),
    "形容詞": ("adj-i",),
    "形状詞": ("adj-na", "adj-no", "adj-t"),
    "名詞": ("n", "pn", "num", "adj-no", "vs", "ctr"),
    "代名詞": ("pn", "n"),
    "副詞": ("adv",),
    "接尾辞": ("suf", "n-suf", "ctr"),
    "接頭辞": ("pref", "n-pref"),
    "感動詞": ("int",),
    "接続詞": ("conj",),
    "連体詞": ("adj-pn",),
}


_WK_POS = {"noun": "noun", "verb": "verb", "adj": "adjective", "adv": "adverb",
           "intj": "interjection", "pron": "pronoun", "phrase": "phrase", "suffix": "suffix",
           "prefix": "prefix", "name": "name", "counter": "counter", "particle": "particle"}


@dataclass
class Sense:
    pos: list[str]
    glosses: list[str]
    misc: list[str]
    fields: list[str]
    info: list[str]
    lsource: list[dict]


@dataclass
class Entry:
    entry_id: int
    common: bool
    rank: int
    kanji: list[tuple[str, bool]]  # (text, common)
    readings: list[tuple[str, bool]]
    senses: list[Sense] = field(default_factory=list)
    source: str = "jmdict"  # or "wiktionary" (words JMdict doesn't have)

    @property
    def headword(self) -> str:
        return self.kanji[0][0] if self.kanji else self.readings[0][0]


@dataclass
class KanjiInfo:
    literal: str
    grade: int | None
    strokes: int | None
    freq: int | None
    jlpt: int | None  # old 4-level JLPT
    onyomi: list[str]
    kunyomi: list[str]
    meanings: list[str]


class DictionaryMissing(RuntimeError):
    pass


_SOURCES = ("jmdict", "kanjidic2", "wiktionary")


class Dictionary:
    """Read-only access to the installed dictionary components (JMdict, KANJIDIC2,
    Wiktionary), each optional. Thread-safe: one SQLite connection per thread and source."""

    def __init__(self, folder: Path | None = None) -> None:
        """folder: a components folder (tests); default: the installed components."""
        self._paths: dict[str, Path] = {}
        for source in _SOURCES:
            path = (folder / source / f"{source}.sqlite") if folder else \
                registry.database_path(source)
            if path.exists() and (folder or registry.is_installed(source)):
                self._paths[source] = path
        if not self._paths:
            raise DictionaryMissing(
                "No dictionary installed. Install JMdict, KANJIDIC2 or Wiktionary in "
                "Settings > Components (needs UniDic-lite or full UniDic).")
        self._local = threading.local()
        self._all_connections: list[sqlite3.Connection] = []
        self._lock = threading.Lock()
        jm = self._db("jmdict")
        self._tags = dict(jm.execute("SELECT code, description FROM tag")) if jm else {}

    # ---------- connections ----------
    @property
    def has_jmdict(self) -> bool:
        return "jmdict" in self._paths

    @property
    def has_kanjidic(self) -> bool:
        return "kanjidic2" in self._paths

    @property
    def has_wiktionary(self) -> bool:
        return "wiktionary" in self._paths

    def _db(self, source: str) -> sqlite3.Connection | None:
        if source not in self._paths:
            return None
        conns = getattr(self._local, "conns", None)
        if conns is None:
            conns = self._local.conns = {}
        conn = conns.get(source)
        if conn is None:
            uri = self._paths[source].resolve().as_uri() + "?mode=ro"
            conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
            conns[source] = conn
            with self._lock:
                self._all_connections.append(conn)
        return conn

    def close(self) -> None:
        """Close every connection (all threads), so the files can be removed."""
        with self._lock:
            for conn in self._all_connections:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            self._all_connections.clear()

    def meta(self) -> dict[str, str]:
        out = {}
        for source in self._paths:
            for key, value in self._db(source).execute("SELECT key, value FROM meta"):
                out[f"{source}_{key}"] = value
        return out

    # ---------- labels ----------
    def pos_label(self, code: str) -> str:
        return POS_LABELS.get(code) or self._tags.get(code, code)

    def misc_label(self, code: str) -> str:
        return MISC_LABELS.get(code) or self._tags.get(code, code)

    # ---------- word queries ----------
    def entry_ids(self, text: str) -> list[int]:
        jm = self._db("jmdict")
        if jm is None:
            return []
        table = "kanji_form" if has_kanji(text) else "reading"
        return [r[0] for r in jm.execute(
            f"SELECT DISTINCT entry_id FROM {table} WHERE text = ?", (text,))]

    def _in_wiktionary(self, text: str) -> bool:
        wk = self._db("wiktionary")
        return wk is not None and wk.execute(
            "SELECT 1 FROM wk_entry WHERE word = ? LIMIT 1", (text,)).fetchone() is not None

    @lru_cache(maxsize=20000)  # noqa: B019 (one long-lived instance)
    def word_status(self, text: str) -> tuple[bool, bool]:
        """(is a dictionary word, is a common word) for this exact written form.
        Commonness comes from JMdict; Wiktionary-only words are never common."""
        jm = self._db("jmdict")
        if jm is not None:
            table = "kanji_form" if has_kanji(text) else "reading"
            row = jm.execute(
                f"SELECT MAX(common) FROM {table} WHERE text = ?", (text,)).fetchone()
            if row is not None and row[0] is not None:
                return True, bool(row[0])
        return self._in_wiktionary(text), False

    @lru_cache(maxsize=20000)  # noqa: B019
    def is_extra(self, text: str) -> bool:
        """True for words found in Wiktionary but not in JMdict."""
        return self._in_wiktionary(text) and not self.entry_ids(text)

    def is_word(self, text: str) -> bool:
        return self.word_status(text)[0]

    def is_common(self, text: str) -> bool:
        return self.word_status(text)[1]

    def entries(self, ids: list[int]) -> list[Entry]:
        db = self._db("jmdict")
        out = []
        for eid in ids:
            common, rank = db.execute(
                "SELECT common, rank FROM entry WHERE id = ?", (eid,)).fetchone()
            kanji = [(t, bool(c)) for t, c in db.execute(
                "SELECT text, common FROM kanji_form WHERE entry_id = ? ORDER BY ord", (eid,))]
            readings = [(t, bool(c)) for t, c in db.execute(
                "SELECT text, common FROM reading WHERE entry_id = ? ORDER BY ord", (eid,))]
            senses = [
                Sense(json.loads(p), json.loads(g), json.loads(m), json.loads(f), json.loads(i),
                      json.loads(ls))
                for p, g, m, f, i, ls in db.execute(
                    "SELECT pos, gloss, misc, field, info, lsource FROM sense "
                    "WHERE entry_id = ? ORDER BY ord", (eid,))
            ]
            out.append(Entry(eid, bool(common), rank, kanji, readings, senses))
        return out

    def lookup(self, keys: list[str], reading: str | None = None, pos: str | None = None,
               limit: int = 3) -> list[Entry]:
        """Entries for the first key that matches, best first: JMdict, then Wiktionary.

        reading: the reading in context (hiragana or katakana); when some entries have it,
                 only those are kept (家 read いえ doesn't list 内/うち).
        pos:     UniDic part of speech (e.g. 助詞); when some entries have a matching JMdict
                 part of speech, only those are kept (the particle は doesn't list 葉/歯).
        """
        reading_h = to_hiragana(reading) if reading else None
        for key in keys:
            if not key:
                continue
            ids = self.entry_ids(key)
            if not ids:
                continue
            entries = self.entries(ids)
            if reading_h:
                same = [e for e in entries
                        if any(to_hiragana(r) == reading_h for r, _ in e.readings)]
                entries = same or entries
            if pos in _UNIDIC_TO_JMDICT_POS:
                prefixes = _UNIDIC_TO_JMDICT_POS[pos]
                same = [e for e in entries
                        if any(p.startswith(prefixes) for s in e.senses for p in s.pos)]
                entries = same or entries

            def score(e: Entry, key=key) -> tuple:
                exact_form = any(k == key for k, _ in e.kanji) or any(
                    r == key for r, _ in e.readings)
                return (not exact_form, not e.common, e.rank, e.entry_id)

            entries.sort(key=score)
            return entries[:limit]
        return self.wiktionary_lookup(keys, reading_h, limit)

    def wiktionary_lookup(self, keys: list[str], reading: str | None = None,
                          limit: int = 3) -> list[Entry]:
        """Wiktionary entries (used when JMdict has no entry, e.g. じっちゃ)."""
        db = self._db("wiktionary")
        if db is None:
            return []
        for key in keys:
            if not key:
                continue
            rows = db.execute("SELECT id, word, reading, pos FROM wk_entry WHERE word = ?",
                              (key,)).fetchall()
            if not rows:
                continue
            if reading:
                same = [r for r in rows if r[2] == reading]
                rows = same or rows
            out = []
            for eid, word, wk_reading, pos in rows[:limit]:
                senses = [
                    Sense([_WK_POS.get(pos, pos)], [gloss], [], [], [], [])
                    for gloss, in db.execute(
                        "SELECT gloss FROM wk_sense WHERE entry_id = ? ORDER BY ord", (eid,))
                ]
                kanji = [(word, False)] if has_kanji(word) else []
                readings = [(wk_reading or word, False)]
                out.append(Entry(-eid, False, 99, kanji, readings, senses, "wiktionary"))
            return out
        return []

    def longer_words(self, text: str, start: int, min_len: int, limit: int = 2
                     ) -> list[Entry]:
        """JMdict words that start at `start` in `text` and are longer than `min_len`
        characters (e.g. 攻撃力 when the word clicked is 攻撃). Longest first."""
        found = []
        for end in range(min(len(text), start + 12), start + min_len, -1):
            candidate = text[start:end]
            if self.entry_ids(candidate):
                found += self.lookup([candidate], limit=1)
                if len(found) >= limit:
                    break
        return found

    # ---------- kanji ----------
    @lru_cache(maxsize=4000)  # noqa: B019
    def kanji(self, literal: str) -> KanjiInfo | None:
        kd = self._db("kanjidic2")
        if kd is None:
            return None
        row = kd.execute(
            "SELECT literal, grade, strokes, freq, jlpt, onyomi, kunyomi, meanings "
            "FROM kanji WHERE literal = ?", (literal,)).fetchone()
        if row is None:
            return None
        lit, grade, strokes, freq, jlpt, on, kun, meanings = row
        return KanjiInfo(lit, grade, strokes, freq, jlpt, json.loads(on), json.loads(kun),
                         json.loads(meanings))

    @lru_cache(maxsize=4000)  # noqa: B019
    def example_words(self, literal: str, limit: int = 4) -> list[tuple[str, str, str]]:
        """Common JMdict words containing the kanji: (word, reading, first gloss)."""
        jm = self._db("jmdict")
        if jm is None:
            return []
        rows = jm.execute(
            "SELECT text, entry_id FROM kanji_word WHERE literal = ? "
            "ORDER BY rank, length(text) LIMIT ?", (literal, limit * 3)).fetchall()
        out, seen = [], set()
        for text, eid in rows:
            if text in seen:
                continue
            seen.add(text)
            reading = jm.execute(
                "SELECT text FROM reading WHERE entry_id = ? ORDER BY ord LIMIT 1",
                (eid,)).fetchone()
            gloss = jm.execute(
                "SELECT gloss FROM sense WHERE entry_id = ? ORDER BY ord LIMIT 1",
                (eid,)).fetchone()
            out.append((text, reading[0] if reading else "",
                        json.loads(gloss[0])[0] if gloss and json.loads(gloss[0]) else ""))
            if len(out) >= limit:
                break
        return out


_shared: Dictionary | None = None
_shared_lock = threading.Lock()


def shared_dictionary() -> Dictionary:
    global _shared
    with _shared_lock:
        if _shared is None:
            _shared = Dictionary()
        return _shared


def optional_dictionary() -> Dictionary | None:
    """The shared dictionary, or None when no dictionary component is installed."""
    try:
        return shared_dictionary()
    except DictionaryMissing:
        return None


def reset_shared() -> None:
    """Forget (and close) the shared dictionary, e.g. before components change."""
    global _shared
    with _shared_lock:
        if _shared is not None:
            _shared.close()
        _shared = None
