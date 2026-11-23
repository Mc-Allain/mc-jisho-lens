"""Where your OCR data came from: pack names, versions, history logs and the "Using:" label.

- Every exported or merged pack has a name you choose (e.g. RavenOCR) and a version that
  goes up with each release (RavenOCR v1, v2, ...). series.json remembers your names and
  their last versions (kept when collected data is deleted, so versions keep counting).
- Every pack carries a history log: one line per release since its first version, with the
  contributor ID, what it was made from, and how many samples. Logs of packs it was made
  from come along.
- imports.json records each pack you imported: which samples you used and which you
  declined (unticked, or Keep mine). The "Using:" label is computed from that and from what
  is in your data now: "KaiOCR v4 (partial) + RavenOCR v2 + own data".
"""

from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import asdict, dataclass, field
from hashlib import sha256
from pathlib import Path

MAX_NAME = 40
MAX_LOG = 300
_BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def clean_name(name: str) -> str:
    """A pack name usable in a file name: no path or reserved characters, max 40 chars."""
    name = _BAD.sub("", " ".join(str(name).split())).strip(" .")
    return name[:MAX_NAME]


def file_name(name: str, version: int) -> str:
    return f"{clean_name(name).replace(' ', '-')}-v{version}.zip"


# ---------------------------------------------------------------- history log
@dataclass
class LogEntry:
    name: str
    version: int
    date: str
    contributor: str
    action: str  # "exported" | "merged"
    sources: str  # e.g. "RavenOCR v1 + own data"
    samples: int
    categories: str = ""  # "Categories: Azur Promilia JP 40, none 3"

    @property
    def key(self) -> tuple:
        return (self.contributor, self.name, self.version, self.action)

    def line(self) -> str:
        return (f"{self.name} v{self.version} · {self.date[:10]} · by {self.contributor[:8]} · "
                f"{self.action}: {self.sources or '—'} · {self.samples} samples"
                + (f" · {self.categories}" if self.categories else ""))

    @classmethod
    def from_dict(cls, d) -> LogEntry | None:
        try:
            return cls(name=clean_name(d["name"]) or "?", version=int(d["version"]),
                       date=str(d.get("date", ""))[:19],
                       contributor=str(d.get("contributor", ""))[:32],
                       action=str(d.get("action", "exported"))[:16],
                       sources=str(d.get("sources", ""))[:500],
                       samples=int(d.get("samples", 0)),
                       categories=str(d.get("categories", ""))[:500])
        except (KeyError, TypeError, ValueError):
            return None


def merge_logs(*logs: list[LogEntry]) -> list[LogEntry]:
    """Logs combined, newest first, each release once."""
    seen, out = set(), []
    for entry in sorted((e for log in logs for e in log), key=lambda e: e.date, reverse=True):
        if entry.key not in seen:
            seen.add(entry.key)
            out.append(entry)
    return out[:MAX_LOG]


def parse_log(raw) -> list[LogEntry]:
    if not isinstance(raw, list):
        return []
    return [e for e in (LogEntry.from_dict(d) for d in raw[:MAX_LOG] if isinstance(d, dict))
            if e is not None]


# ---------------------------------------------------------------- pack identity
@dataclass
class PackInfo:
    """Name, version and history of a pack (from its manifest)."""

    pack_id: str
    name: str | None  # None: made before packs had names
    version: int
    contributor: str
    sources: str
    log: list[LogEntry]
    file: str

    @property
    def label(self) -> str:
        return f"{self.name} v{self.version}" if self.name else Path(self.file).stem

    @property
    def has_history(self) -> bool:
        return self.name is not None

    def history_text(self) -> str:
        if not self.log:
            return "No history (made before packs had names and logs)."
        return "\n".join(e.line() for e in self.log)

    @classmethod
    def from_manifest(cls, manifest: dict, file: str, sample_ids) -> PackInfo:
        name = manifest.get("name")
        name = clean_name(name) if isinstance(name, str) and clean_name(name) else None
        try:
            version = max(1, int(manifest.get("series_version", 1)))
        except (TypeError, ValueError):
            version = 1
        pack_id = manifest.get("pack_id")
        if not isinstance(pack_id, str) or not re.fullmatch(r"[0-9a-f]{8,64}", pack_id):
            # older packs: identified by their samples
            pack_id = "s" + sha256("".join(sorted(sample_ids)).encode()).hexdigest()[:31]
        return cls(pack_id=pack_id, name=name, version=version,
                   contributor=str(manifest.get("contributor", ""))[:32],
                   sources=str(manifest.get("sources", ""))[:500],
                   log=parse_log(manifest.get("log")), file=Path(file).name)


# ---------------------------------------------------------------- local records
@dataclass
class ImportRecord:
    pack_id: str
    label: str
    contributor: str
    file: str
    imported: str
    used: list[str] = field(default_factory=list)  # sample ids used from this pack
    declined: list[str] = field(default_factory=list)  # unticked, or Keep mine
    log: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict) -> ImportRecord:
        known = set(cls.__dataclass_fields__)
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class PackUse:
    """How much of an imported pack is in your data now."""

    record: ImportRecord
    present: int  # used samples still in your data
    used: int
    declined: int

    @property
    def partial(self) -> bool:
        return self.declined > 0 or self.present < self.used

    @property
    def label(self) -> str:
        return self.record.label + (" (partial)" if self.partial else "")

    def detail(self) -> str:
        n = self.present
        text = (f"{self.label} by {self.record.contributor[:8]}: {n} "
                f"sample{'s' if n != 1 else ''} used")
        reasons = []
        if self.declined:
            reasons.append(f"{self.declined} not used by your choice")
        if self.present < self.used:
            reasons.append(f"{self.used - self.present} deleted since")
        return text + (f" ({', '.join(reasons)})" if reasons else "")


class Provenance:
    def __init__(self, folder: Path) -> None:
        self.folder = Path(folder)
        self._lock = threading.Lock()

    # ---------- files ----------
    def _read(self, name: str, default):
        try:
            return json.loads((self.folder / name).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, name: str, data) -> None:
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.folder / (name + ".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.folder / name)

    # ---------- your pack names and versions ----------
    def last_name(self) -> str:
        return str(self._read("series.json", {}).get("last_name", ""))

    def next_version(self, name: str) -> int:
        series = self._read("series.json", {}).get("series", {})
        return int(series.get(clean_name(name), {}).get("version", 0)) + 1

    def series_log(self, name: str) -> list[LogEntry]:
        series = self._read("series.json", {}).get("series", {})
        return parse_log(series.get(clean_name(name), {}).get("log"))

    def record_release(self, entry: LogEntry) -> None:
        data = self._read("series.json", {})
        series = data.setdefault("series", {})
        s = series.setdefault(entry.name, {"version": 0, "log": []})
        s["version"] = max(int(s.get("version", 0)), entry.version)
        s["log"] = [asdict(e) for e in merge_logs([entry], parse_log(s.get("log")))]
        data["last_name"] = entry.name
        self._write("series.json", data)

    # ---------- imported packs ----------
    def records(self) -> list[ImportRecord]:
        raw = self._read("imports.json", {}).get("imports", [])
        out = []
        for d in raw if isinstance(raw, list) else []:
            try:
                out.append(ImportRecord.from_dict(d))
            except TypeError:
                continue
        return out

    def record_import(self, info: PackInfo, used: list[str], declined: list[str]) -> None:
        records = self.records()
        rec = next((r for r in records if r.pack_id == info.pack_id), None)
        if rec is None:
            rec = ImportRecord(info.pack_id, info.label, info.contributor, info.file,
                               time.strftime("%Y-%m-%dT%H:%M:%S"))
            records.append(rec)
        rec.used = sorted(set(rec.used) | set(used))
        rec.declined = sorted((set(rec.declined) | set(declined)) - set(rec.used))
        rec.log = [asdict(e) for e in info.log]
        rec.imported = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._write("imports.json", {"imports": [asdict(r) for r in records]})

    def clear_imports(self) -> None:
        with self._lock:
            (self.folder / "imports.json").unlink(missing_ok=True)

    # ---------- the "Using:" label ----------
    def uses(self, sample_ids: set[str]) -> list[PackUse]:
        out = []
        for rec in sorted(self.records(), key=lambda r: r.imported):
            present = sum(sid in sample_ids for sid in rec.used)
            if present:
                out.append(PackUse(rec, present, len(rec.used), len(rec.declined)))
        return out

    def used_logs(self, sample_ids: set[str]) -> list[LogEntry]:
        return merge_logs(*(parse_log(u.record.log) for u in self.uses(sample_ids)))


def using_label(uses: list[PackUse], own: bool, max_packs: int = 2) -> str:
    """'KaiOCR v4 (partial) + RavenOCR v2 + own data'; long lists are shortened."""
    parts = [u.label for u in uses]
    if len(parts) > max_packs + 1:
        more = len(parts) - max_packs
        parts = parts[:max_packs] + [f"{more} more packs"]
    if own:
        parts.append("own data")
    return " + ".join(parts) if parts else "no data yet"
