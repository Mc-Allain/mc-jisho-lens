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
- [x] fugashi + UniDic tokenizer wrapper with a clean token model.
- [x] Furigana alignment (kanji part only), romaji via cutlet, particle pronunciation.
- [x] WebEngine view: tokens as clickable spans, `<ruby>` furigana, romaji line.
- [x] Furigana / romaji toggles; basic word popup showing reading + romaji only.
- [x] Numbers, counters and symbols (7/20, 418%, +53, ×1, 【】, ——, ……, （火）) pass through as non-clickable tokens.
- [x] Unit tests for furigana alignment and romaji on tricky cases (今日, 食べられなかった, は/を/へ, long vowels, っ), plus real lines from the UI scan.

Done when: clicking a word shows its reading in context.

Phase 2 notes (2026-11-21):
- Analysis runs in the OCR worker right after OCR (a few ms), and again on the GUI thread after Edit.
- Romaji follows the kana (スター → "sutaa", not "star") and uses Hepburn particles (は → wa, へ → e, を → o). cutlet's mapping was patched for ウィ/ウェ/ウォ/クァ/イェ ("wisupaa", not "isupaa").
- Popup shows: word with furigana, reading, romaji, word type, dictionary form (with reading), raw conjugation type/form, particle pronunciation note, and a "not in the word list" note for unknown words (names, game terms). Dictionary meanings and a readable conjugation breakdown come with the Dictionary (Phase 3).
- UniDic-lite weak spots seen on real game lines: rare compounds split wrongly (火元素 → 火元 + 素, まえにじっちゃ → まえ + にじっ + ちゃ) and coined game words get ordinary readings (炎核 → ほのお + かく, 翼人 → つばさ + にん).
- **Switched to full UniDic 3.1 (decision 2026-11-21); unidic-lite removed.** Retest on the same lines: none of the problems above changed (翼人 is now つばさ + ひと), and full UniDic splits unknown katakana names (テララ → テ + ララ, リリカ → リリ + カ). Fixed for both dictionaries: a run of katakana pieces containing a one-character piece or a grammar word is joined back into one "unknown word" (real compounds like スター + リンク stay split). Cost: +526 MB on disk (775 MB vs 249 MB); RAM +~14 MB (dictionary is read from disk on demand); load 0.26 s; analysis ~0.2 ms per line. Setup now needs `python -m unidic download` once.
- Edit remains the way to fix individual wrong splits; a user glossary for game terms (SPEC open question) would fix them permanently.
- Checked end to end with `tools/e2e_test.py` (furigana, popup, romaji toggle; window pictures saved in `tools/out/`).

## Phase 3 — Dictionary
Built first, as ordinary core code behind a small `dictionary` service interface, so meanings reach the popup early. Phase 7 turns it into a module.

- [ ] `tools/build_dictionary.py`: JMdict + KANJIDIC2 → SQLite with indexes for kanji form, kana form, and kanji character.
- [ ] Lookup by lemma + reading, ranked by reading match and commonness.
- [ ] Word popup: meanings by part of speech, conjugation breakdown, particle notes, loanword source, common/JLPT markers.
- [ ] Kanji popup: on/kun readings (current one highlighted), meanings, strokes, grade, JLPT, example words.
- [ ] "Not in dictionary" state for game terms and names: reading + romaji + per-kanji breakdown.
- [ ] **Word-boundary check using JMdict** (idea from 2026-11-21 review): take MeCab's top alternative splits (`nbestToNodeList`) and move a boundary character to the next word only when (a) that creates a *common* JMdict word, (b) the word it leaves is *not* common, and (c) the leftover piece is still a dictionary word. Fixes 火元 + 素 → 火 + 元素 without breaking 攻撃 + 力, 日本 + 人, 大陸 + 中. A naive version without JMdict was tested and rejected: it fixed 火元素 but broke 攻撃力 → 攻 + 撃力, 日本人 → 日 + 本人, 大陸中 → 大 + 陸中.
- [ ] **Compound readings for coined words**: when a run of single-kanji tokens isn't a JMdict word (炎 + 核, 翼 + 人), offer the on'yomi reading from KANJIDIC2 in the popup as an alternative (えんかく, よくじん) and mark it as a guess.
- [ ] Re-evaluate UniDic-lite vs full UniDic once the JMdict checks are in place (suggestion on 2026-11-21: JMdict covers lite's gaps, saving 526 MB). Compare on real game lines.
- [ ] Attribution in an About screen.

Done when: word and kanji popups are complete and work offline.

## Phase 4 — History
- [ ] `history.db` + saved capture images.
- [ ] History screen: list with thumbnails, open in main window, delete, retention setting.

Done when: past captures can be browsed and reopened.

## Phase 5 — Translation (DeepL)
Built as ordinary code, like the Dictionary; Phase 7 turns it into a module.

- [ ] Translation provider interface (core service).
- [ ] DeepL provider; Free/Pro detection; key in Credential Manager.
- [ ] First-launch key prompt (skippable); "Add a DeepL key" state on the button.
- [ ] Translation cache; error messages for no network / quota exceeded.

Done when: Translate shows English, and the app works fine without a key.

## Phase 6 — Anki
The first optional feature. Built as ordinary code with an on/off switch in Settings (off by default) until the module system exists in Phase 7.

- [ ] AnkiConnect client; connection check and helpful "Anki isn't running / add-on missing" messages.
- [ ] Create note types (Word: Reading + Meaning cards; Kanji) and deck on first use.
- [ ] ＋ Anki in word and kanji popups; ★ already-saved markers.
- [ ] Screenshot crop attached as media; offline queue that sends when Anki is back.
- [ ] Settings page: deck, card types, screenshot/audio, tag.

Done when: one click puts a full card into Anki, and it syncs to the phone.

## Phase 7 — Module system
Built once the first optional feature (Anki) exists, so it is designed around real modules.

- [ ] Manifest format, loader, `ModuleContext`, extension points, events, services.
- [ ] Enable / disable with restart-free reload where possible.
- [ ] Module Manager UI (list, enable, disable) — install/uninstall comes in Phase 8.
- [ ] Turn Dictionary (Phase 3), Translation (Phase 5) and Anki (Phase 6) into modules: register their popup sections, buttons, settings pages and services through the extension points; the app must still work with any of them disabled. Anki's Settings on/off switch is replaced by the Module Manager.
- [ ] A test module to prove each extension point.

Done when: modules can add popup buttons, window buttons, settings pages and services without the core knowing about them.

## Phase 8 — Installing modules after installation
- [ ] Module index (list of available modules, versions, download URLs, SHA-256).
- [ ] Download, verify checksum, install dependencies into the module's own folder, enable.
- [ ] Update and uninstall.

Done when: a module can be installed, updated and removed from the Module Manager.

## Phase 9 — Audio module
Built as a module from the start, using the Phase 7 module system.

- [ ] Windows Japanese TTS; ▶ for word and sentence.
- [ ] Attach audio to Anki notes when both modules are enabled.
- [ ] Clear message if no Japanese voice is installed.

## Phase 10 — Release
- [ ] Installer with optional module checkboxes, start-menu entry, uninstaller.
- [ ] Third-party notices and licences.
- [ ] Logging, crash reporting to a local log file.
- [ ] README with setup steps (Japanese OCR capability, Japanese voice, DeepL key, AnkiConnect) and capture tips (wait for the line to finish, select tightly, use borderless windowed mode).

## Order note
Reordered on 2026-11-21: features are built as ordinary code first (Dictionary, History, Translation, Anki), and the Module system comes once the first optional feature (Anki) exists. It then converts the existing features into modules; Audio is the first feature written as a module from the start. History (Phase 4) and Translation (Phase 5) don't depend on each other; History was moved first on 2026-11-21.
