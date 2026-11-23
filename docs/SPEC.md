# mc-jisho-lens — Specification

**Display name:** Jisho Lens
**Status:** Draft v1 (2026-11-21)
**Platform:** Windows 10/11 (x64)

## 1. Overview

Jisho Lens is a Windows desktop tool for reading Japanese text in games. You press a hotkey, drag a rectangle around Japanese text on the screen, and the app reads it (OCR) and shows it in an always-on-top window. You can click any word to see how it is read in that sentence, its romaji, and its meanings, then click a kanji inside it to see all its readings. An English translation is shown only when you ask for it.

The goal is **learning to read**, not just understanding the game, so the Japanese comes first and the English is opt-in.

### 1.1 Target text (from the game UI scan)
A scan of 144 frames from a 7-hour Azur Promilia beta playthrough ([research/ui-text-scan.md](research/ui-text-scan.md)) shaped the OCR requirements. The two main use cases are:

1. **Story dialogue:** white text with a soft shadow drawn directly over the 3D scene (no box), centered at the bottom, with the speaker's name above it in a pale blue. Often low contrast on bright scenes; often caught mid-line because of the letter-by-letter effect and fast-forward.
2. **Menus and descriptions:** dark text on light parchment-style panels (crafting, quests, encyclopedia, confirmations, loading tips, story summaries). Easiest to read and richest in vocabulary.

Also seen: HUD quest tracker and prompts (small, semi-transparent), tutorial text with inline key icons, and combat HUD text (tiny, moving, covered by effects, so not a target).

### Goals
- On-demand capture of horizontal Japanese game text.
- Word-level lookup with context-correct readings, romaji, meanings, and kanji details.
- Furigana and romaji display toggles.
- English translation via DeepL on button press.
- Fully offline except translation.
- Modular: optional features can be installed, enabled, disabled, and removed after installation.

### Non-goals (for now)
- Continuous / real-time screen translation.
- Vertical text (manga).
- Offline translation (Sugoi, local LLM). The translation layer is designed so these can be added later as modules.
- Built-in flashcards (Anki is used instead, as an optional module).
- Game text hooking (reading text from game memory).
- macOS / Linux.

## 2. User flow

1. The app starts in the **system tray**. It does nothing until the hotkey is pressed.
2. **Hotkey** (default `Ctrl+Alt+J`, configurable) → the screen freezes and dims across all monitors.
3. **Drag a rectangle** around the text. `Esc` cancels. Releasing the mouse confirms.
4. OCR reads the region. The **main window** appears (always on top) showing the Japanese text.
5. The user can:
   - **Click a word** → popup with reading, romaji, meanings, part of speech, and conjugation breakdown.
   - **Click a kanji in the popup** → all on'yomi / kun'yomi, meanings, stroke count, JLPT level, example words.
   - **Edit the text** to fix OCR mistakes; the analysis re-runs.
   - **Toggle** furigana / romaji.
   - Press **Translate** → English from DeepL appears below the text.
   - (Anki module) **＋ Anki** in a word or kanji popup.
   - (Audio module) **▶** to hear a word or the sentence.
6. Each capture is saved to **History**, a separate screen.

## 3. Module layout

| Tier | Modules | State after install |
|---|---|---|
| **Core** | Tray + hotkey, capture, OCR, main window (plain text), History, Settings, Module Manager | Always present, can't be disabled |
| **Default** | Word splitting (UniDic-lite), Dictionary (JMdict + KANJIDIC2), Translation (DeepL) | Installed and enabled; can be disabled or removed |
| **Optional** | Full UniDic (alternative to UniDic-lite), Anki, Audio (TTS) | Not installed; install any time from the installer or the Module Manager |

**Components (decided 2026-11-22).** Word splitting and the dictionaries are optional components, **none installed by default**; each can be installed and removed (Settings → Components, or `tools/components.py`):

| Component | Rule |
|---|---|
| UniDic-lite | optional, removable |
| Full UniDic | optional, removable |
| JMdict (English) | optional, removable; only installable while a UniDic is installed |
| KANJIDIC2 | optional, removable; only installable while a UniDic is installed |
| Wiktionary | optional, removable; only installable while a UniDic is installed |

With no UniDic installed there is no word splitting: the window shows plain OCR text. Removing the last UniDic removes JMdict, KANJIDIC2 and Wiktionary automatically. Installed dictionaries are always used; Settings → Word splitting chooses None or an installed UniDic. Each component lives in its own folder (UniDic installed with `pip --target`, dictionaries built into one SQLite file each), the same approach the module system (Phase 7) will use.

### 3.1 Core

**Tray + hotkey**
- Tray icon with menu: Capture, Show window, History, Settings, Quit.
- Global hotkey via Win32 `RegisterHotKey`, works while a game has focus.
- Option: start with Windows.

**Capture**
- Take a screenshot of the full virtual desktop (all monitors) first, then show it frozen and dimmed in a borderless fullscreen overlay for selection. This avoids timing issues with moving content.
- Per-monitor DPI awareness (v2) so the selection matches pixels at 100/125/150% scaling and on mixed-DPI setups.
- The app **detects monitors, resolutions and scaling itself** at startup and whenever the display setup changes (Win32 `EnumDisplayMonitors` + `GetDpiForMonitor`). Nothing needs configuring. The detected setup is shown in Settings → About and written to the log, to help with bug reports.
- The main window is excluded from capture (`SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`).
- Limitation: can't draw over **exclusive fullscreen** games; borderless windowed mode works.

**OCR**
- Pluggable engine interface. Engines:
  - **RapidOCR** (PaddleOCR PP-OCR models via ONNX Runtime). Default unless the Phase 0 test says otherwise. CPU by default; GPU optional.
  - **Windows OCR** (`Windows.Media.Ocr`). Needs the Japanese OCR language capability installed in Windows.
- Preprocessing before OCR (see §1.1 for why each step exists):
  - **Upscale** small text (2–3×).
  - **Contrast boost and white-text isolation** (keep bright, low-saturation pixels): required, not optional. About a quarter of dialogue lines in the scan were white text on bright backgrounds.
  - **Automatic polarity:** detect light-on-dark vs dark-on-light and invert when needed. The same game panel can appear in both themes.
  - Optional sharpen.
  - A preprocessing preset can be chosen per capture or set as the default; the user can retry a capture with another preset from the main window.
- **Capture delay** option (e.g. 0 / 0.5 / 1 s after the selection is confirmed), because dialogue appears letter by letter and is often caught mid-line.
- Post-OCR cleanup:
  - **Speaker name line:** a short line directly above dialogue in a different colour is shown as the speaker, separate from the sentence.
  - **Inline key and mouse icons** (boxed single letters such as [Q], [F], [T]) are removed or marked so they don't reach word analysis.
  - Lines are joined into one text block, keeping line breaks.

**Text analysis**
- (Word splitting module) Morphological analysis with **fugashi + UniDic-lite or full UniDic** (MeCab), chosen in Settings; skipped entirely when word splitting is *None*. For each token: surface form, lemma (dictionary form), part of speech, conjugation type and form, kana reading, pronunciation.
- **Readings in context** come from UniDic (今日 → きょう). Particles use pronunciation (は → wa, を → o, へ → e).
- **Romaji** via **cutlet** (Hepburn).
- **Furigana** alignment: furigana covers only the kanji part (食べる → た over 食). Kana-only words get none.
- Numbers, counters and symbols common in game UI (7/20, 418%, +53, ×1, 【】, ——, ……, （火）) pass through unchanged as non-clickable tokens and don't break word splitting around them.
- Output is a list of tokens rendered as clickable HTML spans with `<ruby>` for furigana.

**Main window**
- Always on top, resizable, remembers position and size. Shown without stealing focus from the game when a capture finishes; focus moves only when the user clicks it.
- Shows the latest capture only (earlier captures live in History).
- Toggles: furigana, romaji line, English.
- Buttons: Translate, Edit, Re-capture, Copy, History.
- Rendered in a Qt WebEngine view (HTML/CSS/JS) for ruby text and clickable spans; the HTML side talks to Python through Qt WebChannel.

**History**
- Separate screen listing past captures: thumbnail, date, Japanese text, translation if any.
- Open a capture back in the main window; delete one or all.
- Retention setting (e.g. keep last N captures or N days).

**OCR data collection (opt-in, off by default)**
- The app asks once whether it may keep captures and corrections to improve OCR accuracy for the user's own copy, and states that the data stays on this computer and is never sent anywhere unless the user exports and shares it. The choice can be changed in Settings, and collected data can be deleted there.
- When allowed: the screenshot crop, OCR result, settings used, timing, text type, and the corrected text (Edit) or a "Correct ✓" confirmation are stored locally.
- Users can export data packs, and import and merge packs from others (manual file sharing only; duplicates merged by image hash). Packs contain only samples fixed with Edit (✓ and unchecked samples stay on the computer). A review window shows every incoming sample (picture, OCR text, your answer before / theirs after with the differences highlighted, status New / Different answer / Same sentence / Same) and lets you exclude any of them and choose, for a different answer, Keep mine / Use theirs / Keep as alternative; nothing changes until you confirm. Learning OCR fixes from imported answers is an opt-in checkbox. Each export or merge is a release of the user's pack: a name they choose plus a version that goes up each time (RavenOCR v1, v2, ...), with a history log since the first version (date, contributor ID, what it was made from, sample count; logs of source packs carried along). The app shows what the local data is made of: "Using: KaiOCR v4 (partial) + RavenOCR v2 + own data" (partial = some of that pack left out by the user's choice; own data = samples the user collected). Exporting opens a review as well (untick what not to share). Samples can be labelled with a **category** when exporting or merging (default suggestion "Azur Promilia JP"; blank = none); every review filters by category and ticks / unticks a whole category, and each history-log line lists the categories of that release. The combined set feeds the OCR benchmark to choose engines and image settings. Details in PLAN Phase 4.

**Settings**
- General: hotkey, start with Windows, window behaviour, theme.
- OCR: engine, preprocessing defaults, CPU/GPU.
- Display: furigana / romaji defaults, font size.
- Plus a page per enabled module.

**Module Manager**
- Lists every known module with name, description, version, size, and status: Not installed / Installed (disabled) / Enabled / Update available.
- Actions: Install, Enable, Disable, Update, Uninstall.
- See §4 for how modules work.

### 3.2 Dictionary (default)
- Offline SQLite database built from **JMdict** (words) and **KANJIDIC2** (kanji), shipped with the module.
- **Word popup:** word, reading in this sentence, romaji, meanings grouped by part of speech, common-word / JLPT markers.
  - Conjugated forms show the dictionary form and a breakdown (食べられなかった → 食べる: potential + negative + past), built from UniDic conjugation data.
  - Particles show a short grammar note.
  - Katakana loanwords show the source word (JMdict `lsource`).
  - When a surface form matches several entries, the entry whose reading matches UniDic's reading is shown first.
- **Kanji popup:** on'yomi, kun'yomi (with the reading used here highlighted), meanings, stroke count, grade, JLPT level, a few common words using the kanji.
- **Not in dictionary:** game names and coined terms (キボ, スターリンク, ステラカード, アニマ, character and place names) are common. The popup clearly says the word isn't in the dictionary, still shows the reading and romaji from the core, and offers the per-kanji breakdown for any kanji in it.
- Later (not in v1): a user glossary to add your own meanings for game terms.
- If the module is disabled, clicking a word shows only the reading and romaji from the core.

### 3.3 Translation — DeepL (default)
- Translate button sends the current text to the DeepL API (Free or Pro, detected from the key).
- Without a key, the app still works; the Translate button shows "Add a DeepL key in Settings".
- First launch asks for the key (skippable).
- Key stored in Windows Credential Manager (`keyring`), not in plain-text config.
- Translations are cached per text so repeats cost nothing.
- Built on a **translation provider interface** so other providers can be added later.

### 3.4 Anki (optional)
- Talks to Anki desktop through the **AnkiConnect** add-on (`http://127.0.0.1:8765`).
- Creates its own note types and a deck (default `Jisho Lens`) on first use.
- **Word note** → two cards: Reading (word → reading) and Meaning (word → meaning).
  Fields: Word, Reading, Romaji, Meanings, PartOfSpeech, Sentence (word highlighted), Screenshot, Audio, Source (game name / tag).
- **Kanji note** → one card. Fields: Kanji, Onyomi, Kunyomi, Meanings, Strokes, JLPT, Examples.
- ＋ Anki button in word and kanji popups; ★ marker for words already in Anki (checked with `findNotes`).
- If Anki isn't running, notes go into a local **queue** and are sent automatically next time Anki is reachable.
- Settings: deck name, which card types to create, include screenshot / audio, default tag.
- Phone review works through AnkiWeb sync (AnkiDroid / AnkiMobile).

### 3.5 Audio (optional)
- Japanese text-to-speech using Windows voices (offline). Needs a Japanese voice installed in Windows.
- ▶ buttons for word and sentence. If the Anki module is enabled, audio can be attached to notes.

## 4. Module system

### 4.1 Module package
Each module is a folder with a manifest:

```toml
# module.toml
id = "anki"
name = "Anki"
version = "1.0.0"
description = "Save words and kanji to Anki through AnkiConnect."
core_api = ">=1.0,<2.0"        # compatible core API versions
entry_point = "jisho_lens_anki:Module"
dependencies = []               # extra Python packages, if any
default_enabled = false
```

### 4.2 Extension points
A module's `Module` class receives a `ModuleContext` and registers what it adds:

- **Popup actions** — buttons in the word / kanji popup (＋ Anki, ▶).
- **Window actions** — buttons on the main window (Translate).
- **Settings pages.**
- **Tray menu items.**
- **Events** — `capture_completed`, `text_analyzed`, `word_opened`, `kanji_opened`, `translation_completed`.
- **Services** — named providers other parts can call: `dictionary`, `translation`, `tts`.

The core never imports a module directly; it only talks through these points. A disabled module isn't imported at all.

### 4.3 Installing after installation
- The app ships with its **own Python runtime** (not a frozen single exe), so new modules and their Python dependencies can be added later.
- Installed modules live in `%LOCALAPPDATA%\mc-jisho-lens\modules\<id>\`, each with its own `site-packages` folder for dependencies.
- Modules are downloaded only from the project's official release source, and each download is checked against a published SHA-256 checksum before installing.
- The installer can also install optional modules (checkboxes, unchecked by default) using the same mechanism.
- Exactly how the runtime is bundled is decided in Phase 0 (see the plan).

## 5. Data and storage

| What | Where | Format |
|---|---|---|
| Settings | `%APPDATA%\mc-jisho-lens\settings.toml` | TOML |
| DeepL key | Windows Credential Manager | — |
| History + capture images | `%LOCALAPPDATA%\mc-jisho-lens\history.db` + `captures\` | SQLite + PNG |
| Components (UniDic, JMdict, KANJIDIC2, Wiktionary) | Development: `data/components/`; installed: `%LOCALAPPDATA%\mc-jisho-lens\components\` (`JISHO_LENS_COMPONENTS` overrides) | One folder each; dictionaries as read-only SQLite |
| Installed modules | `%LOCALAPPDATA%\mc-jisho-lens\modules\` | Folders |
| Anki queue | Inside the Anki module's data folder | SQLite |
| Logs | `%LOCALAPPDATA%\mc-jisho-lens\logs\` | Text, rotating |

`history.db` table `captures`: `id`, `created_at`, `image_path`, `ocr_text`, `edited_text`, `translation`, `ocr_engine`, `source_tag`.

## 6. Tech stack

| Area | Choice |
|---|---|
| Language | Python 3.12 |
| Packaging / env | `uv` for development; bundled Python runtime for release |
| UI | PySide6 (Qt 6) + Qt WebEngine + WebChannel |
| Screenshots | `mss` |
| Win32 calls | `ctypes` (hotkey, DPI awareness, capture exclusion) |
| OCR | `rapidocr` + `onnxruntime`; `winrt` packages for Windows OCR |
| Image processing | Pillow / OpenCV (headless) |
| Analysis | `fugashi` + full UniDic 3.1 (`unidic` package), `cutlet` |
| Dictionary | JMdict + KANJIDIC2 → SQLite (build script in repo) |
| Translation | DeepL API (`deepl` package) |
| Secrets | `keyring` |
| Anki | AnkiConnect over HTTP (`httpx`) |
| TTS | Windows speech (`winrt` Windows.Media.SpeechSynthesis) |
| Tests / lint | `pytest`, `ruff` |
| Installer | Inno Setup (decided in Phase 0) |

## 7. Resource targets
- Target hardware (detected on the dev machine): laptop with RTX 4050 Laptop GPU (6 GB) + Intel UHD integrated graphics, 16 GB RAM, one 1920×1080 display at 100%. Must also run on CPU-only machines.
- Idle in tray: < 150 MB RAM, ~0% CPU.
- Capture → text shown: < 1 s on CPU for a typical dialogue box.
- GPU memory: < 1 GB, and only if GPU OCR is turned on.

## 8. Online / offline

| Feature | Network |
|---|---|
| Capture, OCR, analysis, dictionary, history, audio | Offline |
| Anki | Local only (127.0.0.1) |
| Translation | **Online** (DeepL) |
| Module install / update | Online when installing |

## 9. Licences and attribution
- **JMdict, KANJIDIC2** — EDRDG licence (CC BY-SA 4.0). Attribution in the About screen; the derived database stays under the same licence.
- **Wiktionary** (words JMdict lacks, via Wiktextract / kaikki.org) — CC BY-SA 4.0. Attribution in the About screen.
- **UniDic** — BSD / LGPL / GPL (choose BSD).
- **MeCab, fugashi, cutlet, RapidOCR, PaddleOCR models, ONNX Runtime** — permissive licences; to be listed in a third-party notices file.
- **PySide6** — LGPL; must be dynamically linked (the default) and the licence included.

## 10. Risks
| Risk | Mitigation |
|---|---|
| OCR accuracy on low-contrast dialogue (white text on bright scenes) and busy backgrounds | Phase 0 test set built from the UI scan categories; contrast boost, white-text isolation and auto polarity; two engines; retry with another preset; editable text |
| Text captured mid-line (letter-by-letter dialogue) | Capture delay option; re-capture button |
| DPI scaling / multi-monitor coordinate bugs | Per-monitor DPI v2 from day one; test at 100/125/150% and mixed setups |
| Installing modules after install with a bundled Python | Packaging spike in Phase 0 before building the module system on top |
| Exclusive fullscreen games | Document borderless windowed; nothing else planned |
| UniDic reading wrong for names / rare words | Show alternative readings from JMdict in the popup; text is editable |
| Install size (Qt WebEngine + full UniDic + dictionary) | Full UniDic chosen (decision 2026-11-21); trim Qt modules; the installer must include or download the UniDic data (~526 MB download) |

## 11. Open questions
- ~~Full UniDic or `unidic-lite`?~~ Decided 2026-11-21: **full UniDic 3.1**; `unidic-lite` removed.
- Installer: ship the UniDic data inside the installer, or download it on first run?
- Default hotkey: is `Ctrl+Alt+J` free in your games?
- Where module releases are hosted (e.g. GitHub Releases on the project repo).
- User glossary for game terms: core feature or part of the Dictionary module? (Not in v1.)
