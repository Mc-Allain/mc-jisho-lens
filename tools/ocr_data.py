"""OCR data from the command line (same as History → OCR data in the app).

  uv run python tools/ocr_data.py                         # stats
  uv run python tools/ocr_data.py export [PACK.zip] [--name NAME] [--category CAT] [--only CAT]
  uv run python tools/ocr_data.py import PACK.zip [--different keep|theirs|alternative]
                                                  [--same-sentence] [--learn] [--dry-run]
  uv run python tools/ocr_data.py merge [--out OUT.zip] [--name NAME] PACK1.zip PACK2.zip [...]
                                                  [--same-sentence] [--category CAT] [--only CAT]
  uv run python tools/ocr_data.py testset FOLDER   # then: tools/ocr_bench.py FOLDER

Exports and merges are releases of your pack NAME (e.g. RavenOCR): each one gets the next
version (RavenOCR v1, v2, ...) and a history log. NAME defaults to your last one; the file
defaults to NAME-vN.zip.

Categories label samples (e.g. "Azur Promilia JP"; blank = none). --category CAT labels
every exported sample with CAT (for merge: the samples without one); --only CAT keeps only
that category ("none" = samples without one).

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

from jisho_lens.core.categories import clean_category  # noqa: E402
from jisho_lens.core.ocr_data import (  # noqa: E402  # noqa: E402
    DIFFERS,
    KEEP_ALTERNATIVE,
    KEEP_MINE,
    SAME_SENTENCE,
    STATUS_LABELS,
    USE_THEIRS,
    OcrDataStore,
    PackError,
    apply_export,
    apply_import,
    apply_merge,
    label_rows,
    read_pack,
    review_export,
    review_import,
    review_merge,
    to_test_set,
    unique_packs,
)
from jisho_lens.core.ocr_data.corrections import CorrectionStore  # noqa: E402
from jisho_lens.core.ocr_data.packs import merge_sources, preview_import_label  # noqa: E402
from jisho_lens.core.ocr_data.provenance import clean_name, file_name  # noqa: E402

CHOICES = {"keep": KEEP_MINE, "theirs": USE_THEIRS, "alternative": KEEP_ALTERNATIVE}


def _only(rows, category: str | None) -> None:
    """--only: untick rows of other categories ("none": keep rows without a category)."""
    if category is None:
        return
    want = "" if category.lower() == "none" else clean_category(category).lower()
    for row in rows:
        if row.category.lower() != want:
            row.include = False


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    e = sub.add_parser("export")
    e.add_argument("pack", nargs="?")
    e.add_argument("--name", help="your pack name (default: your last one)")
    e.add_argument("--category", help="label every exported sample with this category")
    e.add_argument("--only", help='export only this category ("none": without one)')
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
    m.add_argument("packs", nargs="+")
    m.add_argument("--out")
    m.add_argument("--name", help="your pack name (default: your last one)")
    m.add_argument("--category", help="label samples without a category with this one")
    m.add_argument("--only", help='keep only this category ("none": without one)')
    m.add_argument("--same-sentence", action="store_true",
                   help="keep other crops of the same sentence")
    t = sub.add_parser("testset")
    t.add_argument("folder")
    args = ap.parse_args(argv)

    store = OcrDataStore()
    try:
        if args.cmd == "export":
            name = clean_name(args.name or store.provenance.last_name())
            if not name:
                print("give your pack a name: --name RavenOCR")
                return 2
            version = store.provenance.next_version(name)
            out = Path(args.pack or file_name(name, version))
            rows = review_export(store)
            if args.category is not None:
                label_rows(rows, clean_category(args.category), only=rows)
            _only(rows, args.only)
            n = apply_export(store, rows, out, name)
            print(f"exported {name} v{version}: {n} samples fixed with Edit -> {out}")
        elif args.cmd == "import":
            pack = read_pack(Path(args.pack))
            print(f"{pack.label}" + (f" by {pack.info.contributor[:8]}" if pack.info else "")
                  + "\n" + (pack.info.history_text() if pack.info else ""))
            rows = review_import(store, pack)
            for row in rows:
                if row.status == DIFFERS:
                    row.choice = CHOICES[args.different]
                if row.status == SAME_SENTENCE and args.same_sentence:
                    row.include = True
            counts = {s: sum(r.status == s for r in rows) for s in STATUS_LABELS}
            print(", ".join(f"{STATUS_LABELS[s]}: {n}" for s, n in counts.items() if n)
                  + (f"; {pack.skipped} without an Edit fix left out" if pack.skipped else ""))
            now, after = preview_import_label(store, rows)
            print(f"using now: {now} -> after import: {after}")
            if args.dry_run:
                return 0
            learn = CorrectionStore() if args.learn else None
            print(apply_import(store, rows, learn).summary())
        elif args.cmd == "merge":
            if len(args.packs) < 2:
                print("give two or more packs to merge")
                return 2
            name = clean_name(args.name or store.provenance.last_name())
            if not name:
                print("give your pack a name: --name RavenOCR")
                return 2
            packs, dropped = unique_packs([read_pack(Path(p)) for p in args.packs])
            if dropped:
                print(f"the same pack was given more than once; left out: {', '.join(dropped)}")
            if len(packs) < 2:
                print("give two or more different packs to merge")
                return 2
            rows = review_merge(packs)
            for row in rows:
                if row.status == SAME_SENTENCE and args.same_sentence:
                    row.include = True
            if args.category:
                label_rows(rows, clean_category(args.category),
                           only=[r for r in rows if not r.category])
            _only(rows, args.only)
            version = store.provenance.next_version(name)
            out = Path(args.out or file_name(name, version))
            count = apply_merge(rows, out, store.contributor(), name, store)
            differs = sum(r.status == DIFFERS and r.include for r in rows)
            print(f"merged {name} v{version}: {count} samples -> {out} (from "
                  f"{merge_sources(rows)}; {differs} with answers that differ, kept side by "
                  "side)")
        elif args.cmd == "testset":
            n = to_test_set(store, Path(args.folder))
            print(f"wrote {n} checked samples to {args.folder}\n"
                  f'run: uv run python tools/ocr_bench.py "{args.folder}"')
    except PackError as exc:
        print(f"error: {exc}")
        return 1
    st = store.stats()
    print(f"\nusing: {store.using()[0]}")
    print(f"local OCR data ({store.folder}): {st['samples']} samples, {st['checked']} checked "
          f"({st['edited']} edited, {st['confirmed']} ✓), {st['needs_review']} need review")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
