"""Logging to %LOCALAPPDATA%\\mc-jisho-lens\\logs\\app.log (rotating) and stderr."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from jisho_lens.core import paths


def setup_logging(level: int = logging.INFO) -> None:
    # Japanese text in log output must never crash the app (cp1252 consoles).
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    file_handler = RotatingFileHandler(
        paths.logs_dir() / "app.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(file_handler)
    if sys.stderr is not None:
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        root.addHandler(console)
