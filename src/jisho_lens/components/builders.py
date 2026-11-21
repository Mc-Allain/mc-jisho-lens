"""Build the dictionary components, one SQLite file each.

  JMdict (EDRDG, CC BY-SA 4.0)      -> jmdict/jmdict.sqlite
  KANJIDIC2 (EDRDG, CC BY-SA 4.0)   -> kanjidic2/kanjidic2.sqlite
  Wiktionary (kaikki.org / Wiktextract, CC BY-SA 4.0) -> wiktionary/wiktionary.sqlite
                                       + userdic-<lite|full>.dic for each installed UniDic
"""

from __future__ import annotations

import csv
import gzip
import io
import json
import os
import re
import sqlite3
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path

from jisho_lens.components import registry

Progress = Callable[[str], None]

URLS = {
    "jmdict": ("JMdict_e.gz", "https://www.edrdg.org/pub/Nihongo/JMdict_e.gz"),
    "kanjidic2": ("kanjidic2.xml.gz", "https://www.edrdg.org/kanjidic/kanjidic2.xml.gz"),
    "wiktionary": ("kaikki-Japanese.jsonl.gz",
                   "https://kaikki.org/dictionary/Japanese/kaikki.org-dictionary-Japanese.jsonl.gz"),
}
COMMON_TAGS = {"news1", "ichi1", "spec1", "spec2", "gai1"}
_XML_STD = {"amp", "lt", "gt", "quot", "apos"}
EDRDG_LICENCE = (
    "JMdict and KANJIDIC2 are the property of the Electronic Dictionary Research and "
    "Development Group (EDRDG), used in conformance with the Group's licence (CC BY-SA 4.0). "
    "https://www.edrdg.org/edrdg/licence.html")
WIKTIONARY_LICENCE = (
    "Words from Wiktionary (https://en.wiktionary.org), CC BY-SA 4.0, extracted by "
    "Wiktextract (kaikki.org).")
# Wiktionary parts of speech kept for popup lookups
WK_POS = {"noun", "verb", "adj", "adv", "intj", "pron", "phrase", "suffix", "prefix", "name",
          "counter", "particle"}
# Word cost for user-dictionary nouns. 7000 fixed じっちゃ and changed ~1% of 2,000-3,000
# sample sentences (almost all into real compounds); 4000 produced bad splits (亜 + 麻色).
USERDIC_COST = 7000
_JP_WORD = re.compile(r"[぀-ヿ㐀-鿿々ー]+")


def download(component_id: str, progress: Progress, refresh: bool = False) -> Path:
    name, url = URLS[component_id]
    folder = registry.sources_dir()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    if path.exists() and not refresh:
        return path
    progress(f"Downloading {name}…")
    req = urllib.request.Request(url, headers={"User-Agent": "mc-jisho-lens-dict-builder"})
    part = path.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=300) as resp, open(part, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        done = 0
        while chunk := resp.read(1 << 16):
            f.write(chunk)
            done += len(chunk)
            if total and done % (1 << 22) < (1 << 16):
                progress(f"Downloading {name}… {100 * done // total}%")
    part.replace(path)
    return path


def _new_db(path: Path, schema: str) -> tuple[sqlite3.Connection, Path]:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".building")
    tmp.unlink(missing_ok=True)
    db = sqlite3.connect(tmp)
    db.executescript(schema)
    return db, tmp


def _finish_db(db: sqlite3.Connection, tmp: Path, path: Path, indexes: str) -> None:
    db.executescript(indexes)
    db.commit()
    db.execute("VACUUM")
    db.close()
    tmp.replace(path)


# ---------------------------------------------------------------- JMdict
JMDICT_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE tag (code TEXT PRIMARY KEY, description TEXT);
CREATE TABLE entry (id INTEGER PRIMARY KEY, seq INTEGER, common INTEGER, rank INTEGER);
CREATE TABLE kanji_form (entry_id INTEGER, ord INTEGER, text TEXT, common INTEGER, info TEXT);
CREATE TABLE reading (entry_id INTEGER, ord INTEGER, text TEXT, common INTEGER, info TEXT,
                      restr TEXT, no_kanji INTEGER);
CREATE TABLE sense (entry_id INTEGER, ord INTEGER, pos TEXT, misc TEXT, field TEXT, dial TEXT,
                    info TEXT, lsource TEXT, stagk TEXT, stagr TEXT, gloss TEXT);
-- common words (2-4 characters) containing each kanji, for the kanji panel's examples
CREATE TABLE kanji_word (literal TEXT, text TEXT, entry_id INTEGER, rank INTEGER);
"""
JMDICT_INDEXES = """
CREATE INDEX kanji_form_text ON kanji_form(text);
CREATE INDEX reading_text ON reading(text);
CREATE INDEX sense_entry ON sense(entry_id);
CREATE INDEX kanji_form_entry ON kanji_form(entry_id);
CREATE INDEX reading_entry ON reading(entry_id);
CREATE INDEX kanji_word_literal ON kanji_word(literal, rank);
"""


def _priority(elem, tag: str) -> tuple[bool, int | None]:
    pris = [p.text for p in elem.findall(tag)]
    common = any(p in COMMON_TAGS for p in pris)
    nf = [int(p[2:]) for p in pris if p and p.startswith("nf")]
    return common, (min(nf) if nf else None)


def build_jmdict(progress: Progress, refresh: bool = False) -> int:
    from jisho_lens.core.analysis.kana import is_kanji

    src = download("jmdict", progress, refresh)
    progress("Building JMdict…")
    raw = gzip.decompress(src.read_bytes()).decode("utf-8")
    db, tmp = _new_db(registry.database_path("jmdict"), JMDICT_SCHEMA)
    db.execute("INSERT INTO meta VALUES ('licence', ?)", (EDRDG_LICENCE,))
    created = re.search(r"<!-- JMdict created: ([\d-]+) -->", raw)
    db.execute("INSERT INTO meta VALUES ('date', ?)", (created.group(1) if created else "",))
    # keep entity names (e.g. "v5r") instead of their long descriptions
    # (some entity names are declared twice in the DTD: keep one)
    db.executemany("INSERT INTO tag VALUES (?, ?)",
                   dict(re.findall(r'<!ENTITY ([\w-]+) "([^"]*)">', raw)).items())
    body = re.sub(r"&([\w-]+);",
                  lambda m: m.group(0) if m.group(1) in _XML_STD else m.group(1),
                  raw[raw.index("<JMdict>"):])
    count = 0
    for _, el in ET.iterparse(io.StringIO(body), events=("end",)):
        if el.tag != "entry":
            continue
        count += 1
        entry_common, best_nf = False, None
        k_rows, r_rows, s_rows = [], [], []
        for i, k in enumerate(el.findall("k_ele")):
            common, nf = _priority(k, "ke_pri")
            entry_common |= common
            best_nf = nf if best_nf is None or (nf is not None and nf < best_nf) else best_nf
            k_rows.append((count, i, k.findtext("keb"), int(common),
                           json.dumps([x.text for x in k.findall("ke_inf")])))
        for i, r in enumerate(el.findall("r_ele")):
            common, nf = _priority(r, "re_pri")
            entry_common |= common
            best_nf = nf if best_nf is None or (nf is not None and nf < best_nf) else best_nf
            r_rows.append((count, i, r.findtext("reb"), int(common),
                           json.dumps([x.text for x in r.findall("re_inf")]),
                           json.dumps([x.text for x in r.findall("re_restr")]),
                           int(r.find("re_nokanji") is not None)))
        last_pos: list[str] = []
        for i, s in enumerate(el.findall("sense")):
            pos = [x.text for x in s.findall("pos")] or last_pos  # pos carries over
            last_pos = pos
            lsource = [{"lang": x.get("{http://www.w3.org/XML/1998/namespace}lang", "eng"),
                        "text": x.text or ""} for x in s.findall("lsource")]
            s_rows.append((
                count, i, json.dumps(pos),
                json.dumps([x.text for x in s.findall("misc")]),
                json.dumps([x.text for x in s.findall("field")]),
                json.dumps([x.text for x in s.findall("dial")]),
                json.dumps([x.text for x in s.findall("s_inf")]),
                json.dumps(lsource),
                json.dumps([x.text for x in s.findall("stagk")]),
                json.dumps([x.text for x in s.findall("stagr")]),
                json.dumps([g.text for g in s.findall("gloss") if g.text], ensure_ascii=False),
            ))
        rank = best_nf if best_nf is not None else (49 if entry_common else 99)
        db.execute("INSERT INTO entry VALUES (?, ?, ?, ?)",
                   (count, int(el.findtext("ent_seq")), int(entry_common), rank))
        db.executemany("INSERT INTO kanji_form VALUES (?, ?, ?, ?, ?)", k_rows)
        db.executemany("INSERT INTO reading VALUES (?, ?, ?, ?, ?, ?, ?)", r_rows)
        db.executemany("INSERT INTO sense VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", s_rows)
        for _, _, text, common, _ in k_rows:
            if common and 2 <= len(text) <= 4:
                db.executemany("INSERT INTO kanji_word VALUES (?, ?, ?, ?)",
                               [(ch, text, count, rank) for ch in set(text) if is_kanji(ch)])
        el.clear()
    _finish_db(db, tmp, registry.database_path("jmdict"), JMDICT_INDEXES)
    return count


# ---------------------------------------------------------------- KANJIDIC2
KANJIDIC_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE kanji (literal TEXT PRIMARY KEY, grade INTEGER, strokes INTEGER, freq INTEGER,
                    jlpt INTEGER, onyomi TEXT, kunyomi TEXT, nanori TEXT, meanings TEXT);
"""


def build_kanjidic(progress: Progress, refresh: bool = False) -> int:
    src = download("kanjidic2", progress, refresh)
    progress("Building KANJIDIC2…")
    root = ET.fromstring(gzip.decompress(src.read_bytes()))
    db, tmp = _new_db(registry.database_path("kanjidic2"), KANJIDIC_SCHEMA)
    db.execute("INSERT INTO meta VALUES ('licence', ?)", (EDRDG_LICENCE,))
    db.execute("INSERT INTO meta VALUES ('date', ?)",
               (root.findtext("header/date_of_creation") or "",))
    rows = []
    for ch in root.findall("character"):
        misc = ch.find("misc")

        def num(tag, m=misc):
            v = m.findtext(tag) if m is not None else None
            return int(v) if v else None

        rm = ch.find("reading_meaning")
        on, kun, meanings, nanori = [], [], [], []
        if rm is not None:
            for g in rm.findall("rmgroup"):
                on += [r.text for r in g.findall("reading") if r.get("r_type") == "ja_on"]
                kun += [r.text for r in g.findall("reading") if r.get("r_type") == "ja_kun"]
                meanings += [m.text for m in g.findall("meaning") if m.get("m_lang") is None]
            nanori = [n.text for n in rm.findall("nanori")]
        rows.append((ch.findtext("literal"), num("grade"), num("stroke_count"), num("freq"),
                     num("jlpt"), json.dumps(on, ensure_ascii=False),
                     json.dumps(kun, ensure_ascii=False), json.dumps(nanori, ensure_ascii=False),
                     json.dumps(meanings, ensure_ascii=False)))
    db.executemany("INSERT INTO kanji VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    _finish_db(db, tmp, registry.database_path("kanjidic2"), "")
    return len(rows)


# ---------------------------------------------------------------- Wiktionary
WIKTIONARY_SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE wk_entry (id INTEGER PRIMARY KEY, word TEXT, reading TEXT, pos TEXT, tags TEXT);
CREATE TABLE wk_sense (entry_id INTEGER, ord INTEGER, gloss TEXT, tags TEXT);
"""
WIKTIONARY_INDEXES = """
CREATE INDEX wk_entry_word ON wk_entry(word);
CREATE INDEX wk_entry_reading ON wk_entry(reading);
CREATE INDEX wk_sense_entry ON wk_sense(entry_id);
"""


def _wk_reading(e: dict) -> str | None:
    """Kana reading: the word itself if kana, else the ruby of the canonical form
    (炎上 -> えんじょう), else the kana head-template argument."""
    from jisho_lens.core.analysis.kana import is_all_kana

    word = e["word"]
    if is_all_kana(word):
        return word
    for form in e.get("forms", []):
        if "canonical" in (form.get("tags") or []) and form.get("ruby"):
            out, rest = "", word
            for base, ruby in form["ruby"]:
                i = rest.find(base)
                if i < 0:
                    return None
                out += rest[:i] + ruby
                rest = rest[i + len(base):]
            return out + rest
    for head in e.get("head_templates", []):
        value = (head.get("args") or {}).get("1")
        if value and is_all_kana(value):
            return value
    return None


def build_wiktionary(progress: Progress, refresh: bool = False) -> int:
    """All Japanese-script Wiktionary words (JMdict, when installed, is looked up first)."""
    from jisho_lens.core.analysis.kana import to_hiragana

    src = download("wiktionary", progress, refresh)
    progress("Building Wiktionary…")
    db, tmp = _new_db(registry.database_path("wiktionary"), WIKTIONARY_SCHEMA)
    db.execute("INSERT INTO meta VALUES ('licence', ?)", (WIKTIONARY_LICENCE,))
    db.execute("INSERT INTO meta VALUES ('date', ?)",
               (time.strftime("%Y-%m-%d", time.gmtime(src.stat().st_mtime)),))
    count = 0
    with gzip.open(src, "rt", encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            word = e.get("word", "")
            if e.get("pos") not in WK_POS or not _JP_WORD.fullmatch(word):
                continue
            senses = []
            for s in e.get("senses", []):
                glosses = s.get("raw_glosses") or s.get("glosses") or []
                if glosses:
                    senses.append(("; ".join(glosses), json.dumps(s.get("tags") or [])))
            if not senses:
                continue
            reading = _wk_reading(e)
            count += 1
            tags = sorted({tag for s in e.get("senses", []) for tag in (s.get("tags") or [])})
            db.execute("INSERT INTO wk_entry VALUES (?, ?, ?, ?, ?)",
                       (count, word, to_hiragana(reading) if reading else None, e["pos"],
                        json.dumps(tags)))
            db.executemany("INSERT INTO wk_sense VALUES (?, ?, ?, ?)",
                           [(count, i, g, tg) for i, (g, tg) in enumerate(senses)])
    _finish_db(db, tmp, registry.database_path("wiktionary"), WIKTIONARY_INDEXES)
    return count


def build_user_dictionary(mode: str, progress: Progress) -> int:
    """MeCab user dictionary of Wiktionary nouns for one installed UniDic ("lite"/"full"),
    so the word splitter keeps words such as じっちゃ whole (まえ + に + じっちゃ).
    Only nouns of 3+ kana or 2+ characters with kanji that UniDic doesn't already know."""
    import fugashi

    from jisho_lens.core.analysis.kana import is_all_kana

    component = registry.MODE_COMPONENT[mode]
    target = registry.user_dictionary_path(mode)
    if not (registry.is_installed(component) and registry.database_path("wiktionary").exists()):
        target.unlink(missing_ok=True)
        return 0
    progress(f"Teaching the word splitter Wiktionary words ({mode})…")
    db = sqlite3.connect(registry.database_path("wiktionary"))
    nouns = [(w, r) for w, r in db.execute(
        "SELECT DISTINCT word, reading FROM wk_entry WHERE pos = 'noun' AND reading IS NOT NULL")
        if (len(w) >= 3 if is_all_kana(w) else len(w) >= 2)]
    db.close()
    # With JMdict installed, only add words JMdict lacks (じっちゃ). Adding JMdict's compounds
    # too (冒険者, 双眼鏡, …) changed ~19% of sample sentences instead of ~1%; JMdict's
    # "Part of" lookup already shows those compounds.
    if registry.is_installed("jmdict"):
        jm = sqlite3.connect(registry.database_path("jmdict"))
        in_jmdict = {r[0] for r in jm.execute(
            "SELECT text FROM kanji_form UNION SELECT text FROM reading")}
        jm.close()
        nouns = [(w, r) for w, r in nouns if w not in in_jmdict]
    dicdir = registry.unidic_package_dir(component)
    d = str(dicdir).replace("\\", "/")
    tagger = fugashi.Tagger(f'-d "{d}" -r "{d}/mecabrc"')
    rows = []
    for word, reading in nouns:
        toks = tagger(word)
        if len(toks) == 1 and not toks[0].is_unk:
            continue  # UniDic already knows it as one word
        kata = reading.translate({c: c + 0x60 for c in range(0x3041, 0x3097)})
        rows.append([word, "", "", str(USERDIC_COST), "名詞", "普通名詞", "一般", "*", "*", "*",
                     kata, word, word, kata, word, kata, "*", "*", "*", "*", "*",
                     kata, kata, kata, kata, "*", "*", "*", "*", "*"])
    # mecab-dict-index (via fugashi) splits its arguments on spaces and wants a program name
    # first, so run it from inside the UniDic folder with space-free temporary paths.
    tmp_dir = Path(os.environ.get("TEMP", str(target.parent))) / "jisho-lens-userdic"
    if " " in str(tmp_dir):
        raise RuntimeError(f"temporary folder path contains a space: {tmp_dir}")
    tmp_dir.mkdir(parents=True, exist_ok=True)
    tmp_csv, tmp_dic = tmp_dir / f"{mode}.csv", tmp_dir / f"{mode}.dic"
    with open(tmp_csv, "w", encoding="utf-8", newline="") as fh:
        csv.writer(fh).writerows(rows)
    cwd = os.getcwd()
    try:
        os.chdir(dicdir)
        fugashi.build_dictionary(
            f"mecab-dict-index -d . -u {tmp_dic.as_posix()} -f utf8 -t utf8 {tmp_csv.as_posix()}")
    finally:
        os.chdir(cwd)
    target.write_bytes(tmp_dic.read_bytes())
    return len(rows)
