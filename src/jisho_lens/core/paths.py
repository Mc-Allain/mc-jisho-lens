"""Where the app keeps its files (SPEC §5)."""

from __future__ import annotations

import os
from pathlib import Path

APP_DIR_NAME = "mc-jisho-lens"


def _env_dir(var: str, fallback: Path) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else fallback


def config_dir() -> Path:
    """%APPDATA%\\mc-jisho-lens (settings). JISHO_LENS_HOME overrides both dirs (tests)."""
    if home := os.environ.get("JISHO_LENS_HOME"):
        return Path(home) / "config"
    return _env_dir("APPDATA", Path.home() / "AppData" / "Roaming") / APP_DIR_NAME


def data_dir() -> Path:
    """%LOCALAPPDATA%\\mc-jisho-lens (history, captures, modules, logs)."""
    if home := os.environ.get("JISHO_LENS_HOME"):
        return Path(home) / "data"
    return _env_dir("LOCALAPPDATA", Path.home() / "AppData" / "Local") / APP_DIR_NAME


def settings_file() -> Path:
    return config_dir() / "settings.toml"


def logs_dir() -> Path:
    return data_dir() / "logs"
