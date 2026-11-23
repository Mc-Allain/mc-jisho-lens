"""OCR data packs: export, import and merge corrected samples as one .zip file.

Sharing is manual: a user exports a pack and sends it to someone, who imports it. A pack
contains only samples the user **fixed with Edit** (OCR got it wrong and the user typed the
right text); samples OCR read right (✓) or never checked stay on the computer:
  manifest.json              format, app version, counts, anonymous contributor ID
  samples/<sha256>.png       screenshot crops
  samples/<sha256>.json      sample metadata (see store.Sample)

Import and merge are two steps, so the user can review them first (ui/pack_review.py):
  read_pack()                     validate a pack; nothing is written
  review_import() / review_merge()  one ReviewRow per image: status, before / after
  apply_import() / apply_merge()  write only the rows the user kept, as they chose
import_pack() and merge_packs() do both steps with the default choices (command line).
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image

from jisho_lens import __version__
from jisho_lens.core.ocr_data.provenance import (
    LogEntry,
    PackInfo,
    clean_name,
    merge_logs,
)
from jisho_lens.core.ocr_data.store import FORMAT, OcrDataStore, Sample, _key, sample_id

PACK_FORMAT = "jisho-lens-ocr-pack"
_NAME = re.compile(r"^(manifest\.json|samples/[0-9a-f]{64}\.(png|json))$")
MAX_FILE = 20 * 1024 * 1024  # per file, uncompressed
MAX_TOTAL = 2 * 1024 * 1024 * 1024  # whole pack, uncompressed
MAX_FILES = 200_000
MAX_PIXELS = 8000 * 8000

# row status
NEW = "new"  # an image you don't have (or have without a right answer)
SAME = "same"  # you already have this image with the same answer: nothing to do
DIFFERS = "differs"  # same image, a different right answer
SAME_SENTENCE = "same_sentence"  # another crop of a sentence you already have
STATUS_LABELS = {NEW: "New", SAME: "Same", DIFFERS: "Different answer",
                 SAME_SENTENCE: "Same sentence"}

# what to do with a "differs" row
KEEP_MINE, USE_THEIRS, KEEP_ALTERNATIVE = "mine", "theirs", "alternative"
ALL_ANSWERS = -1  # merge: keep every pack's answer (first as the answer, others alternatives)


class PackError(ValueError):
    pass


def is_shareable(sample: Sample) -> bool:
    """Only samples fixed with Edit go into packs (OCR read the others right, or they were
    never checked)."""
    return sample.truth is not None and sample.truth_source == "edited"


# ---------------------------------------------------------------- export
def select(store: OcrDataStore) -> list[Sample]:
    """Samples for a pack: the ones fixed with Edit."""
    return [s for s in store.all() if is_shareable(s)]


def checked(store: OcrDataStore) -> list[Sample]:
    """Every sample with a right answer (edited or ✓), for the local OCR test set."""
    return [s for s in store.all() if s.checked]


def release_entry(store: OcrDataStore, name: str, action: str, sources: str,
                  samples: list[Sample]) -> LogEntry:
    """The history-log line of a new release of your pack `name` (next version)."""
    from jisho_lens.core.categories import category_summary

    name = clean_name(name)
    return LogEntry(name=name, version=store.provenance.next_version(name),
                    date=time.strftime("%Y-%m-%dT%H:%M:%S"), contributor=store.contributor(),
                    action=action, sources=sources, samples=len(samples),
                    categories=category_summary(s.category for s in samples))


def export_pack(store: OcrDataStore, path: Path, samples: list[Sample],
                name: str | None = None, *, release: LogEntry | None = None,
                log: list[LogEntry] | None = None) -> int:
    """Write a pack. Samples not fixed with Edit are left out.

    With `name`: the pack is the next version of your pack of that name; its history log
    has this release, your earlier releases and the logs of the packs your data uses
    (`release` / `log` are given by apply_merge instead)."""
    samples = [s for s in samples if is_shareable(s)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if name and release is None:
        label, _uses, _own = store.using()
        release = release_entry(store, name, "exported", label, samples)
        ids = {s.id for s in store.all()}
        log = merge_logs([release], store.provenance.series_log(release.name),
                         store.provenance.used_logs(ids))
    manifest = {
        "format": PACK_FORMAT,
        "version": FORMAT,
        "app_version": __version__,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "contributor": store.contributor(),
        "samples": len(samples),
        "pack_id": uuid.uuid4().hex,
    }
    if release is not None:
        manifest.update(name=release.name, series_version=release.version,
                        sources=release.sources,
                        log=[e.__dict__ for e in (log or [release])])
    tmp = path.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=1))
        for s in samples:
            zf.write(store.png_path(s.id), f"samples/{s.id}.png")
            zf.writestr(f"samples/{s.id}.json", s.to_json())
    tmp.replace(path)
    if release is not None:
        store.provenance.record_release(release)
    return len(samples)


# ---------------------------------------------------------------- read (nothing written)
@dataclass
class Pack:
    path: Path
    manifest: dict
    samples: dict[str, Sample]  # only samples fixed with Edit
    sizes: dict[str, int]  # PNG size per sample id
    skipped: int = 0  # samples without an Edit fix (not offered)
    info: PackInfo | None = None  # name, version, history log

    @property
    def label(self) -> str:
        return self.info.label if self.info else self.path.stem

    @property
    def name(self) -> str:
        return self.path.name

    def image(self, sid: str) -> bytes:
        """The PNG of a sample, checked again against its name."""
        with zipfile.ZipFile(self.path) as zf:
            data = zf.read(f"samples/{sid}.png")
        if sample_id(data) != sid:
            raise PackError(f"image changed since it was checked: {sid}")
        return data


def read_pack(path: Path) -> Pack:
    """Validate a pack (names, sizes, images match their hash, JSON shape). Raises
    PackError. Nothing is written; images are read again from the pack when applied."""
    path = Path(path)
    try:
        zf = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise PackError(f"not a data pack: {exc}") from exc
    with zf:
        infos = zf.infolist()
        if len(infos) > MAX_FILES:
            raise PackError("too many files")
        total = 0
        for info in infos:
            if info.is_dir():
                continue
            if not _NAME.match(info.filename):
                raise PackError(f"unexpected file in pack: {info.filename!r}")
            if info.file_size > MAX_FILE:
                raise PackError(f"file too large: {info.filename}")
            total += info.file_size
            if total > MAX_TOTAL:
                raise PackError("pack too large")
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError as exc:
            raise PackError("manifest.json missing") from exc
        except ValueError as exc:
            raise PackError("bad manifest.json") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != PACK_FORMAT:
            raise PackError("not a Jisho Lens OCR data pack")
        if int(manifest.get("version", 0)) > FORMAT:
            raise PackError("pack made by a newer version of Jisho Lens")
        samples: dict[str, Sample] = {}
        sizes: dict[str, int] = {}
        for info in infos:
            name = info.filename
            if not name.startswith("samples/"):
                continue
            sid = name[len("samples/"):].rsplit(".", 1)[0]
            data = zf.read(info)
            if name.endswith(".png"):
                if sample_id(data) != sid:
                    raise PackError(f"image doesn't match its name: {name}")
                try:
                    with Image.open(io.BytesIO(data)) as im:
                        if im.format != "PNG" or im.width * im.height > MAX_PIXELS:
                            raise PackError(f"bad image: {name}")
                except PackError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise PackError(f"bad image: {name}") from exc
                sizes[sid] = len(data)
            else:
                try:
                    sample = Sample.from_dict(json.loads(data))
                except (ValueError, TypeError) as exc:
                    raise PackError(f"bad sample data: {name}") from exc
                if sample.id != sid or not isinstance(sample.ocr_text, str) \
                        or not isinstance(sample.alternatives, list):
                    raise PackError(f"bad sample data: {name}")
                samples[sid] = sample
        missing = set(samples) - set(sizes)
        if missing:
            raise PackError(f"{len(missing)} samples without an image")
    shareable = {sid: s for sid, s in samples.items() if is_shareable(s)}
    info = PackInfo.from_manifest(manifest, path.name, samples.keys())
    return Pack(path, manifest, shareable, sizes, skipped=len(samples) - len(shareable),
                info=info)


# ---------------------------------------------------------------- review rows
@dataclass
class Answer:
    truth: str
    contributor: str = ""
    pack: str = ""  # pack file name it came from
    source: Pack | None = field(default=None, repr=False, compare=False)

    def as_alternative(self) -> dict:
        return {"truth": self.truth, "source": "edited", "contributor": self.contributor}


@dataclass
class ReviewRow:
    sid: str
    status: str
    ocr_text: str
    before: str | None  # your right answer (import), or None
    answers: list[Answer]  # incoming right answers (merge: one per disagreeing pack)
    sample: Sample  # the incoming sample (metadata)
    pack: Pack  # where its image is
    include: bool = True
    choice: str | int = KEEP_MINE  # import "differs": mine / theirs / alternative;
    #                                merge "differs": answer index or ALL_ANSWERS
    local_id: str | None = None  # same_sentence: your sample of that sentence

    @property
    def after(self) -> str:
        return self.answers[0].truth if self.answers else ""

    @property
    def size(self) -> int:
        return self.pack.sizes.get(self.sid, 0)

    @property
    def contributor(self) -> str:
        return self.sample.contributor

    @property
    def category(self) -> str:
        return self.sample.category or ""

    @category.setter
    def category(self, value: str) -> None:
        from jisho_lens.core.categories import clean_category

        self.sample.category = clean_category(value)


def _incoming_answers(sample: Sample, pack: Pack) -> list[Answer]:
    out = [Answer(sample.truth, sample.contributor, pack.name, pack)]
    for alt in sample.alternatives:
        truth = alt.get("truth") if isinstance(alt, dict) else None
        if isinstance(truth, str) and all(truth != a.truth for a in out):
            out.append(Answer(truth, str(alt.get("contributor", "")), pack.name, pack))
    return out


def review_import(store: OcrDataStore, pack: Pack) -> list[ReviewRow]:
    """One row per sample in the pack, compared with your data. Defaults: New included,
    Different answer included with Keep mine, Same sentence excluded, Same not offered."""
    rows: list[ReviewRow] = []
    seen_keys: set[str] = set()
    for sid, s in pack.samples.items():
        answers = _incoming_answers(s, pack)
        local = store.get(sid)
        if local is None:
            other = store.find_text(s.ocr_text)
            key = _key(s.ocr_text)
            if other is not None or key in seen_keys:
                rows.append(ReviewRow(sid, SAME_SENTENCE, s.ocr_text,
                                      other.truth if other else None, answers, s, pack,
                                      include=False, local_id=other.id if other else None))
            else:
                rows.append(ReviewRow(sid, NEW, s.ocr_text, None, answers, s, pack))
            seen_keys.add(key)
            continue
        known = {local.truth} | {a.get("truth") for a in local.alternatives}
        if local.truth is None:
            rows.append(ReviewRow(sid, NEW, s.ocr_text, None, answers, s, pack))
        elif all(a.truth in known for a in answers):
            rows.append(ReviewRow(sid, SAME, s.ocr_text, local.truth, answers, s, pack,
                                  include=False))
        else:
            new = [a for a in answers if a.truth not in known]
            rows.append(ReviewRow(sid, DIFFERS, s.ocr_text, local.truth, new, s, pack,
                                  choice=KEEP_MINE))
    return rows


def review_merge(packs: list[Pack]) -> list[ReviewRow]:
    """One row per image across the packs. Packs that disagree on an image give a
    "Different answer" row listing each answer (default: keep them all). Another crop of a
    sentence already in an earlier pack is "Same sentence" (excluded by default)."""
    by_id: dict[str, ReviewRow] = {}
    first_by_key: dict[str, str] = {}
    rows: list[ReviewRow] = []
    for pack in packs:
        for sid, s in pack.samples.items():
            answers = _incoming_answers(s, pack)
            row = by_id.get(sid)
            if row is not None:
                for a in answers:
                    if all(a.truth != b.truth for b in row.answers):
                        row.answers.append(a)
                if len(row.answers) > 1 and row.status != SAME_SENTENCE:
                    row.status, row.choice = DIFFERS, ALL_ANSWERS
                continue
            key = _key(s.ocr_text)
            if key in first_by_key:
                row = ReviewRow(sid, SAME_SENTENCE, s.ocr_text,
                                by_id[first_by_key[key]].after, answers, s, pack,
                                include=False, local_id=first_by_key[key])
            else:
                first_by_key[key] = sid
                status = DIFFERS if len(answers) > 1 else NEW
                row = ReviewRow(sid, status, s.ocr_text, None, answers, s, pack,
                                choice=ALL_ANSWERS if status == DIFFERS else KEEP_MINE)
            by_id[sid] = row
            rows.append(row)
    return rows


# ---------------------------------------------------------------- export review
class LocalPack:
    """Your own data seen as a pack, so the export review shows it like other packs."""

    info = None
    skipped = 0

    def __init__(self, store: OcrDataStore, samples: list[Sample]) -> None:
        self.store = store
        self.samples = {s.id: s for s in samples}
        self.sizes = {s.id: (store.png_path(s.id).stat().st_size
                             if store.png_path(s.id).exists() else 0) for s in samples}
        self.name = self.label = "your data"
        self.path = store.folder

    def image(self, sid: str) -> bytes:
        return self.store.png_path(sid).read_bytes()


def review_export(store: OcrDataStore) -> list[ReviewRow]:
    """One row per sample fixed with Edit: Before = what OCR read, After = your fix. All
    included; categories as last labelled (blank if none)."""
    samples = [Sample.from_dict(json.loads(s.to_json())) for s in select(store)]
    pack = LocalPack(store, samples)
    return [ReviewRow(s.id, NEW, s.ocr_text, s.ocr_text, [Answer(s.truth, s.contributor,
                                                                 pack.name, None)], s, pack)
            for s in samples]


def apply_export(store: OcrDataStore, rows: list[ReviewRow], path: Path,
                 name: str | None = None) -> int:
    """Export the included rows, each labelled with its category (blank = none). The
    categories are also saved on your samples, so the next export starts from them."""
    samples = []
    for row in rows:
        store.set_category(row.sid, row.category)
        if row.include:
            samples.append(row.sample)
    return export_pack(store, path, samples, name)


def label_rows(rows: list[ReviewRow], category: str, only=None) -> int:
    """Set the category of the included rows (or of `only`). Returns how many changed."""
    n = 0
    for row in rows if only is None else only:
        if (only is not None or row.include) and row.category != category:
            row.category = category
            n += 1
    return n


# ---------------------------------------------------------------- apply
@dataclass
class ImportResult:
    added: int = 0  # new samples
    answers_added: int = 0  # a right answer filled in for an image you had without one
    replaced: int = 0  # "Use theirs" (your answer kept as an alternative)
    alternatives: int = 0  # "Keep as alternative" (flagged for review)
    kept_mine: int = 0  # "Keep mine"
    skipped: int = 0  # excluded, or already the same
    unanswered: int = 0  # samples in the pack without an Edit fix (not offered)
    learned: int = 0  # OCR fixes learned ("Also learn OCR fixes from these")
    fixed: list[tuple[str, str]] = field(default_factory=list)  # (ocr_text, truth) applied

    # names used before the review window existed
    @property
    def duplicates(self) -> int:
        return self.kept_mine + self.replaced + self.alternatives + self.skipped

    @property
    def conflicts(self) -> int:
        return self.alternatives + self.replaced

    def summary(self) -> str:
        parts = [f"{self.added} new samples"]
        for n, text in ((self.answers_added, "answers added"),
                        (self.replaced, "answers replaced (yours kept as alternative)"),
                        (self.alternatives, "kept as alternative answers (to review)"),
                        (self.kept_mine, "kept yours"), (self.skipped, "skipped"),
                        (self.unanswered, "without an Edit fix (not included)"),
                        (self.learned, "OCR fixes learned")):
            if n:
                parts.append(f"{n} {text}")
        return ", ".join(parts)


def _declined(row: ReviewRow) -> bool:
    """Not used by the user's choice: an unticked New / Different answer row, or Keep mine
    on a different answer. (Skipped duplicates don't count.)"""
    if row.status not in (NEW, DIFFERS):
        return False
    return not row.include or (row.status == DIFFERS and row.choice == KEEP_MINE)


def apply_import(store: OcrDataStore, rows: list[ReviewRow], corrections=None
                 ) -> ImportResult:
    """Write the included rows as chosen. `corrections` (a CorrectionStore) also learns
    the OCR fixes of the imported answers ("Also learn OCR fixes from these")."""
    result = ImportResult()
    for row in rows:
        if not row.include or row.status == SAME:
            result.skipped += 1
            continue
        theirs = row.answers[0]
        local = store.get(row.sid)
        if local is None:  # NEW, or SAME_SENTENCE the user kept
            sample = Sample.from_dict(json.loads(row.sample.to_json()))
            sample.truth, sample.truth_source = theirs.truth, "edited"
            sample.alternatives = [a.as_alternative() for a in row.answers[1:]]
            sample.needs_review = len(row.answers) > 1
            store.save(sample, row.pack.image(row.sid))
            result.added += 1
            result.fixed.append((row.ocr_text, theirs.truth))
        elif local.truth is None:
            local.category = local.category or row.category
            local.truth, local.truth_source = theirs.truth, "edited"
            local.alternatives += [a.as_alternative() for a in row.answers[1:]]
            store.save(local)
            result.answers_added += 1
            result.fixed.append((row.ocr_text, theirs.truth))
        elif row.choice == USE_THEIRS:
            local.alternatives.append({"truth": local.truth, "source": local.truth_source,
                                       "contributor": local.contributor})
            local.alternatives += [a.as_alternative() for a in row.answers[1:]]
            local.truth, local.truth_source = theirs.truth, "edited"
            store.save(local)
            result.replaced += 1
            result.fixed.append((row.ocr_text, theirs.truth))
        elif row.choice == KEEP_ALTERNATIVE:
            local.alternatives += [a.as_alternative() for a in row.answers]
            local.needs_review = True
            store.save(local)
            result.alternatives += 1
        else:
            result.kept_mine += 1
    packs = {id(r.pack): r.pack for r in rows}.values()
    result.unanswered = sum(p.skipped for p in packs)
    for pack in packs:
        mine = [r for r in rows if r.pack is pack]
        used = [r.sid for r in mine if r.include and r.status != SAME
                and not (r.status == DIFFERS and r.choice == KEEP_MINE)]
        same = [r.sid for r in mine if r.status == SAME]
        declined = [r.sid for r in mine if _declined(r)]
        if used or same or declined:
            store.provenance.record_import(pack.info, used + same, declined)
    if corrections is not None:
        for ocr_text, truth in result.fixed:
            result.learned += corrections.learn(ocr_text.splitlines(), truth.splitlines())
    return result


def merge_sources(rows: list[ReviewRow]) -> str:
    """'RavenOCR v2 + KaiOCR v4 (partial)': a pack is partial when some of its samples or
    answers were left out by the user's choice (unticked, or another pack's answer used).
    Skipped duplicates (Same sentence) don't count."""
    packs: list[Pack] = []
    partial: set[int] = set()
    for row in rows:
        for pack in [row.pack] + [a.source for a in row.answers if a.source is not None]:
            if all(pack is not p for p in packs):
                packs.append(pack)
        if row.status in (NEW, DIFFERS) and not row.include:
            partial.update(id(a.source or row.pack) for a in row.answers)
        elif row.status == DIFFERS and isinstance(row.choice, int) and row.choice >= 0:
            partial.update(id(a.source or row.pack) for i, a in enumerate(row.answers)
                           if i != row.choice)
    return " + ".join(p.label + (" (partial)" if id(p) in partial else "") for p in packs)


def apply_merge(rows: list[ReviewRow], output: Path, contributor: str | None = None,
                name: str | None = None, provenance_store: OcrDataStore | None = None) -> int:
    """Write the included rows to one new pack. "Different answer": the chosen answer, or
    with ALL_ANSWERS the first one with the others as alternatives (flagged for review).

    With `name` and `provenance_store` (your data): the merged pack is the next version of
    your pack `name`, and its history log has the logs of every merged pack."""
    release = log = None
    if name and provenance_store is not None:
        release = release_entry(provenance_store, name, "merged", merge_sources(rows),
                                [r.sample for r in rows if r.include])
        pack_logs = {id(r.pack): r.pack.info.log for r in rows if r.pack.info}
        log = merge_logs([release], provenance_store.provenance.series_log(release.name),
                         *pack_logs.values())
    with tempfile.TemporaryDirectory() as tmp:
        store = OcrDataStore(Path(tmp))
        if contributor:
            store.folder.mkdir(parents=True, exist_ok=True)
            (store.folder / "contributor.txt").write_text(contributor, encoding="utf-8")
        for row in rows:
            if not row.include:
                continue
            sample = Sample.from_dict(json.loads(row.sample.to_json()))
            if isinstance(row.choice, int) and 0 <= row.choice < len(row.answers):
                chosen, others = row.answers[row.choice], []
            else:
                chosen, others = row.answers[0], row.answers[1:]
            sample.truth, sample.truth_source = chosen.truth, "edited"
            sample.alternatives = [a.as_alternative() for a in others]
            sample.needs_review = bool(others)
            store.save(sample, row.pack.image(row.sid))
        if release is not None:
            from jisho_lens.core.categories import category_summary

            release.samples = len(store.all())
            release.categories = category_summary(s.category for s in store.all())
        count = export_pack(store, output, store.all(), release=release, log=log)
    if release is not None:
        provenance_store.provenance.record_release(release)
    return count


# ---------------------------------------------------------------- without review
def import_pack(store: OcrDataStore, path: Path, corrections=None) -> ImportResult:
    """Import with the default choices (command line)."""
    return apply_import(store, review_import(store, read_pack(Path(path))), corrections)


def merge_packs(inputs: list[Path], output: Path) -> tuple[int, ImportResult]:
    """Merge with the default choices (command line). Returns (samples written, counts)."""
    rows = review_merge([read_pack(Path(p)) for p in inputs])
    count = apply_merge(rows, output)
    result = ImportResult(added=count,
                          alternatives=sum(r.status == DIFFERS and r.include for r in rows),
                          skipped=sum(not r.include for r in rows))
    return count, result


# ---------------------------------------------------------------- test set
def to_test_set(store: OcrDataStore, folder: Path) -> int:
    """Write samples with a right answer (edited or ✓) as <text type>__<id>.png + .txt for
    tools/ocr_bench.py. The right text includes the speaker line first, like the
    screenshot. This stays on this computer, so ✓ samples are included here."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    for s in checked(store):
        stem = f"{s.text_type or 'text'}__{s.id[:12]}"
        (folder / f"{stem}.png").write_bytes(store.png_path(s.id).read_bytes())
        truth = s.truth if not s.speaker else f"{s.speaker}\n{s.truth}"
        (folder / f"{stem}.txt").write_text(truth, encoding="utf-8")
        count += 1
    return count


# ---------------------------------------------------------------- label preview
def preview_import_label(store: OcrDataStore, rows: list[ReviewRow]) -> tuple[str, str]:
    """("Using:" label now, label after importing the rows as currently chosen)."""
    from jisho_lens.core.ocr_data.provenance import ImportRecord, PackUse, using_label

    now, uses, own = store.using()
    after = [u for u in uses if all(u.record.pack_id != r.pack.info.pack_id
                                    for r in rows if r.pack.info)]
    for pack in {id(r.pack): r.pack for r in rows}.values():
        mine = [r for r in rows if r.pack is pack]
        used = [r for r in mine if (r.include and r.status != SAME
                                    and not (r.status == DIFFERS and r.choice == KEEP_MINE))
                or r.status == SAME]
        declined = [r for r in mine if _declined(r)]
        if used:
            rec = ImportRecord(pack.info.pack_id, pack.label, pack.info.contributor,
                               pack.name, "")
            after.append(PackUse(rec, len(used), len(used), len(declined)))
    return now, using_label(after, own)
