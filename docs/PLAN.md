# mc-jisho-lens — Build Plan

Companion to [SPEC.md](SPEC.md). Each phase ends with something you can run and try.

## Proposed folder structure

```
mc-jisho-lens/
├─ docs/                     SPEC.md, PLAN.md
├─ src/jisho_lens/
│  ├─ app.py                 entry point, tray, startup
│  ├─ core/
│  │  ├─ hotkey.py
│  │  ├─ capture.py          screenshot + DPI helpers
│  │  ├─ ocr/                engine interface, rapidocr.py, windows_ocr.py, preprocess.py
│  │  ├─ analysis/           tokenizer.py, furigana.py, romaji.py
│  │  ├─ history.py
│  │  ├─ settings.py
│  │  └─ modules/            manifest.py, loader.py, context.py, manager.py, installer.py
│  └─ ui/
│     ├─ capture_overlay.py
│     ├─ main_window.py
│     ├─ history_window.py
│     ├─ settings_window.py
│     └─ web/                index.html, app.css, app.js
├─ modules/
│  ├─ dictionary/            default
│  ├─ translation_deepl/     default
│  ├─ anki/                  optional
│  └─ audio/                 optional
├─ tools/
│  └─ build_dictionary.py    JMdict + KANJIDIC2 → SQLite
├─ tests/
├─ installer/                Inno Setup script
└─ pyproject.toml
```

## Phase 0 — Foundations and tests of the risky parts
Goal: answer the risky questions before building on them.

- [x] Repo setup: `uv`, Python 3.12, `ruff`, `pytest`, `.gitignore`, git init.
- [ ] **OCR test set:** about 30 screenshots from the actual game (after the November 26 release), cropped the way a user would select them, with the correct text typed out for each. Cover the categories from [research/ui-text-scan.md](research/ui-text-scan.md):
  - Dialogue on dark or neutral scenes (≈6)
  - Dialogue on bright scenes: cream, cyan, pale sky, white glow (≈6), the hardest case
  - Dialogue with the speaker name line included (≈3)
  - Menus and descriptions, dark text on light panels (≈6)
  - Loading tips in both the light and the dark version (≈2)
  - Tutorial text and prompts with inline key icons (≈3)
  - Quest tracker (≈2)
  - Snow-area HUD (white on white) (≈2)
- [ ] **OCR test:** run RapidOCR and Windows OCR on the set, each with no preprocessing, upscale only, and upscale + contrast / white-text isolation + auto polarity. Compare character accuracy per category and speed. Pick the default engine and default preprocessing preset.
- [ ] Set a target: e.g. ≥ 95% character accuracy on dialogue and menus with the default preset (combat HUD excluded).
- [x] **Capture test:** display detection (monitors, resolution, scaling) built into the app; screenshot + region select confirmed on the dev machine (one 1920×1080 display at 100%). Other scalings (125/150%) and multi-monitor are tested by temporarily changing Windows display scaling, since the dev machine has a single display.
- [x] **Packaging test:** bundle the app with its own Python runtime, install it, then install a dummy module (with one pip dependency) *after* installation. Confirm it loads. Pick the installer tool.
- [x] **Size check:** installed size with Qt WebEngine and UniDic full vs lite.

Done when: default OCR engine chosen, packaging approach proven, UniDic variant chosen.

## Phase 1 — Capture to window
- [x] Tray icon and menu; single instance.
- [x] Global hotkey (`RegisterHotKey`), configurable.
- [x] Frozen, dimmed capture overlay across all monitors; drag to select, `Esc` to cancel.
- [x] OCR engine interface + default engine + preprocessing presets (upscale, contrast / white-text isolation, auto polarity).
- [x] Capture delay option (0 / 0.5 / 1 s).
- [x] Post-OCR cleanup: speaker name line detection, removal of inline key / mouse icons.
- [x] "Retry with another preset" from the main window.
- [x] Main window (always on top, no focus stealing, excluded from capture) showing plain Japanese text.
- [x] Edit / Copy / Re-capture buttons.
- [x] Settings file + basic Settings window (hotkey, OCR engine).

Done when: hotkey → select → Japanese text appears in the window.

Phase 1 notes (2026-11-21):
- End-to-end check `tools/e2e_test.py` passes: synthetic dialogue and menu samples read at 100%, speaker split off, main window confirmed invisible to screenshots.
- OCR: RapidOCR PP-OCRv6 with the angle classifier turned off (game text is never rotated) — same accuracy, roughly 1.3–2 s per capture on CPU. Still above the < 1 s target; GPU (DirectML/CUDA) is the next thing to try.
- Memory: the Qt WebEngine view commits ~590 MB as soon as it exists, so the main window is created on the first capture. Idle in the tray: ~124 MB working set (OCR engine preloaded). After the first capture the window adds roughly 150 MB of working set — revisit if this matters (alternative: draw furigana in a plain Qt widget instead of WebEngine).
- Preprocessing presets exist but none beats `none` yet (see phase-0-findings.md); default stays `none` until real screenshots are tested.

## Phase 2 — Text analysis and display
- [ ] fugashi + UniDic tokenizer wrapper with a clean token model.
- [ ] Furigana alignment (kanji part only), romaji via cutlet, particle pronunciation.
- [ ] WebEngine view: tokens as clickable spans, `<ruby>` furigana, romaji line.
- [ ] Furigana / romaji toggles; basic word popup showing reading + romaji only.
- [ ] Numbers, counters and symbols (7/20, 418%, +53, ×1, 【】, ——, ……, （火）) pass through as non-clickable tokens.
- [ ] Unit tests for furigana alignment and romaji on tricky cases (今日, 食べられなかった, は/を/へ, long vowels, っ), plus real lines from the UI scan.

Done when: clicking a word shows its reading in context.

## Phase 3 — Module system
- [ ] Manifest format, loader, `ModuleContext`, extension points, events, services.
- [ ] Enable / disable with restart-free reload where possible.
- [ ] Module Manager UI (list, enable, disable) — install/uninstall comes in Phase 7.
- [ ] A test module to prove each extension point.

Done when: modules can add popup buttons, window buttons, settings pages and services without the core knowing about them.

## Phase 4 — Dictionary module
- [ ] `tools/build_dictionary.py`: JMdict + KANJIDIC2 → SQLite with indexes for kanji form, kana form, and kanji character.
- [ ] Lookup by lemma + reading, ranked by reading match and commonness.
- [ ] Word popup: meanings by part of speech, conjugation breakdown, particle notes, loanword source, common/JLPT markers.
- [ ] Kanji popup: on/kun readings (current one highlighted), meanings, strokes, grade, JLPT, example words.
- [ ] "Not in dictionary" state for game terms and names: reading + romaji + per-kanji breakdown.
- [ ] Attribution in an About screen.

Done when: word and kanji popups are complete and work offline.

## Phase 5 — Translation module (DeepL)
- [ ] Translation provider interface (core service).
- [ ] DeepL provider; Free/Pro detection; key in Credential Manager.
- [ ] First-launch key prompt (skippable); "Add a DeepL key" state on the button.
- [ ] Translation cache; error messages for no network / quota exceeded.

Done when: Translate shows English, and the app works fine without a key.

## Phase 6 — History
- [ ] `history.db` + saved capture images.
- [ ] History screen: list with thumbnails, open in main window, delete, retention setting.

Done when: past captures can be browsed and reopened.

## Phase 7 — Installing modules after installation
- [ ] Module index (list of available modules, versions, download URLs, SHA-256).
- [ ] Download, verify checksum, install dependencies into the module's own folder, enable.
- [ ] Update and uninstall.

Done when: a module can be installed, updated and removed from the Module Manager.

## Phase 8 — Anki module
- [ ] AnkiConnect client; connection check and helpful "Anki isn't running / add-on missing" messages.
- [ ] Create note types (Word: Reading + Meaning cards; Kanji) and deck on first use.
- [ ] ＋ Anki in word and kanji popups; ★ already-saved markers.
- [ ] Screenshot crop attached as media; offline queue that sends when Anki is back.
- [ ] Settings page: deck, card types, screenshot/audio, tag.

Done when: one click puts a full card into Anki, and it syncs to the phone.

## Phase 9 — Audio module
- [ ] Windows Japanese TTS; ▶ for word and sentence.
- [ ] Attach audio to Anki notes when both modules are enabled.
- [ ] Clear message if no Japanese voice is installed.

## Phase 10 — Release
- [ ] Installer with optional module checkboxes, start-menu entry, uninstaller.
- [ ] Third-party notices and licences.
- [ ] Logging, crash reporting to a local log file.
- [ ] README with setup steps (Japanese OCR capability, Japanese voice, DeepL key, AnkiConnect) and capture tips (wait for the line to finish, select tightly, use borderless windowed mode).

## Order note
Phases 4–6 don't depend on each other once Phase 3 is done, so they can be built in any order.
