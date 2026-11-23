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


def relink_captures(history: HistoryStore, data: OcrDataStore,
                    capture_ids=None) -> tuple[int, int]:
    """Repair links where a History capture shows a different right text than the OCR data
    sample it is linked to (captures of a sentence used to be linked to the first matching
    sample, whatever its answer).

    For each such capture: link it to a sample whose answer is the capture's text; if there
    is none and the capture is a favorite or was edited (its text is your answer), keep its
    own picture as a sample with that answer and link it. `capture_ids`: only these
    captures (e.g. one just starred). Returns (relinked, created)."""
    import time

    from jisho_lens.core.ocr_data.store import Sample, _key, sample_id

    samples = data.all()
    by_answer: dict[str, Sample] = {}
    for s in samples:
        if s.truth:
            by_answer.setdefault(_key(s.truth), s)
    relinked = created = 0
    for c in history.list(limit=1_000_000):
        if capture_ids is not None and c.id not in capture_ids:
            continue
        s = data.get(c.sample_id) if c.sample_id else None
        if s is None or s.truth is None:
            continue
        text = c.text
        if not _key(text) or _key(s.truth) == _key(text):
            continue
        better = by_answer.get(_key(text))
        if better is not None:
            history.set_sample(c.id, better.id)
            relinked += 1
            continue
        if not (c.favorite or c.edited_text is not None) or not c.image_path.exists():
            continue
        png = c.image_path.read_bytes()
        sid = sample_id(png)
        if data.get(sid) is None:
            own = Sample(id=sid, ocr_text=s.ocr_text, engine=c.engine or s.engine,
                         preset=c.preset or s.preset, seconds=c.seconds, speaker=c.speaker,
                         text_type="dialogue" if c.speaker else "text",
                         created=time.strftime("%Y-%m-%dT%H:%M:%S",
                                               time.localtime(c.created_at)),
                         contributor=data.contributor(), truth=text, truth_source="edited",
                         source_pack_id="")
            data.save(own, png)
            by_answer[_key(text)] = own
            created += 1
        else:
            data.set_truth(sid, text, "edited")
        history.set_sample(c.id, sid)
        relinked += 1
    return relinked, created
