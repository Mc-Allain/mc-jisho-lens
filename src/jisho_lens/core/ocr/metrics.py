"""OCR accuracy metrics."""

from __future__ import annotations

import unicodedata


def normalize(text: str) -> str:
    """NFKC (full-width ASCII -> half-width etc.) and drop all whitespace."""
    text = unicodedata.normalize("NFKC", text)
    return "".join(ch for ch in text if not ch.isspace())


def levenshtein(a: str, b: str) -> int:
    if len(a) < len(b):
        a, b = b, a
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def char_accuracy(predicted: str, truth: str) -> float:
    """1 - CER, clamped to [0, 1], after normalization. Empty truth -> 1.0 if prediction empty."""
    p, t = normalize(predicted), normalize(truth)
    if not t:
        return 1.0 if not p else 0.0
    return max(0.0, 1.0 - levenshtein(p, t) / len(t))
