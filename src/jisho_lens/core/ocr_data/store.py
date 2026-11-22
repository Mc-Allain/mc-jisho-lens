"""Locally collected OCR samples (opt-in): screenshot crop + OCR result + the right answer.

Everything stays in <data dir>/ocr-data/ on this computer. Nothing is sent anywhere; the
user can export a pack (packs.py) and share it themselves.

Each sample is two files named by the SHA-256 of the PNG bytes, so the same image from
different people or captures is one sample:
  samples/<id>.png   the selected screen area
  samples/<id>.json  metadata (see Sample)
"""

from __future__ import annotations

import io
import json
import shutil
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path

from PIL import Image

from jisho_lens import __version__
from jisho_lens.core import paths

FORMAT = 1


@dataclass
class Sample:
    id: str
    ocr_text: str  # raw OCR output (all lines, before cleanup)
    engine: str = ""
    preset: str = ""
    seconds: float | None = None
    speaker: str | None = None
    category: str = "text"  # "dialogue" when a speaker line was found; editable
    game: str = ""
    screen: dict = field(default_factory=dict)  # width, height, scale
    app_version: str = __version__
    created: str = ""
    contributor: str = ""  # anonymous random ID, no personal details
    truth: str | None = None  # the right text: corrected by Edit, or confirmed with ✓
    truth_source: str | None = None  # "edited" | "confirmed"
    alternatives: list[dict] = field(default_factory=list)  # other people's answers
    needs_review: bool = False  # answers disagree after a merge
    format: int = FORMAT

    @property
    def checked(self) -> bool:
        return self.truth is not None

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def from_dict(cls, data: dict) -> Sample:
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in known})


def png_bytes(image: Image.Image) -> bytes:
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def sample_id(png: bytes) -> str:
    return sha256(png).hexdigest()


class OcrDataStore:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder or (paths.data_dir() / "ocr-data")
        self.samples_dir = self.folder / "samples"
        self._lock = threading.Lock()
        self._cache: list[Sample] | None = None  # all samples, dropped on every change

    # ---------- identity ----------
    def contributor(self) -> str:
        """Anonymous random ID for this copy of the app (used in exported packs)."""
        path = self.folder / "contributor.txt"
        if not path.exists():
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_text(uuid.uuid4().hex[:16], encoding="utf-8")
        return path.read_text(encoding="utf-8").strip()

    # ---------- read ----------
    def png_path(self, sid: str) -> Path:
        return self.samples_dir / f"{sid}.png"

    def get(self, sid: str) -> Sample | None:
        path = self.samples_dir / f"{sid}.json"
        if not path.exists():
            return None
        return Sample.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def all(self) -> list[Sample]:
        if self._cache is None:
            self._cache = self._read_all()
        return [Sample.from_dict(asdict(s)) for s in self._cache]

    def _read_all(self) -> list[Sample]:
        if not self.samples_dir.exists():
            return []
        out = []
        for path in sorted(self.samples_dir.glob("*.json")):
            try:
                out.append(Sample.from_dict(json.loads(path.read_text(encoding="utf-8"))))
            except (OSError, ValueError, TypeError):
                continue
        return out

    def stats(self) -> dict:
        samples = self.all()
        return {
            "samples": len(samples),
            "checked": sum(s.checked for s in samples),
            "edited": sum(s.truth_source == "edited" for s in samples),
            "confirmed": sum(s.truth_source == "confirmed" for s in samples),
            "needs_review": sum(s.needs_review for s in samples),
        }

    # ---------- write ----------
    def save(self, sample: Sample, png: bytes | None = None) -> None:
        with self._lock:
            self.samples_dir.mkdir(parents=True, exist_ok=True)
            if png is not None and not self.png_path(sample.id).exists():
                self.png_path(sample.id).write_bytes(png)
            (self.samples_dir / f"{sample.id}.json").write_text(sample.to_json(),
                                                               encoding="utf-8")
            self._cache = None

    def find_text(self, text: str) -> Sample | None:
        """A sample of the same sentence: its OCR text or its right answer equals `text`.

        Prefers a checked sample (edited or ✓) when there are several.
        """
        key = _key(text)
        if not key:
            return None
        found = None
        for s in self._cache if self._cache is not None else self.all():
            truths = () if s.truth is None else (s.truth, f"{s.speaker or ''}{s.truth}")
            if _key(s.ocr_text) == key or any(_key(x) == key for x in truths):
                if s.checked:
                    return self.get(s.id)
                found = found or s
        return self.get(found.id) if found else None

    def add_capture(self, image: Image.Image, ocr_text: str, *, engine: str, preset: str,
                    seconds: float, speaker: str | None, game: str = "",
                    screen: dict | None = None, png: bytes | None = None) -> str:
        """Keep a capture as a sample. Returns the sample id.

        The same image refreshes its sample's OCR result. Another crop of a sentence that is
        already kept (same OCR text, or OCR text equal to a kept right answer) is not saved
        again: the existing sample's id is returned, so Edit and ✓ update that one.
        """
        png = png if png is not None else png_bytes(image)
        sid = sample_id(png)
        existing = self.get(sid)
        if existing is not None:
            existing.ocr_text, existing.engine, existing.preset = ocr_text, engine, preset
            existing.seconds, existing.speaker = seconds, speaker
            self.save(existing)
            return sid
        same = self.find_text(ocr_text)
        if same is not None:
            return same.id
        self.save(Sample(
            id=sid, ocr_text=ocr_text, engine=engine, preset=preset, seconds=seconds,
            speaker=speaker, category="dialogue" if speaker else "text", game=game,
            screen=screen or {}, created=time.strftime("%Y-%m-%dT%H:%M:%S"),
            contributor=self.contributor()), png)
        return sid

    # ---------- space ----------
    def size_bytes(self) -> int:
        if not self.samples_dir.exists():
            return 0
        return sum(p.stat().st_size for p in self.samples_dir.iterdir() if p.is_file())

    def delete(self, sid: str) -> None:
        with self._lock:
            for ext in ("png", "json"):
                (self.samples_dir / f"{sid}.{ext}").unlink(missing_ok=True)
            self._cache = None

    def enforce_limit(self, max_bytes: int, keep: set[str] = frozenset()) -> int:
        """Delete the oldest unchecked samples until the data fits in `max_bytes`.

        Checked samples (edited or ✓) and the ids in `keep` (favorites) are never deleted
        here, even if the data stays over the limit. 0 = no limit. Returns deletions.
        """
        if max_bytes <= 0:
            return 0
        total = self.size_bytes()
        if total <= max_bytes:
            return 0
        candidates = sorted((s for s in self.all() if not s.checked and s.id not in keep),
                            key=lambda s: s.created)
        deleted = 0
        for s in candidates:
            if total <= max_bytes:
                break
            for ext in ("png", "json"):
                p = self.samples_dir / f"{s.id}.{ext}"
                if p.exists():
                    total -= p.stat().st_size
            self.delete(s.id)
            deleted += 1
        return deleted

    def remove_duplicates(self, keep: set[str] = frozenset()) -> dict[str, str]:
        """Merge samples of the same sentence (OCR text). Returns {removed id: kept id}.

        Checked samples and the ids in `keep` always stay; of unchecked duplicates only one
        is kept, and only when no checked sample of that sentence exists.
        """
        groups: dict[str, list[Sample]] = {}
        for s in self.all():
            groups.setdefault(_key(s.ocr_text), []).append(s)
        removed: dict[str, str] = {}
        for key, group in groups.items():
            if not key or len(group) < 2:
                continue
            stay = [s for s in group if s.checked or s.id in keep]
            rest = sorted((s for s in group if s not in stay), key=lambda s: s.created,
                          reverse=True)
            if not stay:
                stay, rest = rest[:1], rest[1:]
            target = next((s for s in stay if s.checked), stay[0])
            for s in rest:
                self.delete(s.id)
                removed[s.id] = target.id
        return removed

    def set_truth(self, sid: str, text: str, source: str) -> None:
        """source: "edited" (user corrected the text) or "confirmed" (✓, OCR was right)."""
        sample = self.get(sid)
        if sample is None:
            return
        sample.truth, sample.truth_source = text, source
        self.save(sample)

    def set_category(self, sid: str, category: str) -> None:
        sample = self.get(sid)
        if sample is not None:
            sample.category = category
            self.save(sample)

    def delete_all(self, keep: set[str] = frozenset()) -> int:
        """Delete every sample except the ids in `keep` (favorites). Returns deletions."""
        if not keep:
            n = len(self.all())
            with self._lock:
                if self.samples_dir.exists():
                    shutil.rmtree(self.samples_dir)
                self._cache = None
            return n
        n = 0
        for s in self.all():
            if s.id not in keep:
                self.delete(s.id)
                n += 1
        return n


def _key(text: str | None) -> str:
    """Sentence key for duplicates: the text without spaces and line breaks."""
    return "".join((text or "").split())
