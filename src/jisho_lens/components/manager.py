"""Install and remove components, enforcing the rules:

- Nothing is installed by default.
- JMdict, KANJIDIC2 and Wiktionary need word splitting: they can only be installed while
  UniDic-lite or full UniDic is installed.
- Removing the last UniDic removes JMdict, KANJIDIC2 and Wiktionary too.
- Wiktionary's word-splitter list (user dictionary) is rebuilt whenever a UniDic or
  Wiktionary is installed, and deleted with its UniDic.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

from jisho_lens.components import builders, registry

log = logging.getLogger(__name__)
Progress = Callable[[str], None]

_PIP_PACKAGE = {"unidic-lite": "unidic-lite>=1.0.8", "unidic-full": "unidic>=1.1"}
_before_change: list[Callable[[], None]] = []


class ComponentError(RuntimeError):
    pass


def on_before_change(callback: Callable[[], None]) -> None:
    """Register a callback that releases open files (MeCab taggers, SQLite connections)
    before components are installed or removed."""
    _before_change.append(callback)


def _release() -> None:
    for cb in _before_change:
        try:
            cb()
        except Exception:  # noqa: BLE001
            log.exception("releasing component files failed")
    import gc

    gc.collect()


def _write_marker(component_id: str, **info) -> None:
    registry.marker(component_id).write_text(
        json.dumps({"installed": time.strftime("%Y-%m-%d %H:%M:%S"), **info}), encoding="utf-8")


def _rmtree(path) -> None:
    for attempt in range(5):
        try:
            shutil.rmtree(path)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 4:
                raise
            _release()
            time.sleep(0.5)


# ---------------------------------------------------------------- install
def install(component_id: str, progress: Progress = log.info) -> list[str]:
    """Install a component; returns the components that changed."""
    if component_id not in registry.COMPONENTS:
        raise ComponentError(f"unknown component {component_id!r}")
    if registry.is_installed(component_id):
        return []
    comp = registry.COMPONENTS[component_id]
    if comp.kind == "dictionary" and not registry.installed_unidics():
        raise ComponentError(f"{comp.name} needs word splitting: install UniDic-lite or "
                             "full UniDic first.")
    _release()
    registry.components_dir().mkdir(parents=True, exist_ok=True)
    if comp.kind == "unidic":
        _install_unidic(component_id, progress)
        mode = "lite" if component_id == "unidic-lite" else "full"
        if registry.is_installed("wiktionary"):
            builders.build_user_dictionary(mode, progress)
    else:
        target = registry.component_dir(component_id)
        _rmtree(target)  # leftovers of an interrupted install
        target.mkdir(parents=True)
        if component_id == "jmdict":
            n = builders.build_jmdict(progress)
        elif component_id == "kanjidic2":
            n = builders.build_kanjidic(progress)
        else:
            n = builders.build_wiktionary(progress)
        _write_marker(component_id, entries=n)
        if component_id in ("wiktionary", "jmdict"):
            _rebuild_user_dictionaries(progress)
    progress(f"{comp.name} installed.")
    return [component_id]


def _rebuild_user_dictionaries(progress: Progress) -> None:
    """The Wiktionary word-splitter list depends on the installed UniDics and on JMdict."""
    if not registry.is_installed("wiktionary"):
        return
    for mode, unidic in registry.MODE_COMPONENT.items():
        if registry.is_installed(unidic):
            builders.build_user_dictionary(mode, progress)


def _install_unidic(component_id: str, progress: Progress) -> None:
    target = registry.component_dir(component_id)
    staging = target.with_name(target.name + ".installing")
    _rmtree(staging)
    _rmtree(target)
    progress(f"Installing {registry.COMPONENTS[component_id].name} (pip)…")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
         "--target", str(staging), _PIP_PACKAGE[component_id]],
        check=True, capture_output=True, text=True)
    if component_id == "unidic-full":
        progress("Downloading the full UniDic dictionary (526 MB)…")
        env = dict(os.environ, PYTHONPATH=str(staging))
        subprocess.run([sys.executable, "-m", "unidic", "download"], check=True, env=env,
                       capture_output=True, text=True)
    staging.rename(target)
    if not (registry.unidic_package_dir(component_id) / "sys.dic").exists():
        _rmtree(target)
        raise ComponentError(f"{component_id}: dictionary files missing after install")
    _write_marker(component_id)


# ---------------------------------------------------------------- uninstall
def uninstall(component_id: str, progress: Progress = log.info) -> list[str]:
    """Remove a component; returns every component removed (removing the last UniDic
    also removes the dictionaries)."""
    if component_id not in registry.COMPONENTS:
        raise ComponentError(f"unknown component {component_id!r}")
    removed: list[str] = []
    _release()
    comp = registry.COMPONENTS[component_id]
    if registry.component_dir(component_id).exists():
        _rmtree(registry.component_dir(component_id))
        removed.append(component_id)
    if comp.kind == "dictionary":
        source = registry.sources_dir() / builders.URLS[component_id][0]
        source.unlink(missing_ok=True)
        if component_id == "jmdict" and removed:
            _rebuild_user_dictionaries(progress)
    else:
        mode = "lite" if component_id == "unidic-lite" else "full"
        registry.user_dictionary_path(mode).unlink(missing_ok=True)
        if not registry.installed_unidics():
            for dictionary in registry.DICTIONARIES:
                removed += uninstall(dictionary, progress)
    for c in removed:
        progress(f"{registry.COMPONENTS[c].name} removed.")
    return removed


def removal_effects(component_id: str) -> list[str]:
    """What else would be removed with this component (for a confirmation dialog)."""
    if registry.COMPONENTS[component_id].kind != "unidic":
        return []
    remaining = [u for u in registry.installed_unidics() if u != component_id]
    if remaining:
        return []
    return [d for d in registry.DICTIONARIES if registry.is_installed(d)]


def status() -> list[dict]:
    return [{"id": c.id, "name": c.name, "purpose": c.purpose, "size": c.size,
             "kind": c.kind, "installed": registry.is_installed(c.id)}
            for c in registry.COMPONENTS.values()]
