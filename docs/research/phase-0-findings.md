# Phase 0 findings

Date: 2026-11-21 · Branch: `phase-0/foundations` · Machine: laptop, RTX 4050 Laptop GPU + Intel UHD, 16 GB RAM, one 1920×1080 display at 100%.

## 1. Project setup — done

- `uv` 0.13.9 (installed from PyPI), managed **CPython 3.12.16**, `pyproject.toml` with `uv_build`, package `jisho_lens` under `src/`.
- `ruff` (lint) and `pytest` set up; `uv run ruff check src tools tests spikes` and `uv run pytest` both pass.
- Entry point `jisho-lens` (Phase 0: prints the detected display setup).

## 2. Display detection and capture — works

Code: `src/jisho_lens/core/displays.py`, `core/capture.py`, `ui/capture_overlay.py`; test tool `tools/capture_test.py`.

- Display detection (`EnumDisplayMonitors` + `GetDpiForMonitor`, per-monitor DPI aware v2) reports: `\\.\DISPLAY5 (primary): 1920x1080 at (0,0), 100% scaling`.
- Capture flow: full virtual-desktop screenshot (mss) → frozen, dimmed overlay per monitor → drag → crop in physical pixels.
- Simulated drags (`--auto`) produced exactly the requested rectangles, e.g. `1,1,199,1079` → left=1 top=1 199×1079, and the frozen crop matched a fresh grab of the same area **100%** where nothing on screen moved. (Areas with a playing video differ, as expected.)
- Bug found and fixed: the selection was 1 px too large (QRect corner-to-corner is inclusive).
- Not yet tested: 125%/150% scaling and multiple monitors (only one display here). The mapping is per monitor and independent of scaling, so this is low risk; test by switching Windows scaling once.

**Your part:** run `uv run python tools/capture_test.py` and drag around something on screen to confirm it feels right.

## 3. OCR — harness ready, real test waits for game screenshots

Code: `src/jisho_lens/core/ocr/` (engines, preprocessing, metrics), `tools/ocr_bench.py`, `tools/make_synthetic_ocr_set.py`, `tests/ocr_set/README.md`.

Engines:
| Name | What | Download |
|---|---|---|
| `windows` | Windows.Media.Ocr, Japanese already installed on this PC | none |
| `rapid-v6` | RapidOCR default, PP-OCRv6 small det + rec | bundled (31 MB) |
| `rapid-v5-server` | PP-OCRv5 mobile det + PP-OCRv5 server rec (Chinese/Japanese/English) | ~89 MB on first use |
| `rapid-v4-japan` | PP-OCRv4 det + dedicated Japanese rec | small, on first use |

Preprocessing presets: `none`, `upscale`, `contrast` (auto polarity), `white-text` (keeps bright low-saturation pixels), `auto`.

Synthetic benchmark (21 generated images imitating the game's styles, real lines from the scan):

| engine | preset | dialogue-bright | dialogue-dark | menu-light | tip-dark | tip-light | all | ms/img |
|---|---|---|---|---|---|---|---|---|
| **rapid-v6** | **none** | **92.9%** | **97.6%** | **100.0%** | 98.2% | 98.2% | **96.9%** | 2181 |
| rapid-v6 | upscale | 91.8% | 88.8% | 100.0% | 98.2% | 98.2% | 94.1% | 2391 |
| rapid-v5-server | none | 89.0% | 92.2% | 98.0% | 98.2% | 98.2% | 93.8% | 35035 |
| rapid-v4-japan | none | 88.0% | 92.3% | 96.0% | 96.2% | 95.3% | 92.6% | 1493 |
| rapid-v6 | contrast | 80.4% | 88.8% | 100.0% | 98.2% | 98.2% | 90.9% | 3243 |
| rapid-v6 | auto | 69.1% | 88.8% | 100.0% | 98.2% | 98.2% | 87.7% | 6793 |
| windows | upscale | 38.7% | 89.9% | 98.9% | 94.7% | 82.5% | 77.2% | 30 |
| rapid-v6 | white-text | 65.7% | 72.7% | 100.0% | 4.7% | 98.2% | 73.2% | 8645 |
| windows | none | 31.8% | 84.5% | 98.9% | 81.6% | 80.7% | 72.2% | 11 |

(Full table with all 20 combinations: `tools/out/ocr-bench-20261121-212350.md`.)

What this says — **provisional, synthetic images only**:

1. **RapidOCR with the bundled PP-OCRv6 models and no preprocessing is clearly best** (96.9% overall, 92.9% on bright dialogue, 100% on menus). No extra model download needed.
2. **Windows OCR is very fast (~10–30 ms) and fine on menus (≈99%) but fails on bright dialogue (≈32%).** Useful as a fast option for menus, not as the default.
3. **My preprocessing presets made things worse**, especially `white-text` (it destroys the anti-aliased glyph edges and the dark-text variants) and `auto` (it picks `white-text` too often). Plain upscaling also hurt RapidOCR on dark dialogue. The SPEC's "preprocessing is required" assumption is **not confirmed**; the presets need rework and must be judged on real screenshots before any becomes default.
4. **Speed problem:** RapidOCR takes ~1.5–2.2 s per image on CPU, above the < 1 s target. To try in Phase 1: ONNX Runtime on the GPU (DirectML or CUDA on the RTX 4050), limiting the detection input size, and skipping the angle classifier (game text is never rotated). The PP-OCRv5 server model (35 s) is ruled out.

Caveat: generated images use the Yu Gothic font and clean gradients; real game frames have the game's own font, video-like noise, effects and the beta watermark. **The real test set decides.**

## 4. Packaging — install modules after setup works

Code: `spikes/packaging/` (run `python -X utf8 spikes/packaging/run_test.py`).

The test copies the managed CPython 3.12 runtime (64 MB) plus app code into an "install" folder, then:

1. Runs the app with no modules.
2. Installs a module wheel through the app: checksum verified, the module's own third-party dependency (`humanize`) installed with the bundled `pip --target` into `<data>/modules/hello/site-packages`.
3. Runs the app again: module and dependency load, popup action works.
4. Wrong checksum → refused.
5. Uninstall → back to no modules.

**Result: PASSED.** The approach in SPEC §4.3 (own Python runtime, per-module `site-packages`, SHA-256 check) works. The copied runtime is relocatable.

Findings:
- The app must run Python in **UTF-8 mode** (`-X utf8`); otherwise printing or logging Japanese text crashes with cp1252 errors when output isn't a real console. Add to the launcher.
- Installer tool (Inno Setup vs others) not chosen yet; it only needs to copy files and create shortcuts, so this is low risk. Decide in Phase 10.

## 5. Size check

Installed sizes (site-packages, MB):

| Package | MB | Notes |
|---|---|---|
| PySide6 (incl. WebEngine) | 655 | WebEngineCore alone 195; translations 61, QML 26 — trimmable |
| unidic-lite | 249 | dictionary for word splitting (UniDic 2.1.2) |
| opencv-python-headless | 126 | pulled in by RapidOCR |
| RapidOCR + models | 117 | includes downloaded v5 server rec (85) |
| onnxruntime | 49 | |
| numpy, Pillow, others | ~60 | |
| **Total site-packages** | **1,278** | |
| Python runtime | 64 | |

- **Estimated install: ~1.3 GB** before trimming, plus the JMdict/KANJIDIC2 database later (~100–200 MB).
- Trimming unused Qt modules, translations and QML could save roughly 200–300 MB; shipping only one OCR model set saves up to ~85 MB.
- **Full UniDic** (3.1.0) is a **526 MB download** (~770 MB installed), so it would roughly add 0.5 GB over `unidic-lite`. Not downloaded here.

Recommendation at the time: keep **unidic-lite** for now. **Update (Phase 2): switched to full UniDic 3.1 at the user's request; 775 MB installed. See PLAN Phase 2 notes for the comparison.**

## 6. Still open

- Real OCR test on game screenshots after release (2026-11-26) → confirm default engine (provisionally `rapid-v6`, no preprocessing) and rework preprocessing presets.
- OCR speed: try GPU (DirectML/CUDA) and det-size / no-classifier settings to get under 1 s.
- Manual capture test by you (one drag).
- 125/150% scaling check.
- UniDic lite vs full accuracy (Phase 2).
