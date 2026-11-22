"""User settings stored as TOML (SPEC §3.1 Settings, §5)."""

from __future__ import annotations

import logging
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w

from jisho_lens.core import paths

log = logging.getLogger(__name__)


@dataclass
class OcrSettings:
    engine: str = "rapid-v6"
    preset: str = "none"
    use_gpu: bool = False


@dataclass
class AnalysisSettings:
    # "none" (plain text, default) | "lite" | "full": which installed UniDic splits words.
    # The dictionaries (JMdict, KANJIDIC2, Wiktionary) are used whenever they are installed,
    # and need word splitting. See jisho_lens.components.
    word_splitting: str = "none"

    @property
    def dictionary_active(self) -> bool:
        return self.word_splitting != "none"


@dataclass
class CaptureSettings:
    hotkey: str = "Ctrl+Alt+J"
    delay_seconds: float = 0.0
    remove_key_icons: bool = True
    detect_speaker: bool = True


@dataclass
class HistorySettings:
    enabled: bool = True
    keep_last: int = 200  # captures kept in History (0 = no limit)


@dataclass
class DataSettings:
    """OCR data collection: off until the user agrees (SPEC: opt-in, local only)."""

    collect: str = "ask"  # "ask" (not answered yet) | "yes" | "no"
    game: str = ""  # optional game name stored with collected samples
    max_mb: int = 300  # space for samples (0 = no limit); corrected ones are always kept

    @property
    def collecting(self) -> bool:
        return self.collect == "yes"


@dataclass
class WindowSettings:
    # x, y, width, height in Qt logical pixels; empty = place automatically
    geometry: list[int] = field(default_factory=list)
    font_size: int = 22
    show_furigana: bool = True
    show_romaji: bool = False


@dataclass
class Settings:
    capture: CaptureSettings = field(default_factory=CaptureSettings)
    ocr: OcrSettings = field(default_factory=OcrSettings)
    analysis: AnalysisSettings = field(default_factory=AnalysisSettings)
    window: WindowSettings = field(default_factory=WindowSettings)
    history: HistorySettings = field(default_factory=HistorySettings)
    data: DataSettings = field(default_factory=DataSettings)

    @classmethod
    def load(cls, path: Path | None = None) -> Settings:
        path = path or paths.settings_file()
        settings = cls()
        if not path.exists():
            return settings
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError) as exc:
            log.warning("could not read %s (%s); using defaults", path, exc)
            return settings
        for section in fields(cls):
            values = data.get(section.name, {})
            target = getattr(settings, section.name)
            for f in fields(target):
                if f.name in values:
                    default = getattr(target, f.name)
                    value = values[f.name]
                    # keep the default when the stored type is wrong
                    if isinstance(default, float) and isinstance(value, int):
                        value = float(value)
                    if type(value) is type(default):
                        setattr(target, f.name, value)
        return settings

    def save(self, path: Path | None = None) -> None:
        path = path or paths.settings_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(tomli_w.dumps(asdict(self)), encoding="utf-8")
        tmp.replace(path)
