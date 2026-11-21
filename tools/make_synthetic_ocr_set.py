"""Generate a synthetic OCR test set that imitates the game UI styles from the UI scan.

Run:  uv run python tools/make_synthetic_ocr_set.py [OUT_DIR]   (default tools/out/synthetic)

Each sample is <category>__<n>.png plus <category>__<n>.txt with the correct text.
This only checks the benchmark pipeline and gives a rough first comparison; real game
screenshots (tests/ocr_set/images/) are what decide the default engine.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONT = "C:/Windows/Fonts/YuGothM.ttc"
FONT_BOLD = "C:/Windows/Fonts/YuGothB.ttc"

DIALOGUE = [
    ("テララ", "そうだ、探しに行くまえにじっちゃ……村長の家に寄るぞ。", "森の異変のことを報告して、ついでに準備も手伝ってもらうんだ！"),
    ("ルルカ", "わたしたちを導いてくださる神さまでもあります。", ""),
    ("ルミィ", "コホン。いいか、あたしのことは「ルミィさま」と呼ぶのだ。", ""),
    ("リリカ", "オイラ、ほんとはわざとやってたんじゃないんだ。", "ここは寂しいし、外におかしなキボがいなかったらもっとはやく出てきてたよ……"),
    ("エンカク", "おう、テララ。", "道具の作り方を教えてやるところだ。"),
    ("ティナナ", "テララ！聞いてよ！", "カークのヤツ、貝殻10個でチシャヤシと交換してくれるって言ってたくせに……"),
]
MENU = [
    "普通の火元素と異なり、炎核に満ちたエネルギーは武器と共鳴し、強化することができる。",
    "昇級を完了するには以下のアイテムを消費します。一括で昇級を行いますか？",
    "【鍵×1】を消費して宝箱を開けますか？",
    "対応する生産設備に派遣すると、レシピの生産効率が418%上昇する",
    "累計で20体のキボとスターリンクする 7/20",
]
TIPS = [
    "ステラカードを使ってキボとスターリンクすると、冒険者の世界探索を大いに助けてくれます。",
    "ガヤックはおとなしくて力持ち。大陸で最も頼りになる貨物運送手段の一種——ただし、おなかがいっぱいのときに限ります。",
]


def _gradient(size, top, bottom, noise=12, seed=0):
    rnd = random.Random(seed)
    w, h = size
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(h):
        t = y / max(1, h - 1)
        base = [round(top[i] * (1 - t) + bottom[i] * t) for i in range(3)]
        for x in range(w):
            n = rnd.randint(-noise, noise)
            px[x, y] = tuple(max(0, min(255, c + n)) for c in base)
    # soft blobs to imitate a blurred 3D scene
    blobs = Image.new("RGB", size, (0, 0, 0))
    d = ImageDraw.Draw(blobs)
    for _ in range(8):
        cx, cy, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(40, 160)
        col = tuple(rnd.randint(0, 90) for _ in range(3))
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=col)
    return Image.blend(img, blobs.filter(ImageFilter.GaussianBlur(40)), 0.25)


def _shadow_text(img, xy_lines, font, fill=(255, 255, 255), shadow=(40, 40, 40)):
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for (x, y), text, f in [(xy, t, f) for xy, t, f in xy_lines]:
        d.text((x + 2, y + 2), text, font=f, fill=shadow + (200,))
    layer = layer.filter(ImageFilter.GaussianBlur(2))
    d = ImageDraw.Draw(layer)
    for (x, y), text, f in xy_lines:
        d.text((x, y), text, font=f, fill=fill + (255,))
    img.paste(layer, (0, 0), layer)


def dialogue(name, l1, l2, bg_top, bg_bottom, seed):
    w, h = 900, 150 if l2 else 110
    img = _gradient((w, h), bg_top, bg_bottom, seed=seed)
    f_name = ImageFont.truetype(FONT_BOLD, 22)
    f = ImageFont.truetype(FONT, 22)
    lines = [((w // 2 - 11 * len(name), 10), name, f_name)]
    for i, t in enumerate([l1, l2]):
        if t:
            tw = ImageDraw.Draw(img).textlength(t, font=f)
            lines.append(((int(w / 2 - tw / 2), 50 + i * 40), t, f))
    _shadow_text(img, [lines[0]], f_name, fill=(190, 220, 255))
    _shadow_text(img, lines[1:], f)
    truth = "\n".join([name, l1] + ([l2] if l2 else []))
    return img, truth


def panel(text, bg, fg, width=820, size=20):
    f = ImageFont.truetype(FONT, size)
    # wrap
    lines, cur = [], ""
    d = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    for ch in text:
        if d.textlength(cur + ch, font=f) > width - 40:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    h = 30 + len(lines) * (size + 14)
    img = Image.new("RGB", (width, h), bg)
    dr = ImageDraw.Draw(img)
    for i, line in enumerate(lines):
        dr.text((20, 15 + i * (size + 14)), line, font=f, fill=fg)
    return img, "\n".join(lines)


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "tools" / "out" / "synthetic"
    out.mkdir(parents=True, exist_ok=True)
    samples = []
    for i, (n, a, b) in enumerate(DIALOGUE):
        samples.append(("dialogue-dark", dialogue(n, a, b, (30, 45, 40), (10, 20, 30), i)))
    bright = [((235, 225, 200), (250, 240, 215)), ((170, 230, 240), (210, 245, 250)),
              ((200, 220, 240), (230, 240, 250))]
    for i, (n, a, b) in enumerate(DIALOGUE):
        top, bottom = bright[i % len(bright)]
        samples.append(("dialogue-bright", dialogue(n, a, b, top, bottom, 100 + i)))
    for t in MENU:
        samples.append(("menu-light", panel(t, (238, 232, 218), (60, 55, 50))))
    for t in TIPS:
        samples.append(("tip-light", panel(t, (245, 243, 240), (90, 90, 90), size=18)))
        samples.append(("tip-dark", panel(t, (12, 12, 14), (225, 225, 225), size=18)))
    counts: dict[str, int] = {}
    for cat, (img, truth) in samples:
        counts[cat] = counts.get(cat, 0) + 1
        stem = f"{cat}__{counts[cat]:02d}"
        img.save(out / f"{stem}.png")
        (out / f"{stem}.txt").write_text(truth, encoding="utf-8")
    print(f"Wrote {len(samples)} samples to {out}")


if __name__ == "__main__":
    main()
