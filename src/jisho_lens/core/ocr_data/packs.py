"""OCR data packs: export, import and merge collected samples as one .zip file.

Sharing is manual: a user exports a pack and sends it to someone, who imports it. A pack
contains only:
  manifest.json              format, app version, counts, anonymous contributor ID
  samples/<sha256>.png       screenshot crops
  samples/<sha256>.json      sample metadata (see store.Sample)

Imports are validated (names, sizes, PNG content matches its hash, JSON shape) and merged:
the same image (same hash) is one sample; when people disagree on the right text, every
answer is kept and the sample is flagged for review.
"""

from __future__ import annotations

import io
import json
import re
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from jisho_lens import __version__
from jisho_lens.core.ocr_data.store import FORMAT, OcrDataStore, Sample, sample_id

PACK_FORMAT = "jisho-lens-ocr-pack"
_NAME = re.compile(r"^(manifest\.json|samples/[0-9a-f]{64}\.(png|json))$")
MAX_FILE = 20 * 1024 * 1024  # per file, uncompressed
MAX_TOTAL = 2 * 1024 * 1024 * 1024  # whole pack, uncompressed
MAX_FILES = 200_000
MAX_PIXELS = 8000 * 8000


class PackError(ValueError):
    pass


@dataclass
class ImportResult:
    added: int = 0
    duplicates: int = 0
    answers_added: int = 0  # a right answer filled in from the pack
    conflicts: int = 0  # answers disagree; flagged for review

    def summary(self) -> str:
        return (f"{self.added} new samples, {self.duplicates} already here, "
                f"{self.answers_added} answers added, {self.conflicts} conflicts to review")


# ---------------------------------------------------------------- export
def select(store: OcrDataStore, which: str = "checked", game: str | None = None
           ) -> list[Sample]:
    """which: "all" or "checked" (✓ or edited); game: only that game (case-insensitive)."""
    samples = store.all()
    if which == "checked":
        samples = [s for s in samples if s.checked]
    if game:
        samples = [s for s in samples if s.game.lower() == game.lower()]
    return samples


def export_pack(store: OcrDataStore, path: Path, samples: list[Sample]) -> int:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "format": PACK_FORMAT,
        "version": FORMAT,
        "app_version": __version__,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "contributor": store.contributor(),
        "samples": len(samples),
        "checked": sum(s.checked for s in samples),
    }
    tmp = path.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=1))
        for s in samples:
            zf.write(store.png_path(s.id), f"samples/{s.id}.png")
            zf.writestr(f"samples/{s.id}.json", s.to_json())
    tmp.replace(path)
    return len(samples)


# ---------------------------------------------------------------- import
def _read_pack(path: Path) -> tuple[dict, dict[str, Sample], dict[str, bytes]]:
    """Validate a pack and return (manifest, samples, png bytes). Raises PackError."""
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
        if manifest.get("format") != PACK_FORMAT:
            raise PackError("not a Jisho Lens OCR data pack")
        if int(manifest.get("version", 0)) > FORMAT:
            raise PackError("pack made by a newer version of Jisho Lens")
        samples: dict[str, Sample] = {}
        images: dict[str, bytes] = {}
        for info in infos:
            name = info.filename
            if not name.startswith("samples/"):
                continue
            sid = name[len("samples/"):-len(".png")] if name.endswith(".png") else \
                name[len("samples/"):-len(".json")]
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
                images[sid] = data
            else:
                try:
                    sample = Sample.from_dict(json.loads(data))
                except (ValueError, TypeError) as exc:
                    raise PackError(f"bad sample data: {name}") from exc
                if sample.id != sid or not isinstance(sample.ocr_text, str):
                    raise PackError(f"bad sample data: {name}")
                samples[sid] = sample
        missing = set(samples) - set(images)
        if missing:
            raise PackError(f"{len(missing)} samples without an image")
    return manifest, samples, images


def _answers(sample: Sample) -> list[dict]:
    out = []
    if sample.truth is not None:
        out.append({"truth": sample.truth, "source": sample.truth_source,
                    "contributor": sample.contributor})
    out += [a for a in sample.alternatives if a.get("truth") is not None]
    return out


def import_pack(store: OcrDataStore, path: Path) -> ImportResult:
    _, samples, images = _read_pack(Path(path))
    result = ImportResult()
    for sid, incoming in samples.items():
        local = store.get(sid)
        if local is None:
            store.save(incoming, images[sid])
            result.added += 1
            continue
        result.duplicates += 1
        changed = False
        for answer in _answers(incoming):
            if local.truth is None:
                local.truth, local.truth_source = answer["truth"], answer.get("source")
                result.answers_added += 1
                changed = True
            elif answer["truth"] != local.truth and all(
                    a.get("truth") != answer["truth"] for a in local.alternatives):
                local.alternatives.append(answer)
                local.needs_review = True
                result.conflicts += 1
                changed = True
        if changed:
            store.save(local)
    return result


def merge_packs(inputs: list[Path], output: Path) -> tuple[int, ImportResult]:
    """Combine several packs into one (duplicates merged, conflicts kept and flagged)."""
    total = ImportResult()
    with tempfile.TemporaryDirectory() as tmp:
        store = OcrDataStore(Path(tmp))
        for path in inputs:
            r = import_pack(store, path)
            total.added += r.added
            total.duplicates += r.duplicates
            total.answers_added += r.answers_added
            total.conflicts += r.conflicts
        count = export_pack(store, output, store.all())
    return count, total


# ---------------------------------------------------------------- test set
def to_test_set(store: OcrDataStore, folder: Path, game: str | None = None) -> int:
    """Write checked samples as <category>__<id>.png + .txt for tools/ocr_bench.py.
    The right text includes the speaker line first, like the screenshot."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    count = 0
    for s in select(store, "checked", game):
        stem = f"{s.category or 'text'}__{s.id[:12]}"
        (folder / f"{stem}.png").write_bytes(store.png_path(s.id).read_bytes())
        truth = s.truth if not s.speaker else f"{s.speaker}\n{s.truth}"
        (folder / f"{stem}.txt").write_text(truth, encoding="utf-8")
        count += 1
    return count
