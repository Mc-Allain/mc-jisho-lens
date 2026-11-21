"""The optional components and where they live.

Nothing is installed by default. Each component installs into its own folder under
components_dir() (the same idea as modules in Phase 7):

  unidic-lite / unidic-full   word splitting (UniDic for MeCab), installed with pip --target
  jmdict / kanjidic2 / wiktionary   dictionaries, built into one SQLite file each

The dictionaries need word splitting: they can only be installed while a UniDic is
installed, and are removed automatically when the last UniDic is removed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from jisho_lens.core import paths


@dataclass(frozen=True)
class Component:
    id: str
    name: str
    purpose: str
    size: str
    kind: str  # "unidic" | "dictionary"


COMPONENTS: dict[str, Component] = {c.id: c for c in [
    Component("unidic-lite", "UniDic-lite",
              "Word splitting: clickable words, readings, furigana, romaji, grammar",
              "249 MB", "unidic"),
    Component("unidic-full", "Full UniDic",
              "Word splitting, slightly more accurate than UniDic-lite",
              "775 MB (526 MB download)", "unidic"),
    Component("jmdict", "JMdict (English)",
              "Word meanings, common-word marks, dictionary-based split fixes",
              "62 MB (10.6 MB download)", "dictionary"),
    Component("kanjidic2", "KANJIDIC2",
              "Kanji details: readings, meanings, strokes; coined-word reading guesses",
              "2 MB (1.5 MB download)", "dictionary"),
    Component("wiktionary", "Wiktionary",
              "Words JMdict lacks (dialect, slang, newer words such as じっちゃ)",
              "25 MB (48.6 MB download)", "dictionary"),
]}
UNIDICS = ("unidic-lite", "unidic-full")
DICTIONARIES = ("jmdict", "kanjidic2", "wiktionary")
# word-splitting mode name used in Settings -> component id
MODE_COMPONENT = {"lite": "unidic-lite", "full": "unidic-full"}


def components_dir() -> Path:
    """JISHO_LENS_COMPONENTS, else <repo>/data/components when running from source,
    else %LOCALAPPDATA%\\mc-jisho-lens\\components."""
    if env := os.environ.get("JISHO_LENS_COMPONENTS"):
        return Path(env)
    repo_data = Path(__file__).resolve().parents[3] / "data"
    if (repo_data.parent / "pyproject.toml").exists():
        return repo_data / "components"
    return paths.data_dir() / "components"


def component_dir(component_id: str) -> Path:
    return components_dir() / component_id


def sources_dir() -> Path:
    return components_dir() / "_downloads"


def marker(component_id: str) -> Path:
    """Written last when an install finishes; a folder without it is incomplete."""
    return component_dir(component_id) / "installed.json"


def is_installed(component_id: str) -> bool:
    return marker(component_id).exists()


def installed() -> list[str]:
    return [c for c in COMPONENTS if is_installed(c)]


def installed_unidics() -> list[str]:
    return [c for c in UNIDICS if is_installed(c)]


def database_path(component_id: str) -> Path:
    """SQLite file of a dictionary component."""
    return component_dir(component_id) / f"{component_id}.sqlite"


def unidic_package_dir(component_id: str) -> Path:
    """Folder holding the UniDic dictionary files (sys.dic, mecabrc, ...)."""
    package = "unidic_lite" if component_id == "unidic-lite" else "unidic"
    return component_dir(component_id) / package / "dicdir"


def user_dictionary_path(mode: str) -> Path:
    """MeCab user dictionary of Wiktionary nouns, built for one UniDic."""
    return component_dir("wiktionary") / f"userdic-{mode}.dic"
