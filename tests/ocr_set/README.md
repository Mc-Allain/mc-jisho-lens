# OCR test set (real game screenshots)

Put screenshots in `tests/ocr_set/images/` (ignored by git: game screenshots stay local).

For each screenshot:

- **Crop it the way you would select it in the app** (just the text area, a little margin).
- Name it `<category>__<short-name>.png`, e.g. `dialogue-bright__terara-01.png`.
- Add a text file with the same name and `.txt` containing exactly the Japanese text in the
  image, one line per on-screen line, UTF-8. Include the speaker name as the first line for
  dialogue. Leave out key icons like [Q].

Categories (from docs/research/ui-text-scan.md) and target counts:

| Category | What | Count |
|---|---|---|
| `dialogue-dark` | Dialogue over a dark or neutral scene | ~6 |
| `dialogue-bright` | Dialogue over a bright scene (cream, cyan, sky, white glow) | ~6 |
| `dialogue-speaker` | Dialogue including the speaker name line | ~3 |
| `menu-light` | Menus and descriptions, dark text on light panels | ~6 |
| `tip-light` / `tip-dark` | Loading tips, both versions | ~2 |
| `hint-icons` | Tutorial text and prompts with key / mouse icons | ~3 |
| `quest` | Quest tracker | ~2 |
| `snow` | HUD over snow (white on white) | ~2 |

Then run:

```
uv run python tools/ocr_bench.py
```

The report (accuracy per category for every engine and preprocessing preset) is printed and
saved to `tools/out/`.
