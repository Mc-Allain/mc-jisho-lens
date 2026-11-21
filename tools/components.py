"""Install or remove optional components from the command line (same as Settings >
Components in the app).

  uv run python tools/components.py                      # status
  uv run python tools/components.py install unidic-lite jmdict kanjidic2 wiktionary
  uv run python tools/components.py uninstall wiktionary

Components: unidic-lite, unidic-full (word splitting), jmdict, kanjidic2, wiktionary
(dictionaries; need a UniDic). Removing the last UniDic also removes the dictionaries.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jisho_lens import components  # noqa: E402


def show_status() -> None:
    print(f"Components folder: {components.components_dir()}\n")
    for c in components.status():
        mark = "installed" if c["installed"] else "-"
        print(f"  {c['id']:12s} {mark:10s} {c['name']}: {c['purpose']} ({c['size']})")


def main(argv: list[str]) -> int:
    if not argv or argv[0] == "status":
        show_status()
        return 0
    action, names = argv[0], argv[1:]
    if action not in ("install", "uninstall") or not names:
        print(__doc__)
        return 2
    # install word splitting before dictionaries, remove dictionaries before word splitting
    order = list(components.UNIDICS) + list(components.DICTIONARIES)
    names = sorted(names, key=lambda n: order.index(n) if n in order else -1,
                   reverse=action == "uninstall")
    for name in names:
        try:
            if action == "install":
                components.install(name, progress=print)
            else:
                removed = components.uninstall(name, progress=print)
                if not removed:
                    print(f"{name} was not installed.")
        except components.ComponentError as exc:
            print(f"error: {exc}")
            return 1
    print()
    show_status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
