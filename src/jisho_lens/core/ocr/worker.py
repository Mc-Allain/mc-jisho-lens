"""Runs OCR on a background thread so the UI never freezes.

The engine is loaded once, in the background, when the app starts (or when the engine
setting changes), so the first capture doesn't pay the model loading time.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from PIL import Image
from PySide6.QtCore import QObject, QThread, Signal, Slot

from jisho_lens.core.analysis import Token, shared_analyzer
from jisho_lens.core.ocr import create_engine
from jisho_lens.core.ocr.base import OcrResult
from jisho_lens.core.ocr.cleanup import CleanText, clean
from jisho_lens.core.ocr.preprocess import apply

log = logging.getLogger(__name__)


@dataclass
class OcrJob:
    job_id: int
    image: Image.Image
    engine: str
    preset: str
    remove_key_icons: bool
    detect_speaker: bool


@dataclass
class OcrOutcome:
    job: OcrJob
    raw: OcrResult
    cleaned: CleanText
    tokens: list[list[Token]]  # one list of words per line of cleaned text
    seconds: float  # preprocessing + recognition + analysis


class _Worker(QObject):
    finished = Signal(object)  # OcrOutcome
    failed = Signal(int, str)  # job_id, message
    engine_ready = Signal(str, float)  # engine name, load seconds
    engine_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self._engines: dict = {}

    def _engine(self, name: str):
        if name not in self._engines:
            t0 = time.perf_counter()
            self._engines[name] = create_engine(name)
            log.info("OCR engine %s loaded in %.1fs", name, time.perf_counter() - t0)
        return self._engines[name]

    @Slot(str)
    def preload(self, name: str) -> None:
        t0 = time.perf_counter()
        try:
            shared_analyzer()  # load the word splitter too
        except Exception as exc:  # noqa: BLE001
            log.exception("loading the word splitter failed")
            self.engine_failed.emit("dictionary", str(exc))
        try:
            self._engine(name)
            self.engine_ready.emit(name, time.perf_counter() - t0)
        except Exception as exc:  # noqa: BLE001
            log.exception("loading OCR engine %s failed", name)
            self.engine_failed.emit(name, str(exc))

    @Slot(object)
    def run(self, job: OcrJob) -> None:
        try:
            t0 = time.perf_counter()
            engine = self._engine(job.engine)
            prepared = apply(job.image, job.preset)
            raw = engine.recognize(prepared)
            cleaned = clean(raw.lines, job.remove_key_icons, job.detect_speaker)
            tokens = shared_analyzer().analyze(cleaned.lines)
            seconds = time.perf_counter() - t0
            log.info("OCR job %d: %s/%s %.2fs, %d lines", job.job_id, job.engine, job.preset,
                     seconds, len(raw.lines))
            self.finished.emit(OcrOutcome(job, raw, cleaned, tokens, seconds))
        except Exception as exc:  # noqa: BLE001
            log.exception("OCR job %d failed", job.job_id)
            self.failed.emit(job.job_id, str(exc))


class OcrService(QObject):
    """GUI-thread facade. Call submit(); listen to finished / failed."""

    finished = Signal(object)
    failed = Signal(int, str)
    engine_ready = Signal(str, float)
    engine_failed = Signal(str, str)
    _submit = Signal(object)
    _preload = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self._thread = QThread()
        self._thread.setObjectName("ocr")
        self._worker = _Worker()
        self._worker.moveToThread(self._thread)
        self._submit.connect(self._worker.run)
        self._preload.connect(self._worker.preload)
        self._worker.finished.connect(self.finished)
        self._worker.failed.connect(self.failed)
        self._worker.engine_ready.connect(self.engine_ready)
        self._worker.engine_failed.connect(self.engine_failed)
        self._thread.start()
        self._next_id = 0

    def preload(self, engine: str) -> None:
        self._preload.emit(engine)

    def submit(self, image: Image.Image, engine: str, preset: str,
               remove_key_icons: bool = True, detect_speaker: bool = True) -> int:
        self._next_id += 1
        self._submit.emit(OcrJob(self._next_id, image, engine, preset, remove_key_icons,
                                 detect_speaker))
        return self._next_id

    def shutdown(self) -> None:
        self._thread.quit()
        self._thread.wait(5000)
