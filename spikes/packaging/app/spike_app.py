"""Minimal stand-in for Jisho Lens used by the packaging test.

  python spike_app.py list                     -> load and run installed modules
  python spike_app.py install <wheel> <sha256> -> verify checksum, install module + its deps
  python spike_app.py uninstall <module-id>

Modules live in <data>/modules/<id>/ with module.toml and their own site-packages/.
<data> is %JL_SPIKE_DATA% (the test points it at a temp folder instead of %LOCALAPPDATA%).
"""

from __future__ import annotations

import hashlib
import importlib
import os
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

DATA = Path(os.environ.get("JL_SPIKE_DATA", Path(os.environ["LOCALAPPDATA"]) / "mc-jisho-lens"))
MODULES = DATA / "modules"


class Context:
    def __init__(self) -> None:
        self.popup_actions: list[tuple[str, object]] = []

    def add_popup_action(self, label: str, callback) -> None:
        self.popup_actions.append((label, callback))


def load_modules() -> Context:
    ctx = Context()
    if not MODULES.exists():
        print("no modules installed")
        return ctx
    for folder in sorted(p for p in MODULES.iterdir() if p.is_dir()):
        manifest = tomllib.loads((folder / "module.toml").read_text(encoding="utf-8"))
        sys.path.insert(0, str(folder / "site-packages"))
        mod_name, cls_name = manifest["entry_point"].split(":")
        module = importlib.import_module(mod_name)
        getattr(module, cls_name)().register(ctx)
        print(f"loaded module {manifest['id']} {manifest['version']}")
    return ctx


def install(wheel: Path, sha256: str) -> None:
    digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
    if digest != sha256:
        raise SystemExit(f"checksum mismatch: {digest} != {sha256}")
    with zipfile.ZipFile(wheel) as zf:
        manifest_name = next(n for n in zf.namelist() if n.endswith("/module.toml"))
        manifest = tomllib.loads(zf.read(manifest_name).decode("utf-8"))
    target = MODULES / manifest["id"]
    if target.exists():
        shutil.rmtree(target)
    site = target / "site-packages"
    site.mkdir(parents=True)
    # Install the module wheel and its dependencies into the module's own folder,
    # using the app's bundled Python (sys.executable).
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
         "--target", str(site), str(wheel)],
        check=True,
    )
    (target / "module.toml").write_text(
        (site / manifest_name).read_text(encoding="utf-8"), encoding="utf-8"
    )
    print(f"installed module {manifest['id']} into {target}")


def uninstall(module_id: str) -> None:
    shutil.rmtree(MODULES / module_id)
    print(f"uninstalled {module_id}")


def main(argv: list[str]) -> int:
    print(f"python: {sys.executable} ({sys.version.split()[0]})")
    cmd = argv[0] if argv else "list"
    if cmd == "install":
        install(Path(argv[1]), argv[2])
    elif cmd == "uninstall":
        uninstall(argv[1])
    ctx = load_modules()
    for label, callback in ctx.popup_actions:
        print(f"popup action {label!r} -> {callback('今日')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
