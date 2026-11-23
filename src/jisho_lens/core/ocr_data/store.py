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
import re
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
    speaker: str | None = None  # the speaker's name as OCR read it
    speaker_fix: str | None = None  # your correction of it ("" = no speaker); None = as read
    text_type: str = "text"  # "dialogue" when a speaker line was found (OCR benchmark)
    category: str = ""  # your label, set when exporting or merging (e.g. Azur Promilia JP)
    source_pack: str = ""  # pack it was imported from ("KaiOCR v4"); "" = your own data
    # that pack's ID; "" = your own (also after you change the answer); None = not known
    # yet (saved before samples had a source; filled in once from the import records)
    source_pack_id: str | None = None
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

    def _without_speaker(self, text: str | None) -> list[str]:
        lines = [ln.strip() for ln in (text or "").splitlines() if ln.strip()]
        if lines and self.speaker and _key(lines[0]) == _key(self.speaker):
            lines = lines[1:]  # the speaker line OCR also read
        return lines

    def ocr_lines(self) -> list[str]:
        """What OCR read, as the window shows it (without the speaker line)."""
        return self._without_speaker(self.ocr_text)

    def answer_lines(self) -> list[str]:
        """The right text, as the window shows it (without a speaker line)."""
        return self._without_speaker(self.truth)

    @property
    def same_as_ocr(self) -> bool:
        """The right text is what OCR read (ignoring spaces, line breaks and the speaker
        line OCR also read): nothing was fixed."""
        if self.truth is None:
            return False
        truth, ocr = _key(self.truth), _key(self.ocr_text)
        speaker = _key(self.speaker)
        return truth == ocr or (bool(speaker) and speaker + truth == ocr)

    @property
    def shown_speaker(self) -> str | None:
        """The speaker's name as the window shows it: your correction, else as read."""
        if self.speaker_fix is not None:
            return self.speaker_fix or None
        return self.speaker

    @property
    def speaker_fixed(self) -> bool:
        return self.speaker_fix is not None and _key(self.speaker_fix) != _key(self.speaker)

    @property
    def is_fix(self) -> bool:
        """Fixed with Edit: the right text or the speaker's name differs from what OCR
        read."""
        if self.truth is None:
            return False
        return self.speaker_fixed or (self.truth_source == "edited" and not self.same_as_ocr)

    @property
    def state(self) -> str:
        """"edited" (fixed with Edit), "same" (the right text is what OCR read: ✓, or an
        Edit that changed nothing), or "none" (not checked)."""
        if self.truth is None:
            return "none"
        return "edited" if self.is_fix else "same"

    @property
    def source_label(self) -> str:
        return self.source_pack if self.source_pack_id else "own data"

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, indent=1)

    @classmethod
    def from_dict(cls, data: dict) -> Sample:
        known = {f for f in cls.__dataclass_fields__}
        data = dict(data)
        if "text_type" not in data and data.get("category") in ("text", "dialogue"):
            # saved before categories: "category" was the text type
            data["text_type"], data["category"] = data["category"], ""
        if not isinstance(data.get("category", ""), str):
            data["category"] = ""
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
        self.version = 0  # goes up with every change to the samples
        # goes up only with changes that can affect a fix (an answer or name saved, a
        # sample with an answer deleted, everything deleted); not for new captures
        self.fix_version = 0
        from jisho_lens.core.ocr_data.provenance import Provenance

        self.provenance = Provenance(self.folder)  # pack names, imports, "Using:" label

    # ---------- identity ----------
    def contributor(self) -> str:
        """Anonymous random ID for this copy of the app (used in exported packs)."""
        path = self.folder / "contributor.txt"
        try:
            current = path.read_text(encoding="utf-8").strip()
        except OSError:
            current = ""
        if not re.fullmatch(r"[0-9a-f]{8,64}", current):  # missing or damaged: a new one
            current = uuid.uuid4().hex[:16]
            self.folder.mkdir(parents=True, exist_ok=True)
            path.write_text(current, encoding="utf-8")
        return current

    # ---------- read ----------
    def png_path(self, sid: str) -> Path:
        return self.samples_dir / f"{sid}.png"

    def get(self, sid: str) -> Sample | None:
        """The sample, or None if it doesn't exist or its file is damaged."""
        path = self.samples_dir / f"{sid}.json"
        try:
            return Sample.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            return None

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
            "edited": sum(s.is_fix for s in samples),
            "confirmed": sum(s.checked and not s.is_fix for s in samples),
            "needs_review": sum(s.needs_review for s in samples),
        }

    # ---------- write ----------
    def save(self, sample: Sample, png: bytes | None = None,
             fix_change: bool | None = None) -> None:
        """Write a sample. `fix_change`: whether this can change a fix (default: the
        sample has an answer); it moves `fix_version`, which learned corrections are
        checked against."""
        with self._lock:
            self.samples_dir.mkdir(parents=True, exist_ok=True)
            if png is not None and not self.png_path(sample.id).exists():
                self.png_path(sample.id).write_bytes(png)
            (self.samples_dir / f"{sample.id}.json").write_text(sample.to_json(),
                                                               encoding="utf-8")
            self._cache = None
            self.version += 1
            if sample.truth is not None if fix_change is None else fix_change:
                self.fix_version += 1

    def find_text(self, text: str, shown: str | None = None) -> Sample | None:
        """A sample of the same sentence: its OCR text or its right answer equals `text`.

        When there are several: the one whose right answer is `shown` (the text as the
        capture shows it, after your corrections), else a checked one (edited or ✓), else
        any.
        """
        key = _key(text)
        if not key:
            return None
        want = _key(shown) if shown else ""
        matches = []
        for s in self._cache if self._cache is not None else self.all():
            truths = () if s.truth is None else (s.truth, f"{s.speaker or ''}{s.truth}")
            if _key(s.ocr_text) == key or any(_key(x) == key for x in truths):
                matches.append(s)
        if not matches:
            return None
        best = (next((s for s in matches if want and s.truth and _key(s.truth) == want), None)
                or next((s for s in matches if s.checked), None) or matches[0])
        return self.get(best.id)

    def known_fix(self, ocr_text: str, shown: list[str]) -> list[str] | None:
        """Your fix of this exact sentence: the right text (as the window shows it) of the
        latest sample with the same OCR reading that you fixed with Edit. None when there is
        none, or it is what the window already shows. (known_fix_sample gives the sample,
        for its speaker's name.)"""
        latest = self.known_fix_sample(ocr_text)
        if latest is None:
            return None
        lines = latest.answer_lines()
        return lines if lines and lines != list(shown) else None

    def known_fix_sample(self, ocr_text: str) -> Sample | None:
        """The latest sample with this OCR reading that you fixed (text or speaker)."""
        key = _key(ocr_text)
        if not key:
            return None
        fixes = [s for s in (self._cache if self._cache is not None else self.all())
                 if s.is_fix and _key(s.ocr_text) == key]
        return max(fixes, key=lambda s: s.created) if fixes else None

    def add_capture(self, image: Image.Image, ocr_text: str, *, engine: str, preset: str,
                    seconds: float, speaker: str | None,
                    screen: dict | None = None, png: bytes | None = None,
                    shown: str | None = None) -> str:
        """Keep a capture as a sample. Returns the sample id.

        The same image refreshes its sample's OCR result. Another crop of a sentence that is
        already kept (same OCR text, or OCR text equal to a kept right answer) is not saved
        again: the existing sample's id is returned, so Edit and ✓ update that one. With
        several, the one whose answer is `shown` (the capture's text) is used.
        """
        png = png if png is not None else png_bytes(image)
        sid = sample_id(png)
        existing = self.get(sid)
        if existing is not None:
            # a fix change only if the reading changed (corrections learn OCR -> answer)
            reread = (existing.ocr_text, existing.speaker) != (ocr_text, speaker)
            existing.ocr_text, existing.engine, existing.preset = ocr_text, engine, preset
            existing.seconds, existing.speaker = seconds, speaker
            self.save(existing, fix_change=reread and existing.truth is not None)
            return sid
        same = self.find_text(ocr_text, shown)
        if same is not None:
            return same.id
        self.save(Sample(
            id=sid, ocr_text=ocr_text, engine=engine, preset=preset, seconds=seconds,
            speaker=speaker, text_type="dialogue" if speaker else "text", source_pack_id="",
            screen=screen or {}, created=time.strftime("%Y-%m-%dT%H:%M:%S"),
            contributor=self.contributor()), png)
        return sid

    # ---------- where the data came from ----------
    def using(self):
        """(label, packs in use, own data?) e.g. "KaiOCR v4 (partial) + own data"."""
        from jisho_lens.core.ocr_data.provenance import using_label

        self.backfill_sources()
        samples = self.all()
        uses = self.provenance.uses({s.id: s for s in samples})
        own = any(not s.source_pack_id for s in samples)
        return using_label(uses, own), uses, own

    def using_details(self) -> str:
        """Hover text for the label: each pack's use and the history of the packs."""
        label, uses, own = self.using()
        lines = [f"Using: {label}"]
        lines += [u.detail() for u in uses]
        if own:
            me = self.contributor()
            n = sum(not s.source_pack_id for s in self.all())
            lines.append(f"own data: {n} sample{'s' if n != 1 else ''} you collected or "
                         f"changed (ID {me[:8]})")
        log = self.provenance.used_logs({s.id: s for s in self.all()})
        if log:
            lines += ["", "History of these packs:"] + [e.line() for e in log]
        return "\n".join(lines)

    def backfill_sources(self) -> int:
        """Once: give samples imported before samples had a source pack their source, from
        the import records. Returns how many were filled in."""
        marker = self.folder / "sources-1.done"
        if marker.exists() or not self.samples_dir.exists():
            return 0
        me = self.contributor()
        by_id = {s.id: s for s in self.all()}
        n = 0
        for rec in self.provenance.records():
            mine = []
            for sid in rec.used:
                s = by_id.get(sid)
                if s is None or s.source_pack_id is not None:
                    continue  # gone, or its source is known
                if s.contributor == me:  # yours already ("Same" in that import)
                    mine.append(sid)
                    continue
                s.source_pack, s.source_pack_id = rec.label, rec.pack_id
                self.save(s)
                n += 1
            if mine:
                self.provenance.mark_same(rec.pack_id, mine)
        marker.write_text("ok", encoding="utf-8")
        return n

    # ---------- space ----------
    def size_bytes(self) -> int:
        if not self.samples_dir.exists():
            return 0
        return sum(p.stat().st_size for p in self.samples_dir.iterdir() if p.is_file())

    def delete(self, sid: str) -> None:
        had_answer = (s := self.get(sid)) is not None and s.truth is not None
        with self._lock:
            for ext in ("png", "json"):
                (self.samples_dir / f"{sid}.{ext}").unlink(missing_ok=True)
            self._cache = None
            self.version += 1
            if had_answer:
                self.fix_version += 1

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
        """source: "edited" (user corrected the text) or "confirmed" (✓, OCR was right).

        Changing the answer of a sample imported from a pack makes it your own data (the
        pack then shows as partial)."""
        sample = self.get(sid)
        if sample is None:
            return
        if sample.source_pack_id and text != sample.truth:
            sample.source_pack = sample.source_pack_id = ""
        sample.truth, sample.truth_source = text, source
        self.save(sample)

    def set_speaker(self, sid: str, speaker: str | None) -> None:
        """Your correction of the speaker's name ("" or None = no speaker). The name as OCR
        read it is kept, so later captures are still recognised. A name changed on a sample
        from a pack makes it your own data. A sample without an answer gets the text as
        OCR read it as its answer."""
        sample = self.get(sid)
        if sample is None:
            return
        speaker = " ".join((speaker or "").split())
        fix = None if _key(speaker) == _key(sample.speaker) else speaker
        if fix == sample.speaker_fix:
            return
        if sample.source_pack_id:
            sample.source_pack = sample.source_pack_id = ""
        sample.speaker_fix = fix
        if sample.truth is None:
            sample.truth = "\n".join(sample.ocr_lines())
            sample.truth_source = "edited"
        self.save(sample)

    def set_category(self, sid: str, category: str) -> None:
        """Your label for a sample (blank = none), set when exporting."""
        sample = self.get(sid)
        if sample is not None and sample.category != category:
            sample.category = category
            self.save(sample, fix_change=False)

    def categories(self) -> list[str]:
        return sorted({s.category for s in self.all() if s.category}, key=str.lower)

    def delete_all(self, keep: set[str] = frozenset()) -> int:
        """Delete every sample except the ids in `keep` (favorites). Returns deletions."""
        if not keep:
            n = len(self.all())
            with self._lock:
                if self.samples_dir.exists():
                    shutil.rmtree(self.samples_dir)
                self._cache = None
                self.version += 1
                self.fix_version += 1
            self.provenance.clear_imports()
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
