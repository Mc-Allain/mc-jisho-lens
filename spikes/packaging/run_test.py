"""Packaging test: bundled Python runtime + installing a module after "installation".

Run:  uv run python spikes/packaging/run_test.py

Steps (all under spikes/packaging/out/):
 1. Build the dummy module wheel and compute its SHA-256.
 2. "Install" the app: copy the managed CPython 3.12 runtime + app code to install/.
    The runtime is copied, not referenced, to prove it is relocatable.
 3. Run the installed app with no modules.
 4. Install the module through the app (checksum verified, deps go to the module folder).
 5. Run the app again -> module and its third-party dependency load.
 6. Try installing with a wrong checksum -> must be refused.
 7. Uninstall -> app runs with no modules again.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "out"
UV = [sys.executable, "-m", "uv"] if shutil.which("uv") is None else ["uv"]


def run(cmd, env=None, check=True):
    print("$", " ".join(str(c) for c in cmd))
    p = subprocess.run(cmd, env=env, capture_output=True, text=True, encoding="utf-8")
    print(p.stdout.rstrip())
    if p.stderr.strip():
        print(p.stderr.rstrip())
    if check and p.returncode != 0:
        raise SystemExit(f"failed ({p.returncode})")
    return p


def find_runtime() -> Path:
    base_python = subprocess.run(
        ["python", "-m", "uv", "python", "find", "3.12", "--no-project"],
        capture_output=True, text=True, check=True, cwd=Path.home(),
    ).stdout.strip()
    return Path(base_python).resolve().parent


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def main() -> int:
    if OUT.exists():
        shutil.rmtree(OUT)
    (OUT / "wheels").mkdir(parents=True)

    # 1. module wheel
    run(["python", "-m", "uv", "build", "--wheel", "--out-dir", str(OUT / "wheels"),
         str(HERE / "hello_module")])
    wheel = next((OUT / "wheels").glob("*.whl"))
    sha = hashlib.sha256(wheel.read_bytes()).hexdigest()
    print(f"wheel {wheel.name} sha256={sha}")

    # 2. install app
    install = OUT / "install"
    runtime_src = find_runtime()
    shutil.copytree(runtime_src, install / "runtime")
    shutil.copytree(HERE / "app", install / "app")
    py = install / "runtime" / "python.exe"
    print(f"runtime copied from {runtime_src} ({dir_size(install / 'runtime') / 1e6:.0f} MB)")

    env = dict(os.environ, JL_SPIKE_DATA=str(OUT / "localappdata"), PYTHONNOUSERSITE="1")
    # -X utf8: without it, Japanese text crashes print() when output is piped (cp1252).
    app = [str(py), "-I", "-X", "utf8", str(install / "app" / "spike_app.py")]

    # 3-7
    run(app + ["list"], env)
    run(app + ["install", str(wheel), sha], env)
    out = run(app + ["list"], env).stdout
    assert "loaded module hello" in out and "1.5 MB" in out, "module did not load"
    bad = run(app + ["install", str(wheel), "0" * 64], env, check=False)
    assert bad.returncode != 0 and "checksum mismatch" in (bad.stdout + bad.stderr)
    run(app + ["uninstall", "hello"], env)

    print("\nPACKAGING TEST PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
