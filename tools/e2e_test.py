"""End-to-end check of the Phase 1 app, no user input needed.

Run:  uv run python -X utf8 tools/e2e_test.py [IMAGE]

Shows IMAGE (default: a synthetic dialogue sample) on screen, starts a capture exactly like
the hotkey does, simulates dragging around the image, waits for OCR and prints what the main
window shows. Also checks that the main window is hidden from screenshots.
Uses a temporary settings/data folder, so your real settings are untouched.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
os.environ["JISHO_LENS_HOME"] = tempfile.mkdtemp(prefix="jisho-e2e-")

from PIL import Image, ImageChops  # noqa: E402
from PySide6.QtCore import QPoint, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

from jisho_lens.app import JishoLens  # noqa: E402
from jisho_lens.core.capture import Rect, grab_rect  # noqa: E402
from jisho_lens.core.displays import enable_per_monitor_dpi_awareness  # noqa: E402
from jisho_lens.core.logs import setup_logging  # noqa: E402
from jisho_lens.core.ocr.metrics import char_accuracy  # noqa: E402

SAMPLE = ROOT / "tools" / "out" / "synthetic" / "dialogue-dark__01.png"
X, Y = 200, 250


def main() -> int:
    image_path = Path(sys.argv[1]) if len(sys.argv) > 1 else SAMPLE
    truth_path = image_path.with_suffix(".txt")
    enable_per_monitor_dpi_awareness()
    setup_logging()
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    lens = JishoLens(app)
    result: dict = {}

    label = QLabel()
    label.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
                         | Qt.WindowType.Tool)
    pm = QPixmap(str(image_path))
    label.setPixmap(pm)
    label.move(X, Y)
    label.show()
    w, h = pm.width(), pm.height()

    def capture() -> None:
        result["t0"] = time.perf_counter()
        lens.start_capture()
        QTimer.singleShot(400, drag)

    def drag() -> None:
        win = lens._overlay._windows[0]
        QTest.mousePress(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                         QPoint(X - 4, Y - 4))
        QTest.mouseMove(win, QPoint(X + w // 2, Y + h // 2))
        QTest.mouseRelease(win, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                           QPoint(X + w + 4, Y + h + 4))
        result["selected"] = time.perf_counter()

    out_dir = ROOT / "tools" / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    def on_done(outcome) -> None:
        result["outcome"] = outcome
        result["t1"] = time.perf_counter()
        QTimer.singleShot(1500, click_word)

    def click_word() -> None:
        lens.window.grab().save(str(out_dir / "e2e-1-text.png"))
        js = ("(() => { const ws = document.querySelectorAll('.w'); if (!ws.length) return '';"
              " const w = ws[Math.min(3, ws.length - 1)]; w.click();"
              " return document.getElementById('pop').innerText; })()")
        lens.window.view.page().runJavaScript(js, 0, on_popup)

    def on_popup(text) -> None:
        result["popup"] = text
        QTimer.singleShot(400, toggle_romaji)

    def toggle_romaji() -> None:
        lens.window.grab().save(str(out_dir / "e2e-2-popup.png"))
        lens.window.romaji_btn.setChecked(True)
        QTimer.singleShot(400, after_romaji)

    def after_romaji() -> None:
        lens.window.view.page().runJavaScript("document.body.innerText", 0, on_romaji_text)

    def on_romaji_text(text) -> None:
        result["romaji_text"] = text
        lens.window.grab().save(str(out_dir / "e2e-3-romaji.png"))
        QTimer.singleShot(300, check_exclusion)

    def check_exclusion() -> None:
        g = lens.window.frameGeometry()
        shot = grab_rect(Rect(g.x(), g.y(), g.width(), g.height()))
        own = Image.fromqimage(lens.window.grab().toImage()).convert("RGB").resize(shot.size)
        diff = ImageChops.difference(shot, own).convert("L")
        same = diff.histogram()[0] / (shot.size[0] * shot.size[1])
        result["window_in_screenshot"] = same
        lens.quit()

    lens.ocr.finished.connect(on_done)
    # wait for the engine to load before capturing, like a real user would
    lens.ocr.engine_ready.connect(lambda *_: QTimer.singleShot(300, capture))
    QTimer.singleShot(60_000, lens.quit)  # safety net
    app.exec()

    outcome = result.get("outcome")
    if outcome is None:
        print("FAILED: no OCR result")
        return 1
    print(f"Speaker : {outcome.cleaned.speaker!r}")
    print("Text    :\n  " + "\n  ".join(outcome.cleaned.lines))
    print(f"Window  : {lens.window.text()!r}")
    print(f"OCR {outcome.seconds:.2f}s; select->text {result['t1'] - result['selected']:.2f}s")
    if truth_path.exists():
        truth = truth_path.read_text(encoding="utf-8")
        full = "\n".join(([outcome.cleaned.speaker] if outcome.cleaned.speaker else [])
                         + outcome.cleaned.lines)
        print(f"Accuracy vs truth: {char_accuracy(full, truth):.1%}")
    print("Popup   :", (result.get("popup") or "(none)").replace("\n", " | "))
    rt = (result.get("romaji_text") or "").splitlines()
    print("Romaji  :", " / ".join(x for x in rt if x.isascii() and x.strip())[:200] or "(none)")
    print(f"Pictures: {out_dir / 'e2e-1-text.png'} (+ -2-popup, -3-romaji)")
    same = result.get("window_in_screenshot", 1.0)
    print(f"Main window pixels found in a screenshot: {same:.0%} "
          f"({'hidden from capture OK' if same < 0.5 else 'NOT hidden'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
