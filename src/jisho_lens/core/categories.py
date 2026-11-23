"""Category labels for OCR data (set when exporting or merging packs)."""

from __future__ import annotations

DEFAULT_CATEGORIES = ("Azur Promilia JP",)
MAX_CATEGORY = 40


def clean_category(name: str) -> str:
    return " ".join(str(name or "").split())[:MAX_CATEGORY]


def category_suggestions(*more: str) -> list[str]:
    """Default categories first, then `more` (categories in your data or the packs), each
    once (ignoring case); blank names dropped."""
    out: list[str] = []
    for name in (*DEFAULT_CATEGORIES, *more):
        name = clean_category(name)
        if name and all(name.lower() != o.lower() for o in out):
            out.append(name)
    return out


def category_summary(categories) -> str:
    """'Categories: Azur Promilia JP 40, none 3' (for the history log and the footer)."""
    counts: dict[str, int] = {}
    for name in categories:
        key = clean_category(name) or "none"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    order = sorted(counts, key=lambda k: (k == "none", -counts[k], k.lower()))
    return "Categories: " + ", ".join(f"{k} {counts[k]}" for k in order)
