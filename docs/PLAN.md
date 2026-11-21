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

- [ ] Repo setup: `uv`, Python 3.12, `ruff`, `pytest`, `.gitignore`, git init.
- [ ] **OCR test:** take 20–30 screenshots from your actual games; run RapidOCR and Windows OCR with and without preprocessing; compare character accuracy and speed. Pick the default engine.
- [ ] **Capture test:** screenshot + region select on each monitor at 100/125/150% scaling; confirm the pixels match.
- [ ] **Packaging test:** bundle the app with its own Python runtime, install it, then install a dummy module (with one pip dependency) *after* installation. Confirm it loads. Pick the installer tool.
- [ ] **Size check:** installed size with Qt WebEngine and UniDic full vs lite.

Done when: default OCR engine chosen, packaging approach proven, UniDic variant chosen.

## Phase 1 — Capture to window
- [ ] Tray icon and menu; single instance.
- [ ] Global hotkey (`RegisterHotKey`), configurable.
- [ ] Frozen, dimmed capture overlay across all monitors; drag to select, `Esc` to cancel.
- [ ] OCR engine interface + default engine + preprocessing.
- [ ] Main window (always on top, no focus stealing, excluded from capture) showing plain Japanese text.
- [ ] Edit / Copy / Re-capture buttons.
- [ ] Settings file + basic Settings window (hotkey, OCR engine).

Done when: hotkey → select → Japanese text appears in the window.

## Phase 2 — Text analysis and display
- [ ] fugashi + UniDic tokenizer wrapper with a clean token model.
- [ ] Furigana alignment (kanji part only), romaji via cutlet, particle pronunciation.
- [ ] WebEngine view: tokens as clickable spans, `<ruby>` furigana, romaji line.
- [ ] Furigana / romaji toggles; basic word popup showing reading + romaji only.
- [ ] Unit tests for furigana alignment and romaji on tricky cases (今日, 食べられなかった, は/を/へ, long vowels, っ).

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
- [ ] README with setup steps (Japanese OCR capability, Japanese voice, DeepL key, AnkiConnect).

## Order note
Phases 4–6 don't depend on each other once Phase 3 is done, so they can be built in any order.
