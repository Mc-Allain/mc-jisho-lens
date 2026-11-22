"""Remember my corrections: learn small OCR fixes from Edit and apply them to later captures.

When the user edits a capture, each changed piece is stored together with the characters
around it, e.g. 「うた、」→「うだ、」 or 「るそ。」→「るぞ。」. The surrounding characters keep a
rule specific: it fixes 「そうた、」 but leaves every other た alone. Later captures get the
same fix wherever the exact wrong piece shows up again.

Only used while OCR data collection is on. Stored in <data dir>/ocr-data/corrections.json on
this computer.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path

from jisho_lens.core import paths

LINE = "\n"  # line boundary; may appear in a rule as context ("start/end of a line")
CONTEXT = 1  # characters kept on each side of a change
MIN_WRONG = 3  # a rule's wrong piece is at least this long (without line marks)
MAX_CHANGE = 6  # longer rewrites aren't OCR misreads; they're not learned
MERGE_GAP = 2  # changes this close together become one rule


@dataclass
class Correction:
    wrong: str  # text as OCR reads it, with context; LINE marks a line start/end
    right: str
    count: int = 1  # times learned
    used: int = 0  # times applied
    created: str = ""
    last_used: str = ""

    @property
    def label(self) -> str:
        def show(s: str) -> str:
            return s.replace(LINE, "⏎")

        return f"{show(self.wrong)} → {show(self.right)}"


@dataclass
class Applied:
    lines: list[str]
    used: list[Correction]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _wrap(lines: list[str]) -> str:
    return LINE + LINE.join(lines) + LINE


def _unwrap(text: str) -> list[str]:
    return [ln for ln in text.split(LINE) if ln.strip()]


def _solid(s: str) -> int:
    return len(s.replace(LINE, ""))


def learn_rules(before: list[str], after: list[str]) -> list[tuple[str, str]]:
    """(wrong, right) pairs with context for each small change from before to after."""
    a, b = _wrap(before), _wrap(after)
    ops = [op for op in SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
           if op[0] != "equal"]
    # join changes that are close together
    groups: list[list[int]] = []
    for _tag, i1, i2, j1, j2 in ops:
        if groups and i1 - groups[-1][1] <= MERGE_GAP and LINE not in a[groups[-1][1]:i1]:
            groups[-1][1], groups[-1][3] = i2, j2
        else:
            groups.append([i1, i2, j1, j2])
    rules = []
    for i1, i2, j1, j2 in groups:
        if i2 - i1 > MAX_CHANGE or j2 - j1 > MAX_CHANGE:
            continue
        if LINE in a[i1:i2] or LINE in b[j1:j2]:
            continue  # lines joined or split: not an OCR misread
        left = right = CONTEXT
        while True:
            wrong = a[max(0, i1 - left):i2 + right]
            if _solid(wrong) >= MIN_WRONG:
                break
            # widen on a side that hasn't reached the line boundary yet
            can_left = i1 - left > 0 and a[i1 - left] != LINE
            can_right = i2 + right < len(a) and a[i2 + right - 1] != LINE
            if can_left:
                left += 1
            elif can_right:
                right += 1
            else:
                break
        lo, hi = max(0, i1 - left), min(len(a), i2 + right)
        wrong = a[lo:hi]
        fixed = a[lo:i1] + b[j1:j2] + a[i2:hi]
        if _solid(wrong) < MIN_WRONG or wrong == fixed:
            continue
        rules.append((wrong, fixed))
    return rules


def apply_rules(lines: list[str], rules: list[Correction]) -> Applied:
    """Apply rules in one left-to-right pass (longest match first, no chaining)."""
    if not rules or not lines:
        return Applied(list(lines), [])
    by_len = sorted(rules, key=lambda r: len(r.wrong), reverse=True)
    text = _wrap(lines)
    out, used, i = [], [], 0
    while i < len(text):
        for rule in by_len:
            if text.startswith(rule.wrong, i):
                # a rule ending in a line mark leaves it in place for the next rule
                out.append(rule.right[:-1] if rule.right.endswith(LINE) and
                           rule.wrong.endswith(LINE) else rule.right)
                i += len(rule.wrong) - (1 if rule.wrong.endswith(LINE) else 0)
                if rule not in used:
                    used.append(rule)
                break
        else:
            out.append(text[i])
            i += 1
    return Applied(_unwrap("".join(out)), used)


class CorrectionStore:
    def __init__(self, folder: Path | None = None) -> None:
        self.path = (folder or (paths.data_dir() / "ocr-data")) / "corrections.json"
        self._lock = threading.Lock()
        self._rules: list[Correction] | None = None

    # ---------- storage ----------
    def all(self) -> list[Correction]:
        if self._rules is None:
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._rules = [Correction(**r) for r in data.get("rules", [])]
            except (OSError, ValueError, TypeError):
                self._rules = []
        return list(self._rules)

    def _save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"format": 1, "rules": [asdict(r) for r in self._rules or []]}
            self.path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                                 encoding="utf-8")

    def _find(self, wrong: str) -> Correction | None:
        return next((r for r in self.all() if r.wrong == wrong), None)

    # ---------- use ----------
    def apply(self, lines: list[str]) -> Applied:
        result = apply_rules(lines, self.all())
        if result.used:
            for rule in result.used:
                rule.used += 1
                rule.last_used = _now()
            self._save()
        return result

    def learn(self, before: list[str], after: list[str],
              applied: list[Correction] | None = None) -> int:
        """Learn from an edit. Returns the number of new or changed rules.

        `applied` are the rules used on this text; one the user undid (its wrong piece is
        back in the edited text) is forgotten.
        """
        self.all()
        changed = 0
        edited = _wrap(after)
        undone = []
        for rule in applied or []:
            if rule.wrong in edited and rule.right not in edited:
                self._rules = [r for r in self._rules if r.wrong != rule.wrong]
                undone.append(rule)
                changed += 1
        for wrong, right in learn_rules(before, after):
            if any((wrong in u.right or u.right in wrong) and (right in u.wrong or u.wrong in right)
                   for u in undone):
                continue  # putting the OCR text back is not a new correction
            rule = self._find(wrong)
            if rule is None:
                self._rules.append(Correction(wrong, right, created=_now()))
            elif rule.right != right:
                rule.right, rule.count = right, 1  # the newest answer wins
            else:
                rule.count += 1
            changed += 1
        if changed:
            self._save()
        return changed

    def learn_from_samples(self, samples) -> int:
        """Learn from collected samples the user corrected with Edit; always saves the file."""
        self.all()
        n = 0
        for s in samples:
            if s.truth_source == "edited" and s.truth:
                n += self.learn(s.ocr_text.splitlines(), s.truth.splitlines())
        self._save()
        return n

    def forget(self,applied: list[Correction], text_lines: list[str]) -> int:
        """Drop applied rules whose original OCR piece the user kept (e.g. ✓ after Undo)."""
        self.all()
        text = _wrap(text_lines)
        gone = [r.wrong for r in applied if r.wrong in text and r.right not in text]
        if gone:
            self._rules = [r for r in self._rules if r.wrong not in gone]
            self._save()
        return len(gone)

    def delete(self, wrong: str) -> None:
        self.all()
        self._rules = [r for r in self._rules if r.wrong != wrong]
        self._save()

    def delete_all(self) -> None:
        self._rules = []
        with self._lock:
            self.path.unlink(missing_ok=True)
