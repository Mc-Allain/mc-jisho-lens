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
- [x] `history.db` + saved capture images.
- [x] History screen: list with thumbnails, open in main window, delete, retention setting.

**OCR data collection** (to improve OCR accuracy for this copy of the app) — **off by default, opt-in only**:
- [x] Ask once (first capture after install/update): "Allow Jisho Lens to keep your captures and corrections to improve OCR accuracy for your copy of the app? The data stays on this computer. Nothing is sent anywhere unless you export it and share it yourself." Buttons: Allow / Don't allow. The answer is saved; changeable any time in Settings ("Collect OCR data", off by default), with a "Delete collected data" button.
- [x] When allowed, each capture keeps: the screenshot crop, the OCR result, engine / image setting / time taken, text type, screen resolution and scaling. Not kept: anything outside the selected area, user names, file paths.
- [x] **Edit** saves the corrected text as the right answer; a **Correct ✓** button marks OCR output as right without edits. Only checked samples (✓ or edited) count for accuracy.
- [x] Collected samples are separate from History retention (deleting old history doesn't delete collected samples, and vice versa).

**Export / import / merge** (sharing between users is manual and opt-in):
- [x] **Export** a data pack (`.zip`): all, checked only, or one game; shows the crops before writing (screenshots can contain player names or chat). Includes a manifest (format version, app version, counts) and an anonymous random contributor ID, no personal details.
- [x] **Import** a pack: validate (only images + JSON, size limits, no unsafe paths), add to the local set.
- [x] **Merge / append** packs: duplicates detected by image content hash; different corrections of the same image kept side by side and flagged for review.
- [x] Export to the OCR test-set format (`tests/ocr_set/images/`) and run `tools/ocr_bench.py` on it: best engine and image setting per text type.
- [x] Command-line tools for export / import / merge, plus buttons in the History screen.
- [x] Remember my corrections: fixes made with Edit are applied to later captures (with Undo), while collection is on.
- [x] Space: one sample per sentence, one image file shared by History and OCR data, a size limit (300 MB by default) that never removes corrected samples or favorites.
- [x] Favorites (★) and History filters (All / Favorites / Corrected); delete selected, a time range, Clear history, Clear all. Favorites are never deleted until unstarred.
- [ ] (later) Voicing-mark repair using the dictionary (寄るそ → 寄るぞ before any correction exists).
- [ ] (later) Words people corrected (names, game terms) can be offered to the word splitter's list.

Notes: no automatic collection from other users and no server; packs are shared privately (game screenshots are the publisher's copyrighted material).

Done when: past captures can be browsed and reopened; with consent given, captures and corrections are kept locally, and packs can be exported, imported, merged and benchmarked.

Phase 4 notes (2026-11-22):
- History: `history.db` + PNG crops in the app data folder; the History window lists captures (thumbnail, time, engine, edited / collected / ✓ marks), opens one back in the main window (Retry and Edit work on it) and deletes one or all. Retention: keep the last 200 captures by default (Settings → Keep in History). History stores the text as shown (speaker separate); the raw OCR text is kept only in collected samples.
- OCR data collection is off until answered: the question appears once, after the first capture (default button: Don't allow). Settings → OCR data turns it on/off and deletes collected data. Each sample is named by the SHA-256 of its PNG, so repeated captures of the same image are one sample. Edit saves the correction as the right answer; ✓ Correct confirms OCR was right.
- Packs: `.zip` with `manifest.json` + `samples/<sha256>.png|json`; import rejects anything else (unexpected names, path tricks, oversized files, images that don't match their hash, bad JSON). Merging keeps differing answers side by side and flags them for review. Export shows the crops first. `tools/ocr_data.py` does export / import / merge / testset from the command line; the test set feeds `tools/ocr_bench.py`.
- Checked: 11 new tests (`tests/test_history_and_ocr_data.py`, 86 total); end to end with collection off (History only) and on (sample + ✓); reopening from History + Edit saves the correction.
- Remember my corrections (added after the first real captures: every OCR engine dropped voicing marks — そうた, 寄るそ, ついて, もらうんた — and a second, slightly different crop repeated the same mistakes). Edit learns each small change with one character of context on each side (at least 3 characters; a line start/end counts as context), e.g. 「うた、」→「うだ、」, and stores it in `ocr-data/corrections.json`. Later captures get those fixes before analysis; the status says "Applied N of your earlier corrections" and **Undo** shows the OCR text. A correction is forgotten when the user puts the OCR text back (Edit) or confirms it with ✓ after Undo. Big rewrites (over 6 characters) and line joins/splits aren't learned. Corrections saved before this existed are learned once from the edited samples. Settings → OCR data → Learned corrections lists and deletes them. Collected samples keep the raw OCR text, so the data stays honest. Checked: 7 tests (`tests/test_corrections.py`, 93 total); end to end on the two real captures: capture 1 + Edit learns 4 fixes, capture 2 shows all 4 applied, Undo restores the OCR text.
- Space. The same dialogue line captured 4 times (4 slightly different crops) had become 4 samples (0.8 MB) plus 4 History copies. Now: a capture is not kept as a new sample when its OCR text equals a kept sample's OCR text or right answer (speaker line included); its capture points at that sample, so Edit and ✓ update it. History and OCR data share one PNG through a hard link when the sample is exactly that image. Settings → OCR data space (300 MB default, 0 = no limit) removes the oldest unchecked samples first; corrected (edited / ✓) samples and favorites' samples are never removed automatically, even over the limit. A one-time tidy (`ocr-data/tidy-1.done`) merges duplicates kept earlier (corrected ones all stay) and links identical images. On a copy of the real data: 4 samples (791 KB) → 2 (332 KB), and a fifth crop of the same line added no sample.
- Favorites: ★ Favorite in the main window (for any capture in History) and in History. Favorites are skipped by single/multi delete, time-range delete, Clear history, Clear all, Delete collected data and the History limit (they don't count towards it); remove the star to delete one. History filter: All / ★ Favorites / Corrected (fixed with Edit). Delete options: Delete (selected; Ctrl/Shift for several), Delete range… (from–to, shows how many go and how many favorites stay), Clear history… (History only), Clear all… (History, collected samples including corrected ones, learned corrections). Old `history.db` files get the `favorite` column on open.
- Window stacking (revised 2026-11-23): History, Settings, About and every dialog / message box opened from them or from the text window belong to the text window but are not owned by it natively (an owned window can never go behind its owner). They open in front of it (always-on-top while focused) and come back in front when clicked; when the focus leaves them for the text window or another app they stop being always-on-top and go behind that window. Moving between them (History -> Settings) doesn't send them behind. A window opened from the tray before the text window exists is adopted when it is created. Closing (hiding) the text window leaves them open. Checked with the real z-order.
- On a new capture (Settings → On new capture): **Keep other windows, text window in front** (default): they stay open; the new text window comes in front of them (they are unowned for that) until the user clicks or activates one of them, which makes them all belong to the text window again (in front of it). Only a click counts: when the capture overlay closes, Windows activates one of them by itself, which first undid "in front" (fixed; the text window is also put in front again 200 ms later unless the user clicked one of them). **Keep other windows in front of the text window**. **Close other windows**: History, About and every dialog / message box close; Settings closes too unless a component is installing, then it is only hidden and reopens with the current progress. An unanswered consent question closed this way stays unanswered (asked again next capture). Open windows are never in the screenshot: they are left out of screen capture (WDA_EXCLUDEFROMCAPTURE) during the grab, including the capture-delay wait.
- Pack review (2026-11-23): packs contain only samples **fixed with Edit**; ✓ and unchecked samples stay on the computer (the local OCR test set still uses ✓ samples). Import and merge are two steps: `read_pack` (validates; nothing written; pictures read again from the pack when applied, hash re-checked) -> review window `ui/pack_review.py` -> `apply_import` / `apply_merge`. Rows: New (included), Different answer (included; Keep mine by default, or Use theirs — yours kept as alternative — or Keep as alternative), Same sentence (another crop of a sentence you have; excluded by default), Same (nothing to do). Samples in a pack without an Edit fix (older packs) are left out and counted. Merge: packs that disagree on a picture give one row with each pack's answer (Keep all, or use one pack's). Footer: selected count, MB added, OCR data before -> after vs the limit. "Also learn OCR fixes from these" (off by default) feeds Remember my corrections. Filters by status and contributor; Select all / none; pictures load a few at a time; double-click a picture for full size. Generic so translation packs (Phase 5) reuse it. `tools/ocr_data.py import` has `--different keep|theirs|alternative`, `--same-sentence`, `--learn`, `--dry-run`; `merge` has `--same-sentence`. Checked: 8 pack tests (113 total); both windows rendered with two people's sample data.
- Pack names and the Using label (2026-11-23): export and merge ask for your pack name (remembered; `series.json` keeps each name's last version, also after deleting data) and save the next version, `NAME-vN.zip`. The manifest has name, `series_version`, `pack_id`, `sources` and `log` (this release + your earlier releases of that name + the logs of the packs it was made from; each line: name vN · date · by contributor ID · exported/merged: sources · samples). Older packs: file name as label, "no history", identified by their samples. `imports.json` records per imported pack the samples used and declined; the label is computed from what is in your data now: a pack is listed while any of its used samples is present, "(partial)" when you declined some (unticked, Keep mine) or deleted some since; skipped duplicates don't count; "+ own data" when you have samples you collected; more than 3 packs are shortened ("+ N more packs"). Shown in History's OCR data box (hover: each pack's counts and the history), live in the import review ("Using now → after import"), and as "Merged pack made from" in the merge review; each pack has a header with name, contributor and a History… button. Delete collected data / Clear all clear the import records. `tools/ocr_data.py export|merge --name`. Checked: 9 tests (`tests/test_provenance.py`, 122 total) and the screens rendered with three people's sample data.
- No game name (removed 2026-11-23): samples, packs, settings and the review screens don't record or filter by game. A game name is easy to forget to change when capturing another game or another part of the screen, so the data stays general. Older samples, packs and settings that still have a game name load fine; it is ignored.
- Categories (2026-11-23): samples have a `category` label, blank by default, set only when exporting or merging (so it can't be left on by mistake like a game setting). The old hidden field `category` ("dialogue" / "text", used by the OCR benchmark file names) is now `text_type`; older samples and packs are converted when read. Export opens the review window (mode "export": what OCR read / your fix, Include, Category; pack name, version and history log in the same window; `apply_export` also saves the labels on your samples). Every review has a Category column, a category filter, and Tick / Untick for a whole category; export and merge have "Label as" (suggestions: "Azur Promilia JP" from `core/categories.py`, then categories in use) for the ticked rows shown. Imports keep a pack's categories. Each history-log line lists the release's categories ("Categories: Azur Promilia JP 40, none 3"). `tools/ocr_data.py export|merge --category CAT --only CAT`. Checked: 6 tests (`tests/test_categories.py`, 129 total); export and merge reviews rendered with sample data.
- Review polish: "Label ticked rows as" applies as soon as a category is picked (or typed + Enter / leaving the box) — no separate button to miss; a note says how many were labelled. When the main button (Export / Import / Save merged pack) is disabled, a line next to it says why ("Tick at least one row to export.", "Enter a pack name in the Pack name box to export."), also as its hover text. Pack file dialogs (export, import, merge, test set) use Qt's own file dialog (`ui/file_dialogs.py`), which the stacking rules put in front of its window; Windows' own file dialog is not always-on-top and could open behind History. Checked with WindowFromPoint. Every file dialog starts in the Downloads folder (asked from Windows, so a moved Downloads works; fallback `C:\Users\<user>\Downloads`). Only one file dialog at a time: opening another cancels the one already open (`tests/test_file_dialogs.py`).
- Edge-case review (2026-11-23), `tests/test_edge_cases.py` (19 tests, 150 total), fixed: a damaged sample file or an empty/damaged contributor ID no longer crashes (sample skipped; new ID); damaged `series.json` / `imports.json` are read safely; packs with a non-number version, wrong data types in a sample or damaged compressed data are refused with a clear message instead of crashing; a pack moved, deleted or replaced between the review and Import / Save is caught before anything is written; samples with empty OCR text (OCR read nothing) are no longer treated as one sentence; exporting or merging with nothing ticked is refused (no empty pack, no version used); re-importing your own pack doesn't list it as a pack in "Using:"; the same pack chosen twice for a merge counts once; text from packs (contributor ID, history log) is escaped in the review header and hover texts; pressing the capture hotkey twice quickly opens one overlay; a new capture during the capture delay replaces the waiting one (the old area isn't read); "Esc cancels" is only shown when Esc could be registered; a show/hide hotkey that can't be registered is mentioned in the startup notice. Checked fine as they were: learning from a rewrite (no rules), the same-image Retry, favorites' samples, History hard links.
- Source pack and Manage OCR data (2026-11-23): every sample has a source pack (`source_pack`, `source_pack_id`): the pack it was imported from, or "own data". Importing sets it (New, an answer added, Use theirs; not for your own packs). Changing a sample's answer (Edit in the text window, ✓ with other text, or Manage → Edit answer) makes it your own data, and its pack "(partial)" ("1 changed by you"); deleting one does too ("1 deleted since"). Import records keep "used" (the pack's answer is the answer) apart from "same" (identical already, or kept as an alternative), which never make a pack partial. Samples saved before this have an unknown source and are filled in once from the import records (`sources-1.done`). Manage OCR data (tray menu, History → OCR data): every sample with picture, OCR read, right answer, status, Source pack, category, added; filters by source pack, category, status and text; a tick box per row with Select all / none (rows shown); Delete ticked (favorites' samples are kept); Edit answer(s): with several ticked, one editor opens on the first ticked (the latest) and ◀ Prev / Next ▶ go through them, changes kept until Save changes (count shown), Cancel discards; double-click a row to edit just that one. With nothing ticked, the highlighted row(s) work the same (edit, label, delete). Label as (applies on pick / Enter) and Remove category (takes the category off; also in the export / merge reviews). OCR read / Right answer show the differences highlighted, and the editor shows them live. Tested through the real buttons (`tests/test_data_manager.py`): Edit once crashed because a button's clicked() passes a checked value. A Source pack column is in the export / import / merge reviews, and History marks captures "from <pack>". The text window's "OCR data:" line updates after edits. Checked: 7 tests (`tests/test_source_pack.py`, 157 total); the Manage window driven with sample data.
- History ↔ OCR data links (2026-11-23, found with real data): a capture of a sentence you already had was linked to the first matching sample, whatever its answer; a favorite then protected a sample with a different (wrong) answer, and Clear all deleted the sample with the favorite's text. Now: a new capture links to the sample whose answer is the text it shows (after your corrections); starring a capture (text window or History) and a one-time repair at start (`relink-1.done`) relink captures whose sample has another answer: to a sample with the capture's text, or, for favorites and edited captures, to their own picture kept as a sample with that text. Editing an answer in Manage, or Edit in the text window, updates every History capture using that sample. Manage has an "In History" column (★ favorite / N captures, with times on hover) and Delete says which favorite keeps a sample. Checked: `tests/test_capture_links.py` (5 tests, 166 total) and the repair on a copy of the real data.
- Versions only for changes (2026-11-23): each release remembers what it contained (`series.json`: a fingerprint of every sample's answer and category, and its pack ID). An export or merge with no changes since the last version is saved again as that same version (same pack ID, no new history line); otherwise the next version, and its history line says what changed ("1 new, 1 changed, 1 removed"; the first one says "first release"). The export screen shows "Changes since NAME vN: …" or "No changes since NAME vN". There is no reset option for users (it would let a pack's numbering restart and hide earlier versions); `Provenance.reset_series` exists for support only. Checked: `test_changes_since_the_last_version_and_start_over` (167 total) and the export screen rendered with and without a change.
- Same as OCR (2026-11-23): an answer saved with Edit that equals what OCR read (ignoring spaces, line breaks and the speaker line OCR read) is not a fix: its status is "Same as OCR" (like ✓), it isn't exported in packs and doesn't count as edited (`Sample.is_fix`, `Sample.state`). Manage's status filter: Fixed with Edit / Same as OCR / Not checked.
- Your fix of a known sentence (2026-11-23, found with real data): capturing a sentence you already fixed (the same OCR reading as a sample fixed with Edit) shows your fix at once ("Your fix from earlier"; Undo shows what OCR read; the latest fix wins; a fix equal to OCR, empty text or a speaker-only answer is ignored; only while collecting). The Manage editor starts without the speaker line, and Manage edits update History and teach corrections like Edit (while collecting). Edge cases: `tests/test_known_fix.py` (12 tests).
- Speaker's name editing (2026-11-23): the text window's Edit has a Speaker box above the text (Save Edit saves name and text, Cancel / Esc discard both; empty = no speaker), and Manage OCR data's editor has one too. Manage and the export review show the name in the same cell as the dialogue (first line, bold blue; no separate column), with the differences highlighted in both (`sample_html`). Samples keep the name as OCR read it (`speaker`) and your correction (`speaker_fix`, "" = no speaker), so later captures are still recognised; a corrected name counts as a fix (exported, partial for pack samples). History captures using the sample follow the name; capturing the same sentence again shows the corrected name; Undo shows the name as read. Edge cases: `tests/test_speaker_edit.py` (9 tests).
- Learned corrections follow their fixes (2026-11-23, found with real data: a sample was deleted in Manage but its learned correction kept being applied): each correction records the samples it came from; it is kept only while a sample you fixed supports it (its answer still has that fix, or its OCR reading → answer gives it). Checked and cleaned at start, after Manage edits/deletes, after History / Settings deletions and imports. Edge cases: `tests/test_correction_prune.py` (6 tests).
- Undo Fix / Redo Fix / Save Undo (2026-11-23): the text window's Undo is now **Undo Fix** (shows the text and name as OCR read them; nothing saved). It turns into **Redo Fix**, which brings the fix back exactly as it was (text, name, status, ✓ state). After Undo Fix the ✓ button reads **Save Undo**: it saves the text and name as OCR read them as the right answer (History and other captures of the sentence follow; corrections learned from the replaced fix are forgotten; Redo Fix goes away). The ✓ button reads ✓ Saved only when the text and name shown are the saved answer. Edit, a new capture or opening from History clear Undo / Redo. Checked with real clicks in the app (31 checks).
- Fixes checked at every capture (2026-11-23, found with real data: editing a fix back to the OCR text by hand left its learned correction, and a reverse one, so the next capture was corrected again). Learned corrections are now checked against your fixes before every capture uses them (re-checked only after a fix-related change: an answer or speaker name saved, a sample with an answer deleted or re-read differently, everything deleted; not after new captures, repeat captures or category labels — about 0.5 µs when skipped, ~11 ms for 500 fixes when it runs), whatever changed the data; an Edit learns from what OCR read -> your answer (never from what was shown, so going back to the OCR text teaches nothing). Phase 4 scenario tests (`tests/test_phase4_scenarios.py`) drive the real app with a stand-in OCR (`tests/app_harness.py`) through every way of changing OCR data (Edit, Cancel, Edit back, Undo Fix / Redo Fix / Save Undo, ✓, Manage edit / delete, Delete collected data, Clear all with and without favorites, name fixes, another sentence with the same misread, reopening from History, export, imported fixes, collection off) and check the next capture and the dependents; disabling the correction check makes 5 of them fail.
- Save Edit after Undo Fix (2026-11-23, found with real data: Undo Fix -> Edit -> Done saved nothing, so the fix kept correcting later captures). Edit's button is now **Save Edit**. After Undo Fix the shown text isn't saved yet, so Save Edit saves it even without changes, like Save Undo: the sample's answer becomes the OCR text and the corrections that were undone are forgotten. Edit -> Cancel after Undo Fix still saves nothing; Undo -> Redo -> Save Edit keeps the fix. The bottom bar wraps whole button groups to more rows on a narrow window (it used to overlap buttons below ~600 px, worse while editing). Checked: `tests/test_phase4_scenarios.py` (33, incl. no overlapping controls at 380-900 px in view and edit mode).
- Hotkeys: a second global hotkey shows / hides the text window (default Ctrl+Alt+K; Settings → Show/hide window, Clear = none; must differ from the capture hotkey). Esc cancels a capture after the area is selected: during the capture delay and while reading. Esc is registered as a global hotkey only for those seconds and released when the text arrives, fails or is cancelled; a cancelled OCR job's result is ignored and the previous text stays. (Esc / right-click already cancelled the selection overlay.) Checked: hotkey test (named hotkeys, Esc), end to end (cancel while reading, cancel during the delay, normal read releases Esc, show/hide toggles).
- Install progress: the UniDic pip install and the full UniDic download now report every second (elapsed time, the download percentage when the tool prints one, MB written so far) instead of one message for several minutes, so Settings always shows the current state, also after being hidden and reopened.
- Checked: 13 tests (`tests/test_storage.py`, 106 total); end to end on a copy of the real data (tidy, repeat capture, ★, delete refused, filters, range preview).

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
- [ ] Uninstall keeps your data by default: it asks "Also delete my data (History, OCR data, learned corrections, settings)?", unticked. Reinstalling then keeps everything, including the anonymous contributor ID in packs (`ocr-data/contributor.txt`), so later packs still show the same ID.
- [ ] Third-party notices and licences.
- [ ] Logging, crash reporting to a local log file.
- [ ] README with setup steps (Japanese OCR capability, Japanese voice, DeepL key, AnkiConnect) and capture tips (wait for the line to finish, select tightly, use borderless windowed mode).

## Order note
Reordered on 2026-11-21: features are built as ordinary code first (Dictionary, History, Translation, Anki), and the Module system comes once the first optional feature (Anki) exists. It then converts the existing features into modules; Audio is the first feature written as a module from the start. History (Phase 4) and Translation (Phase 5) don't depend on each other; History was moved first on 2026-11-21.
