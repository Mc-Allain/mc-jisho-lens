# mc-jisho-lens

**Jisho Lens** — a Windows tool for reading Japanese text in games. Press a hotkey, select text on screen, and click any word to see its reading, romaji and meanings. Translate to English with DeepL when you want to.

Status: Phase 4 (capture → OCR → text with furigana, romaji, clickable words, meanings, grammar and kanji details; History; opt-in OCR data collection). DeepL translation comes in Phase 5.

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
3. The text appears in an always-on-top window after about 1–2 seconds. **Esc** cancels while it's waiting or reading (Esc is taken from the game only for those seconds); the previous text stays.

**Ctrl+Alt+K** shows or hides the text window (change or clear it in Settings → Show/hide window).

In the window: **click any word** to see its reading in that sentence, romaji, meanings, dictionary form and a grammar breakdown for verbs; click a **kanji** in the popup for its readings (the one used here highlighted), meaning and common words. Words missing from the dictionary (names, game terms) are marked, and coined kanji compounds get a guessed reading. **Furigana** and **Romaji** buttons switch the readings above the kanji and the romaji line on or off. **Re-capture**, **Edit** (fix OCR mistakes; the words are re-analysed), **Copy**, and **Retry** with another **OCR engine** or **Image filter** (hover over an option for what it does; on a narrow window these move to a second row). Closing the window only hides it; quit from the tray icon's menu. Left-clicking the tray icon shows or hides the window.

Other Jisho Lens windows (History, Settings, dialogs) open in front of the text window and come back in front when you click them; when you click the text window or another app they go behind it. On a new capture they are kept open with the new text window in front of them; **Settings → On new capture** can instead keep them in front or close them. They never appear in the screenshot.

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

**History and OCR data.** Every capture is saved to **History** (tray menu or the History button): reopen, correct or delete past captures. After your first capture the app asks **once** whether it may keep your captures and corrections to improve OCR accuracy — this is **off unless you allow it**, and the data **stays on this computer**; nothing is sent anywhere unless you export a pack and share it yourself. With collection on, **Edit** saves your correction and **✓ Correct** marks text OCR got right. The app also **remembers your corrections**: when the same misread shows up in a later capture it is fixed automatically ("Applied N of your earlier corrections"; **Undo** shows what OCR read). Review or delete them in **Settings → OCR data → Learned corrections**.

Space: the same sentence is kept as one sample however often you capture it, History and OCR data share one image file, and **Settings → OCR data space** (300 MB by default) removes the oldest *unchecked* samples when full. Corrected samples stay until you delete them yourself. **★ Favorite** (main window or History) keeps a phrase: favorites can't be deleted until you remove the star. History can show **All / Favorites / Corrected**, and delete the **selected** captures, a **time range**, everything (**Clear history**) or History plus all collected data (**Clear all**). In History you can **export**, **import** and **merge** data packs: packs contain only samples you **fixed with Edit**, and importing or merging opens a **review window** (picture, your answer before / theirs after, include or exclude each one, choose for a different answer) where nothing changes until you confirm. You can also export an OCR test set (`tools/ocr_data.py` does the same from the command line). Change or delete it in **Settings → OCR data**.

Settings are stored in `%APPDATA%\mc-jisho-lens\settings.toml`, logs in `%LOCALAPPDATA%\mc-jisho-lens\logs\`.

## Developer tools

```powershell
uv run pytest                                     # unit tests
uv run ruff check src tests tools spikes          # lint
uv run python -X utf8 tools/e2e_test.py           # end-to-end check, no input needed
uv run python tools/capture_test.py               # capture only
uv run python tools/ocr_bench.py                  # OCR benchmark (see tests/ocr_set/README.md)
uv run python tools/ocr_data.py                   # OCR data: stats, export, import, merge, testset
```
