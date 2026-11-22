"""OCR data from the command line (same as History → OCR data in the app).

  uv run python tools/ocr_data.py                         # stats
  uv run python tools/ocr_data.py export PACK.zip [--all] [--game NAME]
  uv run python tools/ocr_data.py import PACK.zip
  uv run python tools/ocr_data.py merge OUT.zip PACK1.zip PACK2.zip [...]
  uv run python tools/ocr_data.py testset FOLDER [--game NAME]   # then: tools/ocr_bench.py FOLDER

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
    OcrDataStore,
    PackError,
    export_pack,
    import_pack,
    merge_packs,
    select,
    to_test_set,
)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    e = sub.add_parser("export")
    e.add_argument("pack")
    e.add_argument("--all", action="store_true", help="include unchecked samples")
    e.add_argument("--game")
    i = sub.add_parser("import")
    i.add_argument("pack")
    m = sub.add_parser("merge")
    m.add_argument("out")
    m.add_argument("packs", nargs="+")
    t = sub.add_parser("testset")
    t.add_argument("folder")
    t.add_argument("--game")
    args = ap.parse_args(argv)

    store = OcrDataStore()
    try:
        if args.cmd == "export":
            n = export_pack(store, Path(args.pack),
                            select(store, "all" if args.all else "checked", args.game))
            print(f"exported {n} samples to {args.pack}")
        elif args.cmd == "import":
            print(import_pack(store, Path(args.pack)).summary())
        elif args.cmd == "merge":
            if len(args.packs) < 2:
                print("give two or more packs to merge")
                return 2
            count, result = merge_packs([Path(p) for p in args.packs], Path(args.out))
            print(f"merged pack with {count} samples -> {args.out}\n{result.summary()}")
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
