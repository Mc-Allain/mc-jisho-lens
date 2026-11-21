"""Post-OCR cleanup (SPEC §3.1 OCR):

- key / mouse icon labels ([T], [Q], Esc, LSHIFT ...) are removed when they stand alone
  (their own line, or separated by spaces at the start/end of a line);
- the speaker name line above dialogue is split off.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jisho_lens.core.ocr.base import OcrLine

# A key label: 1-2 ASCII letters/digits, or a known key name.
_KEY_NAMES = (
    r"(?:[A-Z0-9]{1,2}|ESC|Esc|TAB|Tab|SPACE|Space|ENTER|Enter"
    r"|L-?SHIFT|R-?MOUSE|L-?MOUSE|Ctrl|CTRL|Shift|SHIFT|Alt|ALT)"
)
_KEY_ONLY = re.compile(rf"^\s*[\[\(]?{_KEY_NAMES}[\]\)]?\s*$")
_KEY_EDGE_START = re.compile(rf"^\s*[\[\(]?{_KEY_NAMES}[\]\)]?\s+(?=[^\x00-\x7F])")
_KEY_EDGE_END = re.compile(rf"(?<=[^\x00-\x7F])\s+[\[\(]?{_KEY_NAMES}[\]\)]?\s*$")

_SENTENCE_PUNCT = set("。、！？!?…「」『』（）()：:")
_MAX_SPEAKER_CHARS = 10


@dataclass
class CleanText:
    speaker: str | None
    lines: list[str]

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def strip_key_icons(lines: list[str]) -> list[str]:
    out = []
    for line in lines:
        if _KEY_ONLY.match(line):
            continue
        line = _KEY_EDGE_START.sub("", line)
        line = _KEY_EDGE_END.sub("", line)
        if line.strip():
            out.append(line.strip())
    return out


def _center_x(line: OcrLine) -> float | None:
    return None if line.box is None else (line.box[0] + line.box[2]) / 2


def find_speaker(lines: list[OcrLine]) -> int | None:
    """Index of the speaker line, or None.

    The speaker is the first line when: it is short, has no sentence punctuation or digits,
    at least one longer line follows, and (if boxes are known) it is horizontally centred
    over the lines below it, like the game's dialogue layout.
    """
    if len(lines) < 2:
        return None
    first = lines[0].text.strip()
    rest = [ln for ln in lines[1:] if ln.text.strip()]
    if not first or not rest or len(first) > _MAX_SPEAKER_CHARS:
        return None
    if any(ch in _SENTENCE_PUNCT or ch.isdigit() for ch in first):
        return None
    # Dialogue lines are clearly longer than a name; this keeps "確認 / キャンセル" etc. out.
    # Trade-off: a one-word reply like "はっ！" keeps its speaker inside the text.
    if max(len(ln.text.strip()) for ln in rest) < max(8, 2 * len(first)):
        return None
    c0 = _center_x(lines[0])
    centers = [c for c in (_center_x(ln) for ln in rest) if c is not None]
    if c0 is not None and centers:
        widths = [ln.box[2] - ln.box[0] for ln in rest if ln.box is not None]
        body_center = sum(centers) / len(centers)
        if abs(c0 - body_center) > 0.15 * max(widths):
            return None
    return 0


def clean(lines: list[OcrLine], remove_key_icons: bool = True, detect_speaker: bool = True
          ) -> CleanText:
    speaker = None
    if detect_speaker and (idx := find_speaker(lines)) is not None:
        speaker = lines[idx].text.strip()
        lines = lines[:idx] + lines[idx + 1:]
    texts = [ln.text.strip() for ln in lines if ln.text.strip()]
    if remove_key_icons:
        texts = strip_key_icons(texts)
    return CleanText(speaker=speaker, lines=texts)
