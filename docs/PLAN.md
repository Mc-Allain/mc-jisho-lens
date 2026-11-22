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
│  └─ components.py          install / remove UniDic, JMdict, KANJIDIC2, Wiktionary
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

- [x] `tools/build_dictionary.py`: JMdict + KANJIDIC2 → SQLite with indexes for kanji form, kana form, and kanji character.
- [x] Lookup by lemma + reading, ranked by reading match and commonness.
- [x] Word popup: meanings by part of speech, conjugation breakdown, particle notes, loanword source, common/JLPT markers.
- [x] Kanji popup: on/kun readings (current one highlighted), meanings, strokes, grade, JLPT, example words.
- [x] "Not in dictionary" state for game terms and names: reading + romaji + per-kanji breakdown.
- [x] **Word-boundary check using JMdict** (idea from 2026-11-21 review): take MeCab's top alternative splits (`nbestToNodeList`) and move a boundary character to the next word only when (a) that creates a *common* JMdict word, (b) the word it leaves is *not* common, and (c) the leftover piece is still a dictionary word. Fixes 火元 + 素 → 火 + 元素 without breaking 攻撃 + 力, 日本 + 人, 大陸 + 中. A naive version without JMdict was tested and rejected: it fixed 火元素 but broke 攻撃力 → 攻 + 撃力, 日本人 → 日 + 本人, 大陸中 → 大 + 陸中.
- [x] **Compound readings for coined words**: when a run of single-kanji tokens isn't a JMdict word (炎 + 核, 翼 + 人), offer the on'yomi reading from KANJIDIC2 in the popup as an alternative (えんかく, よくじん) and mark it as a guess.
- [x] Re-evaluate UniDic-lite vs full UniDic once the JMdict checks are in place (suggestion on 2026-11-21: JMdict covers lite's gaps, saving 526 MB). Compare on real game lines.
- [x] Attribution in an About screen.

Done when: word and kanji popups are complete and work offline.

Phase 3 notes (2026-11-21):
- `tools/build_dictionary.py` downloads JMdict_e and KANJIDIC2 from edrdg.org (10.6 + 1.5 MB) and builds `data/dictionary.sqlite` (66 MB, ~10 s): 219,188 words, 13,108 kanji, plus a kanji → common-words table for examples. `data/` is git-ignored; the database is derived EDRDG data (CC BY-SA 4.0).
- Lookups use UniDic's dictionary form + lemma, keep only entries with the reading used in the sentence and a compatible part of speech (the particle は no longer lists 葉/歯). Popup data for a page takes ~50 ms.
- Popup: meanings grouped by part of speech with usage tags and loanword sources, "common word" marker, grammar breakdown for verb/adjective phrases (食べられなかった → 食べる + passive/potential + negative + past; 手伝ってもらう → te-form + てもらう), particle notes, longer dictionary words starting at the word (攻撃 → 攻撃力), clickable kanji panel (on/kun with the reading used here highlighted, strokes, grade, old JLPT level, frequency, common example words).
- JLPT levels for *words* are not in JMdict, so they aren't shown; kanji show the old 4-level JLPT from KANJIDIC2.
- Word-boundary check: fixes 火元 + 素 → 火 + 元素 and 大 + 陸中 → 大陸 + 中; leaves 攻撃力, 日本人, 経験値, 強化素材, 生産効率 alone (tests in `tests/test_dictionary.py`). On 40 game lines it changed 6 splits.
- Coined compounds: 炎 + 核 → "maybe えんかく?", 翼 + 人 → "maybe よくじん?" (12 guesses on the 40 lines).
- Katakana names: the joining rule now also covers pieces UniDic labels as symbols or doesn't know (ミィティ, シャラカ), while real compounds stay split (スター + リンク, キボ + ホイール).
- **UniDic-lite vs full, re-evaluated with the JMdict checks** (`tools/compare_unidic.py`, 40 game lines): practically identical (503 vs 502 words, 22 vs 22 without a meaning, 6 vs 6 split fixes). Full was better on 2 lines: 大陸中 read じゅう (lite: ちゅう, wrong) and 長押し kept whole (lite: 長 + 押し). Lite saves 526 MB on disk. Decision pending (user).
- About screen (tray menu) shows the EDRDG attribution and data versions.
- **Decision 2026-11-22:** word splitting is now a setting — UniDic-lite (default, user's preference), full UniDic, or None (plain text). Full UniDic was removed from the environment; both UniDics are optional install groups (`unidic-lite` installed by default via `[tool.uv] default-groups`, `unidic-full` on request). The Dictionary (JMdict + KANJIDIC2) is its own on/off setting, only available with lite or full. Without the dictionary, words keep readings, romaji and grammar; the popup shows no meanings. Tests in `tests/test_modes.py`; e2e checked in all three setups.
- **Wiktionary words (2026-11-22)**, to fix dialect / casual words JMdict lacks (じっちゃ, "grandpa"): `build_dictionary.py` imports the kaikki.org Japanese data (48.6 MB download, CC BY-SA 4.0) and keeps 22,547 Wiktionary words that JMdict doesn't have (popup shows them marked "From Wiktionary"). It also builds a MeCab **user dictionary** per installed UniDic (`data/userdic-lite.dic`, 6,058 nouns of 3+ kana or 2+ characters with kanji that UniDic doesn't know), used only when the Dictionary setting is on. Word cost 7000: fixed まえ + に + じっちゃ and changed ~1% of 2,000-3,000 sample sentences, almost all into real compounds (受話口, 聖騎士, チョコパイ); cost 4000 produced bad splits (亜 + 麻色).
- Boundary check tightened at the same time (2026-11-22): it now only changes a split that contains a fragment (one-letter prefix/suffix, stray kana, or unknown non-katakana piece) and never accepts a new split that leaves a stray kana, and it never splits a Wiktionary word back up. Fixes two Phase 3 regressions: ほんと → ほん + と and お + ばあ → おば + あ; unknown katakana loanwords stay whole (テンプレ). On 2,000 sample sentences the JMdict check changed 4 splits. Tests in `tests/test_dictionary.py` (70 tests total).
- Seen while testing: with a game and screen recorder running (CPU ~55%), OCR took 3.6–3.9 s per capture instead of ~1.5–2 s, so GPU OCR remains important. OCR also split one line at "……" in a sample image (read as a line break + "・").
- **Components (2026-11-22):** UniDic-lite, full UniDic, JMdict, KANJIDIC2 and Wiktionary are now optional components, none installed by default (word splitting defaults to None = plain text). Each installs into its own folder (`data/components/` from source): UniDic via `pip --target`, each dictionary into its own SQLite file. Dictionaries can only be installed while a UniDic is installed and are removed with the last UniDic. Settings → Components has Install/Remove buttons (background work with progress); `tools/components.py` does the same from the command line and replaces `tools/build_dictionary.py`. The Wiktionary word-splitter list is rebuilt when a UniDic, Wiktionary or JMdict is installed or removed, and leaves out JMdict words while JMdict is installed (including them changed ~19% of sample sentences instead of ~1.4%). Removal works while the app has the files open (MeCab/SQLite are released first). Tests: `tests/test_components.py` (75 tests total).


## Phase 4 — History and OCR data collection

**History** (core):
- [ ] `history.db` + saved capture images.
- [ ] History screen: list with thumbnails, open in main window, delete, retention setting.

**OCR data collection** (to improve OCR accuracy for this copy of the app) — **off by default, opt-in only**:
- [ ] Ask once (first capture after install/update): "Allow Jisho Lens to keep your captures and corrections to improve OCR accuracy for your copy of the app? The data stays on this computer. Nothing is sent anywhere unless you export it and share it yourself." Buttons: Allow / Don't allow. The answer is saved; changeable any time in Settings ("Collect OCR data", off by default), with a "Delete collected data" button.
- [ ] When allowed, each capture keeps: the screenshot crop, the OCR result, engine / image setting / time taken, text type, game name (optional), screen resolution and scaling. Not kept: anything outside the selected area, user names, file paths.
- [ ] **Edit** saves the corrected text as the right answer; a **Correct ✓** button marks OCR output as right without edits. Only checked samples (✓ or edited) count for accuracy.
- [ ] Collected samples are separate from History retention (deleting old history doesn't delete collected samples, and vice versa).

**Export / import / merge** (sharing between users is manual and opt-in):
- [ ] **Export** a data pack (`.zip`): all, checked only, or one game; shows the crops before writing (screenshots can contain player names or chat). Includes a manifest (format version, app version, counts) and an anonymous random contributor ID, no personal details.
- [ ] **Import** a pack: validate (only images + JSON, size limits, no unsafe paths), add to the local set.
- [ ] **Merge / append** packs: duplicates detected by image content hash; different corrections of the same image kept side by side and flagged for review.
- [ ] Export to the OCR test-set format (`tests/ocr_set/images/`) and run `tools/ocr_bench.py` on it: best engine and image setting per text type.
- [ ] Command-line tools for export / import / merge, plus buttons in the History screen.
- [ ] Words people corrected (names, game terms) can be offered to the word splitter's list (later).

Notes: no automatic collection from other users and no server; packs are shared privately (game screenshots are the publisher's copyrighted material).

Done when: past captures can be browsed and reopened; with consent given, captures and corrections are kept locally, and packs can be exported, imported, merged and benchmarked.

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
- [ ] Turn Word splitting (UniDic-lite / full), Dictionary (Phase 3), Translation (Phase 5) and Anki (Phase 6) into modules (the Dictionary module requires a Word splitting module; removing word splitting disables the dictionary): register their popup sections, buttons, settings pages and services through the extension points; the app must still work with any of them disabled. Anki's Settings on/off switch is replaced by the Module Manager.
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
