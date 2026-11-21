"""Phase 0 capture test.

Run:  uv run python tools/capture_test.py [--delay SECONDS]

1. Waits --delay seconds (default 3) so you can switch to the window you want to capture.
2. Takes a full-desktop screenshot and shows it frozen and dimmed on every monitor.
3. Drag a rectangle (Esc or right-click cancels).
4. Saves tools/out/capture-<time>-frozen.png (crop of the frozen screenshot) and
   tools/out/capture-<time>-live.png (fresh grab of the same rectangle), and prints
   the rectangle and whether the two images are identical.

Identical images mean the overlay's coordinates map exactly to physical screen pixels.
(If something on screen moved in between, small differences are expected.)
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from PIL import ImageChops
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from jisho_lens.core.capture import Rect, grab_desktop, grab_rect  # noqa: E402
from jisho_lens.core.displays import (  # noqa: E402
    describe_displays,
    enable_per_monitor_dpi_awareness,
)
from jisho_lens.ui.capture_overlay import CaptureOverlay  # noqa: E402

OUT = ROOT / "tools" / "out"


def simulate_drag(overlay: CaptureOverlay, spec: str) -> None:
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest

    x, y, w, h = (int(v) for v in spec.split(","))
    win = overlay._windows[0]
    QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x, y))
    QTest.mouseMove(win, QPoint(x + w // 2, y + h // 2))
    QTest.mouseMove(win, QPoint(x + w, y + h))
    QTest.mouseRelease(
        win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, QPoint(x + w, y + h)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=3.0)
    parser.add_argument(
        "--auto",
        metavar="X,Y,W,H",
        help="simulate a drag on the primary monitor (logical widget coords) instead of waiting",
    )
    args = parser.parse_args()

    enable_per_monitor_dpi_awareness()
    app = QApplication(sys.argv)
    print(describe_displays())
    print(f"Capturing in {args.delay:g} s...")

    result: dict = {}

    def done(rect: Rect | None) -> None:
        result["rect"] = rect
        app.quit()

    def start() -> None:
        shot = grab_desktop()
        result["shot"] = shot
        overlay = CaptureOverlay(shot, done)
        result["overlay"] = overlay
        overlay.show()
        if args.auto:
            QTimer.singleShot(500, lambda: simulate_drag(overlay, args.auto))

    QTimer.singleShot(int(args.delay * 1000), start)
    app.exec()

    rect = result.get("rect")
    if rect is None:
        print("Cancelled.")
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    frozen = result["shot"].crop(rect)
    live = grab_rect(rect)
    frozen_path = OUT / f"capture-{stamp}-frozen.png"
    live_path = OUT / f"capture-{stamp}-live.png"
    frozen.save(frozen_path)
    live.save(live_path)

    same = 0.0
    if frozen.size == live.size:
        diff = ImageChops.difference(frozen, live).convert("L")
        hist = diff.histogram()
        same = hist[0] / (frozen.size[0] * frozen.size[1]) * 100
    print(f"Selection (physical px): left={rect.left} top={rect.top} {rect.width}x{rect.height}")
    print(f"Frozen crop: {frozen.size}, live grab: {live.size}, identical pixels: {same:.1f}%")
    print("(Below 100% is expected if anything in the area moved, e.g. a video.)")
    print(f"Saved: {frozen_path}\n       {live_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
