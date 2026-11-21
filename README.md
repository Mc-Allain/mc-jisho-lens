# mc-jisho-lens

**Jisho Lens** — a Windows tool for reading Japanese text in games. Press a hotkey, select text on screen, and click any word to see its reading, romaji and meanings. Translate to English with DeepL when you want to.

Status: Phase 1 (capture → OCR → text window). Furigana, romaji and word lookups come in Phase 2.

- [Specification](docs/SPEC.md)
- [Build plan](docs/PLAN.md)

## Run it (development)

Requires Windows 10/11 and [uv](https://docs.astral.sh/uv/). If `uv` isn't on your PATH, use `python -m uv` instead of `uv` below.

```powershell
uv sync
uv run jisho-lens
```

The app starts in the system tray (字 icon). Then:

1. Press **Ctrl+Alt+J** (change it in Settings). The screen freezes and dims.
2. Drag a rectangle around Japanese text. Esc or right-click cancels.
3. The text appears in an always-on-top window after about 1–2 seconds.

In the window: **Re-capture**, **Edit** (fix OCR mistakes), **Copy**, and **Retry** with another OCR engine or image preset. Closing the window only hides it; quit from the tray icon's menu. Left-clicking the tray icon shows or hides the window.

Tips: games must run in **borderless windowed** mode (the app can't draw over exclusive fullscreen). Wait until a dialogue line has fully appeared before capturing, or set a capture delay in Settings.

Settings are stored in `%APPDATA%\mc-jisho-lens\settings.toml`, logs in `%LOCALAPPDATA%\mc-jisho-lens\logs\`.

## Developer tools

```powershell
uv run pytest                                     # unit tests
uv run ruff check src tests tools spikes          # lint
uv run python -X utf8 tools/e2e_test.py           # end-to-end check, no input needed
uv run python tools/capture_test.py               # capture only
uv run python tools/ocr_bench.py                  # OCR benchmark (see tests/ocr_set/README.md)
```
