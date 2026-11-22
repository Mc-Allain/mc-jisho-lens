"""Space used by History and OCR data, and the deletions that span both."""

from __future__ import annotations

import os
from hashlib import sha256

from jisho_lens.core.history import HistoryStore
from jisho_lens.core.ocr_data.corrections import CorrectionStore
from jisho_lens.core.ocr_data.store import OcrDataStore


def share_identical_images(history: HistoryStore, data: OcrDataStore) -> int:
    """Replace History crops that are byte-identical to their OCR sample with a hard link,
    so the image is stored once. Returns how many were shared."""
    shared = 0
    for c in history.list(limit=1_000_000):
        if not c.sample_id:
            continue
        sample_png = data.png_path(c.sample_id)
        if not (sample_png.exists() and c.image_path.exists()):
            continue
        try:
            if os.path.samefile(sample_png, c.image_path):
                continue
            if sha256(c.image_path.read_bytes()).hexdigest() != c.sample_id:
                continue
            tmp = c.image_path.with_suffix(".link")
            tmp.unlink(missing_ok=True)
            os.link(sample_png, tmp)
            os.replace(tmp, c.image_path)
            shared += 1
        except OSError:
            continue
    return shared


def clear_all(history: HistoryStore, data: OcrDataStore,
              corrections: CorrectionStore) -> tuple[int, int, int]:
    """Clear all: History, collected OCR data and learned corrections. Favorites and their
    samples stay. Returns (captures, samples, favorites kept)."""
    keep = history.favorite_sample_ids()
    kept = history.favorite_count()
    captures = len(history.delete_all())
    samples = data.delete_all(keep)
    corrections.delete_all()
    return captures, samples, kept
