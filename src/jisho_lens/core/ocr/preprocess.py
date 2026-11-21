"""Image preprocessing presets applied before OCR.

Presets (from the game UI scan, docs/research/ui-text-scan.md):
  none        unchanged
  upscale     enlarge small captures so text is ~40 px tall or more
  contrast    upscale + grayscale + autocontrast, then auto polarity -> dark text on light
  white-text  upscale + keep only bright, low-saturation pixels (white dialogue text over
              3D scenes) -> black text on white
  auto        white-text if the capture looks like light text on a busy/bright background,
              otherwise contrast
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

PRESETS = ("none", "upscale", "contrast", "white-text", "auto")

# Captures smaller than this (shortest side) get enlarged.
_TARGET_MIN_SIDE = 400
_MAX_SCALE = 3.0


def upscale(image: Image.Image) -> Image.Image:
    short = min(image.size)
    if short >= _TARGET_MIN_SIDE:
        return image
    scale = min(_MAX_SCALE, _TARGET_MIN_SIDE / max(1, short))
    size = (round(image.width * scale), round(image.height * scale))
    return image.resize(size, Image.Resampling.LANCZOS)


def is_light_on_dark(gray: Image.Image) -> bool:
    """True when the background (the border of the image) is darker than mid grey."""
    a = np.asarray(gray, dtype=np.uint8)
    h, w = a.shape
    k = max(1, min(h, w) // 10)
    border = np.concatenate([a[:k].ravel(), a[-k:].ravel(), a[:, :k].ravel(), a[:, -k:].ravel()])
    return float(np.median(border)) < 128


def contrast(image: Image.Image) -> Image.Image:
    gray = ImageOps.autocontrast(upscale(image).convert("L"), cutoff=1)
    if is_light_on_dark(gray):
        gray = ImageOps.invert(gray)
    return gray.convert("RGB")


def white_text_mask(image: Image.Image, min_value: int = 200, max_saturation: int = 60):
    hsv = np.asarray(image.convert("HSV"), dtype=np.uint8)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    return (v >= min_value) & (s <= max_saturation)


def white_text(image: Image.Image) -> Image.Image:
    big = upscale(image).convert("RGB")
    mask = white_text_mask(big)
    out = np.where(mask, 0, 255).astype(np.uint8)  # text black, rest white
    img = Image.fromarray(out, mode="L").filter(ImageFilter.MedianFilter(3))
    return img.convert("RGB")


def _looks_like_white_text(image: Image.Image) -> bool:
    """Heuristic: a few percent of pixels are near-white and the rest is not a plain
    light panel (light panels have mostly bright pixels)."""
    small = image.convert("RGB")
    small.thumbnail((400, 400))
    mask = white_text_mask(small)
    white_share = float(mask.mean())
    bright_share = float((np.asarray(small.convert("L")) >= 180).mean())
    return 0.01 <= white_share <= 0.35 and bright_share < 0.6


def apply(image: Image.Image, preset: str) -> Image.Image:
    if preset == "none":
        return image.convert("RGB")
    if preset == "upscale":
        return upscale(image).convert("RGB")
    if preset == "contrast":
        return contrast(image)
    if preset == "white-text":
        return white_text(image)
    if preset == "auto":
        return white_text(image) if _looks_like_white_text(image) else contrast(image)
    raise ValueError(f"unknown preset {preset!r}")
