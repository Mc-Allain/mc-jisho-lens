"""Compare UniDic-lite and full UniDic on game lines, both with the JMdict checks.

Run:  uv run python tools/components.py install unidic-lite unidic-full jmdict wiktionary
      uv run python -X utf8 tools/compare_unidic.py LINES.txt

LINES.txt: one Japanese line per line. Prints a summary and every line where the two
dictionaries split or read words differently, for manual judgement.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jisho_lens.core.analysis import Analyzer  # noqa: E402
from jisho_lens.dictionary import Dictionary  # noqa: E402
from jisho_lens.dictionary.enrich import enrich  # noqa: E402


def stats(name: str, an: Analyzer, d: Dictionary, lines: list[str]) -> tuple[dict, list]:
    s = {"words": 0, "unknown": 0, "no_meaning": 0, "fixed": 0, "compound": 0}
    shown = []
    toks = an.analyze(lines)
    page = enrich(d, lines, toks)
    flat = [t for line in toks for t in line]
    for t, w in zip(flat, page.words, strict=True):
        if not t.clickable:
            continue
        s["words"] += 1
        s["unknown"] += not t.known
        s["no_meaning"] += not w.get("entries")
        s["fixed"] += t.boundary_fixed
        s["compound"] += "compound" in w
    for line_toks in toks:
        shown.append(" ".join(
            t.surface + (f"[{t.reading}]" if t.reading and t.reading != t.surface
                         and any("一" <= c <= "鿿" for c in t.surface) else "")
            for t in line_toks if t.surface.strip()))
    return s, shown


def main() -> int:
    lines = [ln.strip() for ln in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    d = Dictionary()
    lite = Analyzer(word_checker=d, mode="lite")
    full = Analyzer(word_checker=d, mode="full")
    s_lite, out_lite = stats("lite", lite, d, lines)
    s_full, out_full = stats("full", full, d, lines)
    print(f"{len(lines)} lines\n")
    print(f"{'':28s}{'lite':>8s}{'full':>8s}")
    labels = {"words": "clickable words", "unknown": "unknown to UniDic",
              "no_meaning": "no JMdict meaning found", "fixed": "split fixed by JMdict check",
              "compound": "coined-compound guesses"}
    for k, label in labels.items():
        print(f"{label:28s}{s_lite[k]:>8d}{s_full[k]:>8d}")
    diffs = [(a, b) for a, b in zip(out_lite, out_full, strict=True) if a != b]
    print(f"\n{len(diffs)} lines differ:\n")
    for a, b in diffs:
        print(f"  lite: {a}\n  full: {b}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
