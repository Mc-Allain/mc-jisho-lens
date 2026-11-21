"""Phase 0 OCR benchmark: engines x preprocessing presets over a labelled image set.

Run:
  uv run python tools/ocr_bench.py [IMAGE_DIR] [--engines a,b] [--presets a,b]

IMAGE_DIR (default tests/ocr_set/images) holds <category>__<name>.png files, each with a
<category>__<name>.txt next to it containing the correct text. Results are printed and
written to tools/out/ocr-bench-<time>.md.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jisho_lens.core.ocr import ENGINE_NAMES, create_engine  # noqa: E402
from jisho_lens.core.ocr.metrics import char_accuracy  # noqa: E402
from jisho_lens.core.ocr.preprocess import PRESETS, apply  # noqa: E402

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def load_set(folder: Path) -> list[tuple[str, Path, str]]:
    items = []
    for img in sorted(folder.iterdir()):
        if img.suffix.lower() not in IMAGE_EXT:
            continue
        truth_file = img.with_suffix(".txt")
        if not truth_file.exists():
            print(f"skip (no .txt): {img.name}")
            continue
        category = img.stem.split("__", 1)[0] if "__" in img.stem else "uncategorized"
        items.append((category, img, truth_file.read_text(encoding="utf-8")))
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default=str(ROOT / "tests" / "ocr_set" / "images"))
    ap.add_argument("--engines", default=",".join(ENGINE_NAMES))
    ap.add_argument("--presets", default=",".join(PRESETS))
    ap.add_argument("--show-errors", action="store_true", help="print each wrong result")
    args = ap.parse_args()

    folder = Path(args.folder)
    items = load_set(folder)
    if not items:
        print(f"No labelled images in {folder}")
        return 1
    engines = [e for e in args.engines.split(",") if e]
    presets = [p for p in args.presets.split(",") if p]
    categories = sorted({c for c, _, _ in items})

    # acc[(engine, preset)][category] -> list of accuracies; secs[(engine, preset)] -> times
    acc: dict = defaultdict(lambda: defaultdict(list))
    secs: dict = defaultdict(list)
    images = {p: Image.open(p).convert("RGB") for _, p, _ in items}

    for name in engines:
        try:
            t0 = time.perf_counter()
            engine = create_engine(name)
            print(f"[{name}] loaded in {time.perf_counter() - t0:.1f}s")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] unavailable: {exc}")
            continue
        engine.recognize(next(iter(images.values())))  # warm-up
        for preset in presets:
            for category, path, truth in items:
                prepared = apply(images[path], preset)
                t0 = time.perf_counter()
                result = engine.recognize(prepared)
                secs[(name, preset)].append(time.perf_counter() - t0)
                a = char_accuracy(result.text, truth)
                acc[(name, preset)][category].append(a)
                if args.show_errors and a < 1.0:
                    print(f"  {name}/{preset} {path.name} {a:.0%}\n    got:  {result.text!r}"
                          f"\n    want: {truth!r}")

    header = "| engine | preset | " + " | ".join(categories) + " | all | ms/img |"
    sep = "|" + "---|" * (len(categories) + 4)
    rows = []
    for (name, preset), per_cat in acc.items():
        cells = []
        all_vals = []
        for c in categories:
            vals = per_cat.get(c, [])
            all_vals += vals
            cells.append(f"{sum(vals) / len(vals):.1%}" if vals else "-")
        avg = sum(all_vals) / len(all_vals)
        ms = 1000 * sum(secs[(name, preset)]) / len(secs[(name, preset)])
        row = f"| {name} | {preset} | " + " | ".join(cells) + f" | {avg:.1%} | {ms:.0f} |"
        rows.append((avg, row))
    rows.sort(key=lambda r: -r[0])
    table = "\n".join([header, sep] + [r for _, r in rows])
    counts = ", ".join(f"{c}: {sum(1 for x, _, _ in items if x == c)}" for c in categories)
    report = (
        f"# OCR benchmark\n\nSet: `{folder}` ({len(items)} images; {counts})\n\n"
        f"Character accuracy (1 - CER) per category, sorted by overall accuracy.\n\n{table}\n"
    )
    print("\n" + report)
    out = ROOT / "tools" / "out"
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"ocr-bench-{time.strftime('%Y%m%d-%H%M%S')}.md"
    path.write_text(report, encoding="utf-8")
    print(f"Saved {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
