"""Split Japanese text into words with readings, furigana, romaji and grammar
(SPEC §3.1 Text analysis).

Uses fugashi (MeCab) with UniDic-lite or full UniDic (Settings > Word splitting) for word
splitting and context-correct readings, and cutlet for Hepburn romaji. Romaji follows the
kana (スター -> "sutaa", not "star"), because the point is learning to read.

When a word checker (the JMdict dictionary) is available, MeCab's alternative splits are
checked too: a different split is used only when it creates a *common* dictionary word,
the word it replaces is *not* common, and every new piece is still a real word.
(火元 + 素 -> 火 + 元素, while 攻撃 + 力, 日本 + 人, 大陸 + 中 stay.)
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol

from jisho_lens.core.analysis import grammar
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
_GRAMMAR_POS = {"助詞", "助動詞", "接尾辞", "接頭辞"}
_CONTENT_POS = {"名詞", "代名詞", "動詞", "形容詞", "形状詞", "副詞", "連体詞", "感動詞",
                "接続詞"}
_MAPPING_FIXES = {"うぃ": "wi", "うぇ": "we", "うぉ": "wo", "くぁ": "kwa", "いぇ": "ye"}
_NBEST = 6


class WordChecker(Protocol):
    def is_word(self, text: str) -> bool: ...
    def is_common(self, text: str) -> bool: ...


@dataclass
class Token:
    surface: str
    reading: str | None  # hiragana reading in this sentence
    romaji: str
    pos: str  # Japanese POS (UniDic pos1)
    pos_en: str
    base: str | None  # dictionary form, as written (e.g. 食べる), when it differs
    base_reading: str | None
    conjugation: str | None  # raw UniDic "type / form"
    note: str | None  # particle note
    furigana: list[Segment] = field(default_factory=list)
    clickable: bool = False
    known: bool = True  # False when UniDic didn't know the word
    space_after: bool = False
    start: int = 0  # character offset in the line
    lemma: str | None = None  # UniDic lemma (e.g. 為る for する), for dictionary lookup
    orth_base: str | None = None  # dictionary form as written, always set when known
    word_class: str | None = None  # e.g. "ichidan verb"
    form: str | None = None  # e.g. "negative / passive stem"
    phrase: str | None = None  # verb/adjective with its endings, e.g. 食べられなかった
    grammar: list[grammar.GrammarPart] = field(default_factory=list)
    boundary_fixed: bool = False  # split changed by the dictionary check

    @property
    def lookup_keys(self) -> list[str]:
        keys = [self.orth_base, self.lemma, self.surface]
        return list(dict.fromkeys(k for k in keys if k))

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
            "wclass": self.word_class,
            "form": self.form,
            "phrase": self.phrase,
            "grammar": [[g.surface, g.label] for g in self.grammar],
            "note": self.note,
            "known": self.known,
            "fixed": self.boundary_fixed,
        }


def _clean(value) -> str | None:
    if value is None or value in ("", "*"):
        return None
    return str(value)


def _clean_lemma(value) -> str | None:
    lemma = _clean(value)
    if lemma and "-" in lemma:  # "スター-star", "カーク-外国"
        lemma = lemma.split("-", 1)[0]
    return lemma


def _is_katakana_word(text: str) -> bool:
    return bool(text) and all(0x30A1 <= ord(c) <= 0x30FA or c == "ー" for c in text)


class DictionaryMissing(RuntimeError):
    pass


# Word-splitting modes (Settings > Word splitting). "none" means plain OCR text only:
# no UniDic. The dictionary (JMdict / KANJIDIC2) is a separate option that is only
# available with "lite" or "full", because meanings need words to click on.
SPLITTING_MODES = ("lite", "full", "none")
SPLITTING_LABELS = {
    "lite": "UniDic-lite (249 MB)",
    "full": "Full UniDic (775 MB, slightly more accurate)",
    "none": "None — plain text only (no words, readings or dictionary)",
}
_INSTALL_HINT = ("Install it in Settings > Components "
                 "(or: uv run python tools/components.py install {component}).")


def unidic_dir(mode: str) -> str:
    """Folder of the installed UniDic component for `mode` ("lite" or "full"); raises
    DictionaryMissing with install instructions when it isn't installed."""
    from jisho_lens.components import registry

    if mode not in registry.MODE_COMPONENT:
        raise DictionaryMissing(f"no UniDic for mode {mode!r}")
    component = registry.MODE_COMPONENT[mode]
    folder = registry.unidic_package_dir(component)
    if not registry.is_installed(component) or not (folder / "sys.dic").exists():
        name = registry.COMPONENTS[component].name
        raise DictionaryMissing(
            f"{name} is not installed. " + _INSTALL_HINT.format(component=component))
    return str(folder)


def available_modes() -> dict[str, str | None]:
    """mode -> None if usable, else the reason it isn't."""
    out: dict[str, str | None] = {"none": None}
    for mode in ("lite", "full"):
        try:
            unidic_dir(mode)
            out[mode] = None
        except DictionaryMissing as exc:
            out[mode] = str(exc)
    return {m: out[m] for m in SPLITTING_MODES}


def check_dictionary() -> str:
    """Backward-compatible: the UniDic folder for the default mode (lite)."""
    return unidic_dir("lite")


class Analyzer:
    """Thread-safe wrapper around one fugashi tagger + cutlet."""

    def __init__(self, word_checker: WordChecker | None = None, mode: str = "lite",
                 dicdir: str | None = None, userdic: str | None = None) -> None:
        """mode: "lite" or "full" UniDic; dicdir overrides the dictionary folder;
        userdic: a MeCab user dictionary built for that UniDic (Wiktionary nouns)."""
        import cutlet

        if mode not in ("lite", "full"):
            raise ValueError(f"Analyzer needs mode 'lite' or 'full', not {mode!r}")
        self.mode = mode
        self.userdic = userdic
        d = (dicdir or unidic_dir(mode)).replace("\\", "/")
        # Always pass the folder explicitly, so the chosen UniDic is used even when both
        # are installed.
        args = f'-d "{d}" -r "{d}/mecabrc"'
        if userdic:
            args += f' -u "{userdic.replace(chr(92), "/")}"'
        self._cutlet = cutlet.Cutlet(use_foreign_spelling=False, mecab_args=args)
        self._cutlet.use_wo = False  # を -> "o" (Hepburn)
        # cutlet drops the w/y in these loanword combinations (ウィスパー -> "isupaa")
        for kana, romaji in _MAPPING_FIXES.items():
            self._cutlet.update_mapping(kana, romaji)
        self._tagger = self._cutlet.tagger
        self._lock = threading.Lock()
        self.word_checker = word_checker

    # ---------- public ----------
    def analyze_line(self, text: str) -> list[Token]:
        with self._lock:
            words = list(self._tagger(text))
            fixed: set[int] = set()
            if self.word_checker is not None and len(words) > 1:
                words, fixed = self._check_boundaries(text, words)
            romaji = self._cutlet.romaji_tokens(words, capitalize=False)
        tokens = []
        gaps = []  # real whitespace in the text before the next word
        offset = 0
        for idx, (word, rom) in enumerate(zip(words, romaji, strict=True)):
            offset += len(word.white_space or "")
            tok = self._token(word, rom.surface.lower(), rom.space or bool(word.white_space))
            tok.start = offset
            tok.boundary_fixed = idx in fixed
            offset += len(word.surface)
            tokens.append(tok)
            nxt = words[idx + 1] if idx + 1 < len(words) else None
            gaps.append(bool(nxt is not None and nxt.white_space))
        tokens = self._merge_split_names(tokens, gaps)
        self._attach_grammar(tokens)
        return tokens

    def analyze(self, lines: list[str]) -> list[list[Token]]:
        return [self.analyze_line(line) for line in lines]

    # ---------- word-boundary check (JMdict) ----------
    @staticmethod
    def _spans(words) -> list[tuple[int, int]]:
        spans, pos = [], 0
        for w in words:
            pos += len(w.white_space or "")
            spans.append((pos, pos + len(w.surface)))
            pos += len(w.surface)
        return spans

    def _piece_ok(self, word) -> bool:
        """A piece of a new split must still be a real word."""
        if word.is_unk:
            return False
        if _clean(word.feature.pos1) in _GRAMMAR_POS | _NOT_WORDS:
            return True
        wc = self.word_checker
        return any(wc.is_word(k) for k in (word.surface, _clean(word.feature.orthBase),
                                          _clean_lemma(word.feature.lemma)) if k)

    def _is_common(self, word) -> bool:
        wc = self.word_checker
        return any(wc.is_common(k) for k in (word.surface, _clean(word.feature.orthBase)) if k)

    @staticmethod
    def _is_fragment(word, kana_only: bool) -> bool:
        """A piece that doesn't look like a word on its own: unknown, or a single character
        that is a prefix / suffix (old split) or a stray kana that isn't grammar (both)."""
        if word.is_unk:
            # unknown katakana is usually a loanword or name (テンプレ), not a broken split
            return not _is_katakana_word(word.surface)
        if len(word.surface) != 1:
            return False
        pos1 = _clean(word.feature.pos1)
        if pos1 in ("助詞", "助動詞") or pos1 in _NOT_WORDS:
            return False
        if kana_only:
            return is_all_kana(word.surface)
        return pos1 in ("接頭辞", "接尾辞") or is_all_kana(word.surface)

    def _region_better(self, old: list, new: list) -> bool:
        """(a) the new split has a common word of 2+ characters, (b) the old split has a
        content word of 2+ characters that isn't common, (c) every new piece is a word,
        (d) the old split looks broken (has a fragment: 火元 + 素, 大 + 陸中), and (e) the
        new split leaves no stray kana (おば + あ). (d) keeps real words like ほんと whole."""
        if not all(self._piece_ok(w) for w in new):
            return False
        if not any(self._is_fragment(w, kana_only=False) for w in old):
            return False
        if any(self._is_fragment(w, kana_only=True) for w in new):
            return False
        # Words that exist only in the extra (Wiktionary) list were added to the splitter on
        # purpose (じっちゃ); never split them back into pieces.
        is_extra = getattr(self.word_checker, "is_extra", None)
        if is_extra is not None and any(is_extra(w.surface) for w in old):
            return False
        new_common = any(len(w.surface) >= 2 and self._is_common(w) for w in new)
        old_rare = any(
            len(w.surface) >= 2 and _clean(w.feature.pos1) in _CONTENT_POS
            and not self._is_common(w)
            for w in old
        )
        return new_common and old_rare

    def _check_boundaries(self, text: str, best: list) -> tuple[list, set[int]]:
        try:
            alternatives = self._tagger.nbestToNodeList(text, _NBEST)
        except Exception:  # noqa: BLE001
            return best, set()
        best_spans = self._spans(best)
        result = list(zip(best_spans, best, strict=True))  # [(span, node)]
        changed: list[tuple[int, int]] = []
        seen = {tuple(w.surface for w in best)}
        for alt in alternatives:
            key = tuple(w.surface for w in alt)
            if key in seen:
                continue
            seen.add(key)
            alt_spans = self._spans(alt)
            if not alt_spans or alt_spans[-1][1] != best_spans[-1][1]:
                continue
            cur_bounds = {e for (_, e), _ in result}
            alt_bounds = {e for _, e in alt_spans}
            # walk regions between boundaries shared by both splits
            shared = sorted(cur_bounds & alt_bounds)
            prev = 0
            for end in shared:
                old = [(s, n) for s, n in result if s[0] >= prev and s[1] <= end]
                new = [(s, n) for s, n in zip(alt_spans, alt, strict=True)
                       if s[0] >= prev and s[1] <= end]
                region = (prev, end)
                if ([n.surface for _, n in old] != [n.surface for _, n in new]
                        and not any(r[0] < end and prev < r[1] for r in changed)
                        and self._region_better([n for _, n in old], [n for _, n in new])):
                    result = [x for x in result if not (x[0][0] >= prev and x[0][1] <= end)]
                    result += new
                    result.sort(key=lambda x: x[0][0])
                    changed.append(region)
                prev = end
        if not changed:
            return best, set()
        nodes = [n for _, n in result]
        fixed = {i for i, (s, _) in enumerate(result)
                 if any(r[0] <= s[0] and s[1] <= r[1] for r in changed)}
        return nodes, fixed

    # ---------- tokens ----------
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
        ctype, cform = _clean(f.cType), _clean(f.cForm)
        conj = f"{ctype} / {cform}" if ctype else None

        note = grammar.PARTICLE_NOTES.get(surface) if pos1 == "助詞" else None

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
            lemma=_clean_lemma(f.lemma),
            orth_base=base,
            word_class=grammar.word_class(ctype),
            form=grammar.form_label(cform),
        )

    def _merge_split_names(self, tokens: list[Token], gaps: list[bool]) -> list[Token]:
        """UniDic splits unknown katakana names into pieces (テララ -> テ + ララ,
        リリカ -> リリ + カ). Join a run of adjacent katakana tokens back into one word when
        the run contains a one-character piece or a grammar word, which real katakana
        compounds (スター + リンク) never do."""
        def fragment(t: Token) -> bool:
            # a one-letter piece, a grammar ending or "symbol" katakana is never a word here
            return len(t.surface) == 1 or t.pos in _GRAMMAR_POS or t.pos in _NOT_WORDS

        def joinable(a: Token, b: Token) -> bool:
            if fragment(a) or fragment(b):
                return True
            # an unknown piece joins short neighbours only, so real words like スター or
            # ホイール next to an unknown name (キボ) stay separate
            if not a.known:
                return len(b.surface) <= 2
            if not b.known:
                return len(a.surface) <= 2
            return False

        out: list[Token] = []
        i = 0
        while i < len(tokens):
            j = i + 1
            while (j < len(tokens) and _is_katakana_word(tokens[i].surface)
                   and _is_katakana_word(tokens[j].surface) and not gaps[j - 1]
                   and joinable(tokens[j - 1], tokens[j])):
                j += 1
            run = tokens[i:j]
            if len(run) >= 2:
                surface = "".join(t.surface for t in run)
                reading = to_hiragana(surface)
                with self._lock:
                    romaji = self._cutlet.map_kana(reading)
                out.append(Token(
                    surface=surface, reading=reading, romaji=romaji, pos="名詞",
                    pos_en="unknown word (maybe a name or game term)", base=None,
                    base_reading=None, conjugation=None, note=None,
                    furigana=[(surface, None)], clickable=True, known=False,
                    space_after=run[-1].space_after, start=run[0].start,
                ))
                i = j
            else:
                out.append(tokens[i])
                i += 1
        return out

    @staticmethod
    def _attach_grammar(tokens: list[Token]) -> None:
        """Group a verb / adjective with its endings and explain each part."""
        i = 0
        while i < len(tokens):
            head = tokens[i]
            if head.pos not in ("動詞", "形容詞") or head.word_class is None:
                i += 1
                continue
            head_label = head.word_class + (f", {head.form}" if head.form else "")
            if head.orth_base and head.orth_base != head.surface:
                head_label = f"{head.orth_base} — {head_label}"
            parts = [grammar.GrammarPart(head.surface, head_label)]
            j = i + 1
            after_te = False
            while j < len(tokens):
                t = tokens[j]
                label = None
                if t.pos == "助動詞":
                    label = grammar.aux_label(t.lemma, t.surface) or "auxiliary"
                elif t.pos == "助詞" and grammar.linking_label(t.surface):
                    label = grammar.linking_label(t.surface)
                elif t.pos == "動詞" and after_te:
                    label = grammar.te_helper_label(t.lemma, t.surface)
                elif t.pos == "形容詞" and t.lemma in ("無い", "ない") and len(parts) > 0:
                    label = "negative"
                if label is None:
                    break
                after_te = t.surface in ("て", "で")
                parts.append(grammar.GrammarPart(t.surface, label))
                j += 1
            if len(parts) > 1:
                phrase = "".join(p.surface for p in parts)
                for t in tokens[i:j]:
                    t.phrase = phrase
                    t.grammar = parts
            i = max(j, i + 1)


_shared: dict[tuple[str, bool], Analyzer] = {}
_shared_lock = threading.Lock()


def shared_analyzer(mode: str = "lite", use_dictionary: bool = True) -> Analyzer | None:
    """The app-wide analyzer for `mode` ("lite" / "full"), or None for "none".
    With use_dictionary, the JMdict dictionary (if its database exists) checks word
    boundaries. Raises DictionaryMissing when the chosen UniDic isn't installed."""
    if mode == "none":
        return None
    key = (mode, use_dictionary)
    with _shared_lock:
        if key not in _shared:
            checker, userdic = None, None
            if use_dictionary:
                try:
                    from jisho_lens.dictionary import shared_dictionary

                    checker = shared_dictionary()
                    userdic = user_dictionary_path(mode)
                except Exception:  # noqa: BLE001 (database missing: split without the check)
                    checker = None
            _shared[key] = Analyzer(word_checker=checker, mode=mode, userdic=userdic)
        return _shared[key]


def user_dictionary_path(mode: str) -> str | None:
    """Wiktionary nouns (such as じっちゃ) for the word splitter, built for one UniDic when
    the Wiktionary component is installed."""
    from jisho_lens.components import registry

    path = registry.user_dictionary_path(mode)
    return str(path) if registry.is_installed("wiktionary") and path.exists() else None


def reset_shared() -> None:
    """Forget the cached analyzers (and their MeCab files), e.g. before components change."""
    with _shared_lock:
        _shared.clear()
