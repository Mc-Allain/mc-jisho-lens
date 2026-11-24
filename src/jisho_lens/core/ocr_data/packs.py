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
import zlib
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
REMOVED = "removed"  # merge: an older version has it, a newer one of the same pack dropped it
STATUS_LABELS = {NEW: "New", SAME: "Same", DIFFERS: "Different answer",
                 SAME_SENTENCE: "Same sentence", REMOVED: "Removed in newer version"}

# what to do with a "differs" row
KEEP_MINE, USE_THEIRS, KEEP_ALTERNATIVE = "mine", "theirs", "alternative"
ALL_ANSWERS = -1  # merge: keep every pack's answer (first as the answer, others alternatives)


class PackError(ValueError):
    pass


def is_shareable(sample: Sample) -> bool:
    """Only samples fixed with Edit go into packs (OCR read the others right, or they were
    never checked)."""
    return sample.is_fix


# ---------------------------------------------------------------- export
def select(store: OcrDataStore) -> list[Sample]:
    """Samples for a pack: the ones fixed with Edit."""
    return [s for s in store.all() if is_shareable(s)]


def checked(store: OcrDataStore) -> list[Sample]:
    """Every sample with a right answer (edited or ✓), for the local OCR test set."""
    return [s for s in store.all() if s.checked]


def release_content(samples: list[Sample]) -> dict[str, str]:
    """What a release contains: {sample id: fingerprint of its answer and category}."""
    from hashlib import sha1

    return {s.id: sha1(f"{s.truth}\x00{s.category}".encode()).hexdigest()[:16]
            for s in samples if is_shareable(s)}


def describe_changes(old: dict | None, new: dict) -> tuple[str, bool]:
    """("3 new, 1 changed, 1 removed", unchanged?) compared with the previous release."""
    if old is None:
        return "first release", False
    added = len(new.keys() - old.keys())
    removed = len(old.keys() - new.keys())
    changed = sum(old[k] != new[k] for k in new.keys() & old.keys())
    parts = [f"{n} {what}" for n, what in ((added, "new"), (changed, "changed"),
                                            (removed, "removed")) if n]
    return (", ".join(parts), False) if parts else ("no changes", True)


def release_entry(store: OcrDataStore, name: str, action: str, sources: str,
                  samples: list[Sample]) -> tuple[LogEntry, bool, dict, str]:
    """The history-log line of a release of your pack `name`: the next version, or, when
    nothing changed since the last one, that same version again. Returns (entry,
    unchanged?, content, pack ID to use)."""
    from jisho_lens.core.categories import category_summary

    name = clean_name(name)
    last, old, last_id = store.provenance.last_release(name)
    content = release_content(samples)
    changes, unchanged = describe_changes(old, content) if last else ("first release", False)
    version = last if unchanged else last + 1
    entry = LogEntry(name=name, version=version, date=time.strftime("%Y-%m-%dT%H:%M:%S"),
                     contributor=store.contributor(), action=action, sources=sources,
                     samples=len(content), categories=category_summary(
                         s.category for s in samples if is_shareable(s)),
                     changes=changes)
    return entry, unchanged, content, (last_id if unchanged and last_id
                                       else uuid.uuid4().hex)


def release_preview(store: OcrDataStore, name: str, samples: list[Sample]) -> tuple[int, str,
                                                                                     bool]:
    """(version it will get, changes since the last version, unchanged?) for the screens."""
    entry, unchanged, _content, _id = release_entry(store, name, "exported", "", samples)
    return entry.version, entry.changes, unchanged


def export_pack(store: OcrDataStore, path: Path, samples: list[Sample],
                name: str | None = None, *, release=None,
                log: list[LogEntry] | None = None) -> int:
    """Write a pack. Samples not fixed with Edit are left out.

    With `name`: a release of your pack of that name: the next version with a new history
    line, or, when nothing changed since the last version, that same version again (no new
    line). Its history log has your releases and the logs of the packs your data uses.
    (`release` / `log` are given by apply_merge instead.)"""
    samples = [s for s in samples if is_shareable(s)]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if name and release is None:
        label, _uses, _own = store.using()
        release = release_entry(store, name, "exported", label, samples)
        entry, unchanged, _content, _pid = release
        series = store.provenance.series_log(entry.name)
        log = merge_logs([] if unchanged else [entry], series,
                         store.provenance.used_logs({s.id: s for s in store.all()}))
    entry = unchanged = content = pack_id = None
    if release is not None:
        entry, unchanged, content, pack_id = release
    manifest = {
        "format": PACK_FORMAT,
        "version": FORMAT,
        "app_version": __version__,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "contributor": store.contributor(),
        "samples": len(samples),
        "pack_id": pack_id or uuid.uuid4().hex,
    }
    if entry is not None:
        manifest.update(name=entry.name, series_version=entry.version,
                        sources=entry.sources,
                        log=[e.__dict__ for e in (log or [entry])])
    tmp = path.with_suffix(".part")
    try:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=1))
            for s in samples:
                zf.write(store.png_path(s.id), f"samples/{s.id}.png")
                zf.writestr(f"samples/{s.id}.json", s.to_json())
        tmp.replace(path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    if entry is not None and not unchanged:
        store.provenance.record_release(entry, content, manifest["pack_id"])
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
    stamp: tuple = ()  # (size, modified time) of the file when it was checked

    @property
    def label(self) -> str:
        return self.info.label if self.info else self.path.stem

    @property
    def name(self) -> str:
        return self.path.name

    def check_unchanged(self) -> None:
        """Raise PackError if the file was moved, deleted or replaced since it was checked
        (before anything is written)."""
        try:
            st = self.path.stat()
        except OSError as exc:
            raise PackError(f"{self.name} is no longer there (moved or deleted)") from exc
        if self.stamp and (st.st_size, st.st_mtime_ns) != self.stamp:
            raise PackError(f"{self.name} changed after it was checked; open it again")

    def image(self, sid: str) -> bytes:
        """The PNG of a sample, checked again against its name."""
        try:
            with zipfile.ZipFile(self.path) as zf:
                data = zf.read(f"samples/{sid}.png")
        except (OSError, KeyError, EOFError, zipfile.BadZipFile, zlib.error) as exc:
            raise PackError(f"can't read a picture from {self.name}: {exc}") from exc
        if sample_id(data) != sid:
            raise PackError(f"image changed since it was checked: {sid}")
        return data


def read_pack(path: Path) -> Pack:
    """Validate a pack (names, sizes, images match their hash, JSON shape). Raises
    PackError. Nothing is written; images are read again from the pack when applied."""
    path = Path(path)
    try:
        st = path.stat()
        return _read_pack(path, (st.st_size, st.st_mtime_ns))
    except PackError:
        raise
    except (OSError, EOFError, zipfile.BadZipFile, zlib.error, RuntimeError, ValueError,
            TypeError, KeyError) as exc:  # damaged zip data, odd values
        raise PackError(f"damaged or not a data pack: {exc}") from exc


def _str(value, optional: bool = False) -> bool:
    return isinstance(value, str) or (optional and value is None)


def _valid_sample(s: Sample) -> bool:
    """Types a pack must use (so nothing odd reaches the screens or your data)."""
    return (_str(s.ocr_text) and _str(s.truth, True) and _str(s.truth_source, True)
            and _str(s.speaker, True) and _str(s.contributor) and _str(s.category)
            and _str(s.engine) and _str(s.preset) and _str(s.text_type)
            and _str(s.source_pack) and _str(s.source_pack_id, True)
            and _str(s.speaker_fix, True)
            and isinstance(s.screen, dict) and isinstance(s.needs_review, bool)
            and isinstance(s.alternatives, list)
            and all(isinstance(a, dict) and _str(a.get("truth"), True)
                    and _str(a.get("contributor", ""), True) for a in s.alternatives))


def _read_pack(path: Path, stamp: tuple) -> Pack:
    zf = zipfile.ZipFile(path)
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
        try:
            version = int(manifest.get("version", 0))
        except (TypeError, ValueError) as exc:
            raise PackError("bad manifest.json (version)") from exc
        if version > FORMAT:
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
                if sample.id != sid or not _valid_sample(sample):
                    raise PackError(f"bad sample data: {name}")
                samples[sid] = sample
        missing = set(samples) - set(sizes)
        if missing:
            raise PackError(f"{len(missing)} samples without an image")
    shareable = {sid: s for sid, s in samples.items() if is_shareable(s)}
    info = PackInfo.from_manifest(manifest, path.name, samples.keys())
    return Pack(path, manifest, shareable, sizes, skipped=len(samples) - len(shareable),
                info=info, stamp=stamp)


def unique_packs(packs: list[Pack]) -> tuple[list[Pack], list[str]]:
    """The same pack chosen twice (e.g. two copies of one file) counts once. Returns
    (packs, file names left out)."""
    seen, out, dropped = set(), [], []
    for pack in packs:
        key = pack.info.pack_id if pack.info else str(pack.path)
        if key in seen:
            dropped.append(pack.name)
        else:
            seen.add(key)
            out.append(pack)
    return out, dropped


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
    removed_in: str = ""  # REMOVED: the newer version that dropped it ("KaiOCR v4")

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
            if other is not None or (key and key in seen_keys):
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


def series_key(pack) -> tuple[str, str] | None:
    """Versions of one pack share this: its name and who first released it (two people can
    use the same name). None for packs made before packs had names."""
    info = getattr(pack, "info", None)
    if info is None or not info.name:
        return None
    mine = [e for e in info.log if e.name == info.name]
    creator = min(mine, key=lambda e: e.version).contributor if mine else info.contributor
    return (info.name.lower(), creator)


def order_packs(packs: list) -> list:
    """Newest version first among versions of the same pack (where the first of them was);
    other packs keep their order."""
    groups: dict = {}
    for pack in packs:
        groups.setdefault(series_key(pack) or id(pack), []).append(pack)
    out, placed = [], set()
    for pack in packs:
        key = series_key(pack) or id(pack)
        if key in placed:
            continue
        placed.add(key)
        out.extend(sorted(groups[key], key=lambda p: -p.info.version)
                   if series_key(pack) else groups[key])
    return out


def _newest_versions(packs: list) -> dict[int, object]:
    """id(pack) -> the newest version of the same pack in `packs` (itself if newest)."""
    newest: dict = {}
    for pack in packs:
        key = series_key(pack)
        if key and (key not in newest or pack.info.version > newest[key].info.version):
            newest[key] = pack
    return {id(p): newest.get(series_key(p), p) for p in packs}


def review_merge(packs: list[Pack]) -> list[ReviewRow]:
    """One row per image across the packs, newest version first among versions of the
    same pack. Packs that disagree on an image give a "Different answer" row listing each
    answer (default: keep them all). Another crop of a sentence already in an earlier pack
    is "Same sentence" (excluded by default). An image an older version has but the newest
    version of that pack in the merge dropped is "Removed in <newer>" (excluded by
    default): it is only listed when no other pack brings it."""
    packs = order_packs(packs)
    newest = _newest_versions(packs)
    by_id: dict[str, ReviewRow] = {}
    first_by_key: dict[str, str] = {}
    rows: list[ReviewRow] = []
    removed: list[tuple[Pack, str, Sample]] = []
    for pack in packs:
        for sid, s in pack.samples.items():
            latest = newest[id(pack)]
            if latest is not pack and sid not in latest.samples:
                removed.append((pack, sid, s))
                continue
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
            if key and key in first_by_key:
                row = ReviewRow(sid, SAME_SENTENCE, s.ocr_text,
                                by_id[first_by_key[key]].after, answers, s, pack,
                                include=False, local_id=first_by_key[key])
            else:
                if key:
                    first_by_key[key] = sid
                status = DIFFERS if len(answers) > 1 else NEW
                row = ReviewRow(sid, status, s.ocr_text, None, answers, s, pack,
                                choice=ALL_ANSWERS if status == DIFFERS else KEEP_MINE)
            by_id[sid] = row
            rows.append(row)
    for pack, sid, s in removed:  # dropped by a newer version: listed, not included
        if sid in by_id:
            continue  # another pack brings it; this old answer isn't offered again
        row = ReviewRow(sid, REMOVED, s.ocr_text, None, _incoming_answers(s, pack), s, pack,
                        include=False, removed_in=newest[id(pack)].label)
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
    if not any(r.include for r in rows):
        raise PackError("nothing to export: no samples are ticked")
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
    fixed: list[tuple[str, str, str]] = field(default_factory=list)  # (id, ocr, truth)

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
    for pack in {id(r.pack): r.pack for r in rows if r.include}.values():
        if isinstance(pack, Pack):
            pack.check_unchanged()  # before anything is written
    me = store.contributor()

    def take_source(sample: Sample, pack) -> None:
        """The pack becomes the sample's source (not for your own packs)."""
        info = getattr(pack, "info", None)
        if info is not None and info.contributor != me:
            sample.source_pack, sample.source_pack_id = pack.label, info.pack_id
        else:
            sample.source_pack = sample.source_pack_id = ""

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
            take_source(sample, row.pack)
            store.save(sample, row.pack.image(row.sid))
            result.added += 1
            result.fixed.append((row.sid, row.ocr_text, theirs.truth))
        elif local.truth is None:
            local.category = local.category or row.category
            local.truth, local.truth_source = theirs.truth, "edited"
            local.alternatives += [a.as_alternative() for a in row.answers[1:]]
            take_source(local, row.pack)
            store.save(local)
            result.answers_added += 1
            result.fixed.append((row.sid, row.ocr_text, theirs.truth))
        elif row.choice == USE_THEIRS:
            local.alternatives.append({"truth": local.truth, "source": local.truth_source,
                                       "contributor": local.contributor})
            local.alternatives += [a.as_alternative() for a in row.answers[1:]]
            local.truth, local.truth_source = theirs.truth, "edited"
            take_source(local, row.pack)
            store.save(local)
            result.replaced += 1
            result.fixed.append((row.sid, row.ocr_text, theirs.truth))
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
        # used: the pack's answer is now the answer; same: present without that (identical
        # already, or kept as an alternative to yours)
        used = [r.sid for r in mine if r.include and r.status != SAME
                and not (r.status == DIFFERS and r.choice in (KEEP_MINE, KEEP_ALTERNATIVE))]
        same = [r.sid for r in mine if r.status == SAME
                or (r.include and r.status == DIFFERS and r.choice == KEEP_ALTERNATIVE)]
        declined = [r.sid for r in mine if _declined(r)]
        mine_pack = pack.info is not None and pack.info.contributor == store.contributor()
        if (used or same or declined) and pack.info is not None and not mine_pack:
            store.provenance.record_import(pack.info, used, declined, same)
    if corrections is not None:
        for sid, ocr_text, truth in result.fixed:
            s = store.get(sid)
            lines = s.ocr_lines() if s is not None else ocr_text.splitlines()
            result.learned += corrections.learn(lines, truth.splitlines(), sample_id=sid)
    return result


def carry_choices(old: list[ReviewRow], new: list[ReviewRow]) -> None:
    """After packs were added or removed: rows still there keep what the user chose (tick,
    category, the answer used); rows whose status changed start from their defaults, but
    keep their category."""
    before = {r.sid: r for r in old}
    for row in new:
        prev = before.get(row.sid)
        if prev is None:
            continue
        row.category = prev.category
        if prev.status != row.status:
            continue
        row.include = prev.include
        if row.status == DIFFERS and isinstance(prev.choice, int) and prev.choice >= 0 \
                and prev.choice < len(prev.answers):
            chosen = prev.answers[prev.choice]
            row.choice = next((i for i, a in enumerate(row.answers)
                               if a.truth == chosen.truth and a.pack == chosen.pack),
                              ALL_ANSWERS)


def merge_contributions(rows: list[ReviewRow]) -> dict[int, int]:
    """Records each pack brings to the merge as chosen, by id(pack): an included row counts
    for the pack(s) whose answer is kept (the chosen one, or every answer when all are
    kept). A pack that only repeats an image with the same answer brings nothing."""
    counts: dict[int, int] = {}
    for row in rows:
        if not row.include:
            continue
        if isinstance(row.choice, int) and 0 <= row.choice < len(row.answers):
            kept = [row.answers[row.choice]]
        else:
            kept = row.answers
        for pack_id in {id(a.source or row.pack) for a in kept}:
            counts[pack_id] = counts.get(pack_id, 0) + 1
    return counts


def merge_sources(rows: list[ReviewRow]) -> str:
    """'RavenOCR v2 + KaiOCR v4 (partial)': a pack is partial when some of its samples or
    answers were left out by the user's choice (unticked, or another pack's answer used).
    Skipped duplicates (Same sentence) don't count. A pack bringing nothing is left out."""
    counts = merge_contributions(rows)
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
    return " + ".join(p.label + (" (partial)" if id(p) in partial else "") for p in packs
                      if counts.get(id(p)))


def apply_merge(rows: list[ReviewRow], output: Path, contributor: str | None = None,
                name: str | None = None, provenance_store: OcrDataStore | None = None) -> int:
    """Write the included rows to one new pack. "Different answer": the chosen answer, or
    with ALL_ANSWERS the first one with the others as alternatives (flagged for review).

    With `name` and `provenance_store` (your data): the merged pack is the next version of
    your pack `name`, and its history log has the logs of every merged pack."""
    if not any(r.include for r in rows):
        raise PackError("nothing to merge: no samples are ticked")
    for pack in {id(r.pack): r.pack for r in rows if r.include}.values():
        pack.check_unchanged()
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
        release = log = None
        if name and provenance_store is not None:
            release = release_entry(provenance_store, name, "merged", merge_sources(rows),
                                    store.all())
            entry, unchanged = release[0], release[1]
            # the logs of the packs that bring something (not of packs left out)
            counts = merge_contributions(rows)
            pack_logs = {id(p): p.info.log for r in rows
                         for p in [r.pack] + [a.source for a in r.answers if a.source]
                         if p.info and counts.get(id(p))}
            log = merge_logs([] if unchanged else [entry],
                             provenance_store.provenance.series_log(entry.name),
                             *pack_logs.values())
        count = export_pack(store, output, store.all(), release=release, log=log)
    if release is not None and not release[1]:
        provenance_store.provenance.record_release(release[0], release[2], release[3])
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

    now, uses, _own = store.using()
    me = store.contributor()
    after = [u for u in uses if all(u.record.pack_id != r.pack.info.pack_id
                                    for r in rows if r.pack.info)]
    taken: set[str] = set()  # your samples that will get the pack's answer
    for pack in {id(r.pack): r.pack for r in rows}.values():
        mine = [r for r in rows if r.pack is pack]
        if pack.info is None or pack.info.contributor == me:
            continue  # your own pack: not listed
        used = [r for r in mine if r.include and r.status != SAME
                and not (r.status == DIFFERS and r.choice in (KEEP_MINE, KEEP_ALTERNATIVE))]
        same = [r for r in mine if r.status == SAME
                or (r.include and r.status == DIFFERS and r.choice == KEEP_ALTERNATIVE)]
        declined = [r for r in mine if _declined(r)]
        taken |= {r.sid for r in used if r.status != DIFFERS or r.choice == USE_THEIRS}
        if used or same:
            rec = ImportRecord(pack.info.pack_id, pack.label, pack.info.contributor,
                               pack.name, "")
            after.append(PackUse(rec, len(used) + len(same), len(used), len(declined)))
    own = any(not s.source_pack_id and s.id not in taken for s in store.all())
    return now, using_label(after, own)


def merge_release_preview(store: OcrDataStore, name: str, rows: list[ReviewRow]
                          ) -> tuple[int, str, bool]:
    """release_preview for a merge, from the rows as currently chosen."""
    samples = []
    for row in rows:
        if not row.include:
            continue
        s = Sample.from_dict(json.loads(row.sample.to_json()))
        chosen = (row.answers[row.choice] if isinstance(row.choice, int)
                  and 0 <= row.choice < len(row.answers) else row.answers[0])
        s.truth, s.truth_source = chosen.truth, "edited"
        samples.append(s)
    return release_preview(store, name, samples)
