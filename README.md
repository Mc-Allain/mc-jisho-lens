# mc-jisho-lens

**Jisho Lens** — a Windows tool for reading Japanese text in games. Press a hotkey, select text on screen, and click any word to see its reading, romaji and meanings. Translate to English with DeepL when you want to.

Status: Phase 3 (capture → OCR → text with furigana, romaji, clickable words, meanings, grammar and kanji details). History comes in Phase 4, DeepL translation in Phase 5.

- [Specification](docs/SPEC.md)
- [Build plan](docs/PLAN.md)

## Run it (development)

Requires Windows 10/11 and [uv](https://docs.astral.sh/uv/). If `uv` isn't on your PATH, use `python -m uv` instead of `uv` below.

```powershell
uv sync
uv run jisho-lens
```

Out of the box the app shows the captured text as plain text. Word splitting and the dictionaries are **optional components** — install them in **Settings → Components**, or from the command line:

```powershell
uv run python tools/components.py install unidic-lite jmdict kanjidic2 wiktionary
```

The app starts in the system tray (字 icon). Then:

1. Press **Ctrl+Alt+J** (change it in Settings). The screen freezes and dims.
2. Drag a rectangle around Japanese text. Esc or right-click cancels.
3. The text appears in an always-on-top window after about 1–2 seconds.

In the window: **click any word** to see its reading in that sentence, romaji, meanings, dictionary form and a grammar breakdown for verbs; click a **kanji** in the popup for its readings (the one used here highlighted), meaning and common words. Words missing from the dictionary (names, game terms) are marked, and coined kanji compounds get a guessed reading. **Furigana** and **Romaji** buttons switch the readings above the kanji and the romaji line on or off. **Re-capture**, **Edit** (fix OCR mistakes; the words are re-analysed), **Copy**, and **Retry** with another OCR engine or image preset. Closing the window only hides it; quit from the tray icon's menu. Left-clicking the tray icon shows or hides the window.

Tips: games must run in **borderless windowed** mode (the app can't draw over exclusive fullscreen). Wait until a dialogue line has fully appeared before capturing, or set a capture delay in Settings.

**Components** (nothing is installed by default; each can be removed again):

| Component | What it adds | Size |
|---|---|---|
| UniDic-lite | Word splitting: clickable words, readings, furigana, romaji, grammar | 249 MB |
| Full UniDic | Same, slightly more accurate | 775 MB (526 MB download) |
| JMdict (English) | Meanings, common-word marks, dictionary-based split fixes | 62 MB |
| KANJIDIC2 | Kanji details, reading guesses for coined words | 2 MB |
| Wiktionary | Words JMdict lacks: dialect, slang, newer words (じっちゃ) | 25 MB |

Without a UniDic there is no word splitting (plain text). JMdict, KANJIDIC2 and Wiktionary need a UniDic and are removed automatically with the last one. Components live in `data/components/` when running from source (`%LOCALAPPDATA%\mc-jisho-lens\components` when installed). Choose which installed UniDic to use in **Settings → Word splitting**.

Settings are stored in `%APPDATA%\mc-jisho-lens\settings.toml`, logs in `%LOCALAPPDATA%\mc-jisho-lens\logs\`.

## Developer tools

```powershell
uv run pytest                                     # unit tests
uv run ruff check src tests tools spikes          # lint
uv run python -X utf8 tools/e2e_test.py           # end-to-end check, no input needed
uv run python tools/capture_test.py               # capture only
uv run python tools/ocr_bench.py                  # OCR benchmark (see tests/ocr_set/README.md)
```
