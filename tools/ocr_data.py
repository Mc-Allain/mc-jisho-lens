"""OCR data from the command line (same as History → OCR data in the app).

  uv run python tools/ocr_data.py                         # stats
  uv run python tools/ocr_data.py export PACK.zip [--game NAME]
  uv run python tools/ocr_data.py import PACK.zip [--different keep|theirs|alternative]
                                                  [--same-sentence] [--learn] [--dry-run]
  uv run python tools/ocr_data.py merge OUT.zip PACK1.zip PACK2.zip [...] [--same-sentence]
  uv run python tools/ocr_data.py testset FOLDER [--game NAME]   # then: tools/ocr_bench.py FOLDER

Packs contain only samples fixed with Edit (OCR read the others right, or they were never
checked). The app's review window lets you choose per sample; here the choices apply to
all: a different answer for an image you have is kept as yours by default, and another crop
of a sentence you already have is skipped unless --same-sentence.

Collected data only exists if you allowed collection in the app (off by default) or
imported packs. It stays on this computer unless you share an exported pack yourself.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jisho_lens.core.ocr_data import (  # noqa: E402
    DIFFERS,
    KEEP_ALTERNATIVE,
    KEEP_MINE,
    SAME_SENTENCE,
    STATUS_LABELS,
    USE_THEIRS,
    OcrDataStore,
    PackError,
    apply_import,
    apply_merge,
    export_pack,
    read_pack,
    review_import,
    review_merge,
    select,
    to_test_set,
)
from jisho_lens.core.ocr_data.corrections import CorrectionStore  # noqa: E402

CHOICES = {"keep": KEEP_MINE, "theirs": USE_THEIRS, "alternative": KEEP_ALTERNATIVE}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    e = sub.add_parser("export")
    e.add_argument("pack")
    e.add_argument("--game")
    i = sub.add_parser("import")
    i.add_argument("pack")
    i.add_argument("--different", choices=list(CHOICES), default="keep",
                   help="an image you have with a different answer: keep yours (default), "
                        "use theirs (yours kept as alternative), or keep theirs as alternative")
    i.add_argument("--same-sentence", action="store_true",
                   help="also import other crops of sentences you already have")
    i.add_argument("--learn", action="store_true",
                   help="also learn OCR fixes from the imported answers")
    i.add_argument("--dry-run", action="store_true", help="only show what would happen")
    m = sub.add_parser("merge")
    m.add_argument("out")
    m.add_argument("packs", nargs="+")
    m.add_argument("--same-sentence", action="store_true",
                   help="keep other crops of the same sentence")
    t = sub.add_parser("testset")
    t.add_argument("folder")
    t.add_argument("--game")
    args = ap.parse_args(argv)

    store = OcrDataStore()
    try:
        if args.cmd == "export":
            n = export_pack(store, Path(args.pack), select(store, args.game))
            print(f"exported {n} samples fixed with Edit to {args.pack}")
        elif args.cmd == "import":
            pack = read_pack(Path(args.pack))
            rows = review_import(store, pack)
            for row in rows:
                if row.status == DIFFERS:
                    row.choice = CHOICES[args.different]
                if row.status == SAME_SENTENCE and args.same_sentence:
                    row.include = True
            counts = {s: sum(r.status == s for r in rows) for s in STATUS_LABELS}
            print(", ".join(f"{STATUS_LABELS[s]}: {n}" for s, n in counts.items() if n)
                  + (f"; {pack.skipped} without an Edit fix left out" if pack.skipped else ""))
            if args.dry_run:
                return 0
            learn = CorrectionStore() if args.learn else None
            print(apply_import(store, rows, learn).summary())
        elif args.cmd == "merge":
            if len(args.packs) < 2:
                print("give two or more packs to merge")
                return 2
            packs = [read_pack(Path(p)) for p in args.packs]
            rows = review_merge(packs)
            for row in rows:
                if row.status == SAME_SENTENCE and args.same_sentence:
                    row.include = True
            count = apply_merge(rows, Path(args.out), store.contributor())
            differs = sum(r.status == DIFFERS and r.include for r in rows)
            print(f"merged pack with {count} samples -> {args.out} ({differs} with answers "
                  "that differ, kept side by side)")
        elif args.cmd == "testset":
            n = to_test_set(store, Path(args.folder), args.game)
            print(f"wrote {n} checked samples to {args.folder}\n"
                  f'run: uv run python tools/ocr_bench.py "{args.folder}"')
    except PackError as exc:
        print(f"error: {exc}")
        return 1
    st = store.stats()
    print(f"\nlocal OCR data ({store.folder}): {st['samples']} samples, {st['checked']} checked "
          f"({st['edited']} edited, {st['confirmed']} ✓), {st['needs_review']} need review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
