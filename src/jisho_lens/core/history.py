"""History of captures (SPEC §3.1 History, §5): history.db + PNG crops in captures/.

History is a convenience for the user (browse and reopen past captures) with a retention
limit. It is separate from OCR data collection (jisho_lens.core.ocr_data), which is opt-in.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from jisho_lens.core import paths

SCHEMA = """
CREATE TABLE IF NOT EXISTS captures (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at REAL NOT NULL,
  image_file TEXT NOT NULL,
  ocr_text TEXT NOT NULL,
  edited_text TEXT,
  speaker TEXT,
  engine TEXT,
  preset TEXT,
  seconds REAL,
  sample_id TEXT,           -- OCR data sample, when collection is on
  favorite INTEGER NOT NULL DEFAULT 0  -- favorites are not deleted until unfavorited
);
CREATE INDEX IF NOT EXISTS captures_created ON captures(created_at);
"""


@dataclass
class Capture:
    id: int
    created_at: float
    image_path: Path
    ocr_text: str
    edited_text: str | None
    speaker: str | None
    engine: str | None
    preset: str | None
    seconds: float | None
    sample_id: str | None
    favorite: bool = False

    @property
    def text(self) -> str:
        return self.edited_text if self.edited_text is not None else self.ocr_text

    @property
    def lines(self) -> list[str]:
        return [ln for ln in self.text.splitlines() if ln.strip()]

    def image(self) -> Image.Image:
        return Image.open(self.image_path)


class HistoryStore:
    def __init__(self, folder: Path | None = None) -> None:
        self.folder = folder or paths.data_dir()
        self.images = self.folder / "captures"
        self.images.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(self.folder / "history.db", check_same_thread=False)
        self._db.executescript(SCHEMA)
        cols = {r[1] for r in self._db.execute("PRAGMA table_info(captures)")}
        if "favorite" not in cols:  # History from before favorites
            self._db.execute(
                "ALTER TABLE captures ADD COLUMN favorite INTEGER NOT NULL DEFAULT 0")
            self._db.commit()
        self._lock = threading.Lock()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def add(self, image: Image.Image, ocr_text: str, speaker: str | None = None,
            engine: str | None = None, preset: str | None = None,
            seconds: float | None = None, sample_id: str | None = None,
            png: bytes | None = None, same_file: Path | None = None) -> int:
        """Add a capture. `same_file` is an existing PNG of exactly this image (the OCR data
        sample): it is shared through a hard link instead of being stored twice."""
        name = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.png"
        target = self.images / name
        linked = False
        if same_file is not None and same_file.exists():
            try:
                os.link(same_file, target)
                linked = True
            except OSError:
                pass
        if not linked:
            if png is not None:
                target.write_bytes(png)
            else:
                image.save(target)
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO captures (created_at, image_file, ocr_text, speaker, engine, "
                "preset, seconds, sample_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (time.time(), name, ocr_text, speaker, engine, preset, seconds, sample_id))
            self._db.commit()
            return int(cur.lastrowid)

    def update_ocr(self, capture_id: int, ocr_text: str, speaker: str | None, engine: str,
                   preset: str, seconds: float, sample_id: str | None) -> None:
        """A Retry read the same capture again: replace the OCR result, drop edits."""
        with self._lock:
            self._db.execute(
                "UPDATE captures SET ocr_text = ?, edited_text = NULL, speaker = ?, engine = ?, "
                "preset = ?, seconds = ?, sample_id = COALESCE(?, sample_id) WHERE id = ?",
                (ocr_text, speaker, engine, preset, seconds, sample_id, capture_id))
            self._db.commit()

    def set_edited(self, capture_id: int, text: str) -> None:
        with self._lock:
            self._db.execute("UPDATE captures SET edited_text = ? WHERE id = ?",
                             (text, capture_id))
            self._db.commit()

    def set_sample(self, capture_id: int, sample_id: str) -> None:
        with self._lock:
            self._db.execute("UPDATE captures SET sample_id = ? WHERE id = ?",
                             (sample_id, capture_id))
            self._db.commit()

    def set_favorite(self, capture_id: int, favorite: bool) -> None:
        with self._lock:
            self._db.execute("UPDATE captures SET favorite = ? WHERE id = ?",
                             (int(favorite), capture_id))
            self._db.commit()

    def favorite_sample_ids(self) -> set[str]:
        """OCR data samples of favorite captures (never deleted while favorited)."""
        with self._lock:
            rows = self._db.execute("SELECT sample_id FROM captures WHERE favorite = 1 AND "
                                    "sample_id IS NOT NULL").fetchall()
        return {r[0] for r in rows}

    def favorite_count(self) -> int:
        with self._lock:
            return self._db.execute(
                "SELECT COUNT(*) FROM captures WHERE favorite = 1").fetchone()[0]

    def remap_samples(self, mapping: dict[str, str]) -> None:
        """Point captures at the sample kept when duplicates were merged."""
        if not mapping:
            return
        with self._lock:
            self._db.executemany("UPDATE captures SET sample_id = ? WHERE sample_id = ?",
                                 [(new, old) for old, new in mapping.items()])
            self._db.commit()

    def _row(self, row) -> Capture:
        (cid, created, image_file, ocr, edited, speaker, engine, preset, seconds, sample,
         fav) = row
        return Capture(cid, created, self.images / image_file, ocr, edited, speaker, engine,
                       preset, seconds, sample, bool(fav))

    _COLUMNS = ("id, created_at, image_file, ocr_text, edited_text, speaker, engine, preset, "
                "seconds, sample_id, favorite")
    FILTERS = {"all": "", "favorites": "WHERE favorite = 1",
               "corrected": "WHERE edited_text IS NOT NULL"}

    def get(self, capture_id: int) -> Capture | None:
        with self._lock:
            row = self._db.execute(f"SELECT {self._COLUMNS} FROM captures WHERE id = ?",
                                   (capture_id,)).fetchone()
        return self._row(row) if row else None

    def list(self, limit: int = 500, show: str = "all") -> list[Capture]:
        """show: "all", "favorites" or "corrected" (fixed with Edit)."""
        where = self.FILTERS.get(show, "")
        with self._lock:
            rows = self._db.execute(
                f"SELECT {self._COLUMNS} FROM captures {where} "
                "ORDER BY created_at DESC, id DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    def count(self) -> int:
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM captures").fetchone()[0]

    def _delete_where(self, where: str, args: tuple = ()) -> list[Capture]:
        """Delete matching captures except favorites. Returns the deleted ones."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {self._COLUMNS} FROM captures WHERE favorite = 0 AND ({where})",
                args).fetchall()
            self._db.execute(f"DELETE FROM captures WHERE favorite = 0 AND ({where})", args)
            self._db.commit()
        gone = [self._row(r) for r in rows]
        for c in gone:
            c.image_path.unlink(missing_ok=True)
        return gone

    def delete(self, capture_id: int) -> bool:
        """Delete one capture. A favorite is not deleted (returns False)."""
        return bool(self._delete_where("id = ?", (capture_id,)))

    def delete_many(self, capture_ids) -> list[Capture]:
        ids = [int(i) for i in capture_ids]
        if not ids:
            return []
        return self._delete_where(f"id IN ({','.join('?' * len(ids))})", tuple(ids))

    def delete_range(self, start: float, end: float) -> list[Capture]:
        """Delete captures taken from `start` to `end` (Unix times, inclusive)."""
        return self._delete_where("created_at >= ? AND created_at <= ?", (start, end))

    def count_range(self, start: float, end: float) -> tuple[int, int]:
        """(captures that would be deleted, favorites kept) in the time range."""
        with self._lock:
            rows = self._db.execute(
                "SELECT favorite, COUNT(*) FROM captures WHERE created_at >= ? AND "
                "created_at <= ? GROUP BY favorite", (start, end)).fetchall()
        counts = dict(rows)
        return counts.get(0, 0), counts.get(1, 0)

    def delete_all(self) -> list[Capture]:
        """Delete every capture except favorites. Returns the deleted ones."""
        return self._delete_where("1 = 1")

    def enforce_retention(self, keep_last: int) -> int:
        """Keep only the newest `keep_last` captures (0 = keep all). Returns deletions.

        Favorites do not count towards the limit and are never deleted here.
        """
        if keep_last <= 0:
            return 0
        with self._lock:
            old = self._db.execute(
                "SELECT id FROM captures WHERE favorite = 0 "
                "ORDER BY created_at DESC, id DESC LIMIT -1 OFFSET ?",
                (keep_last,)).fetchall()
        for (cid,) in old:
            self.delete(cid)
        return len(old)
