"""Screen capture in physical pixels across the whole virtual desktop."""

from __future__ import annotations

from dataclasses import dataclass

import mss
from PIL import Image

from jisho_lens.core.displays import Display, get_displays, virtual_desktop_bounds


@dataclass(frozen=True)
class Rect:
    """Rectangle in physical virtual-desktop pixels."""

    left: int
    top: int
    width: int
    height: int

    @property
    def is_empty(self) -> bool:
        return self.width <= 0 or self.height <= 0


@dataclass
class DesktopShot:
    """A full virtual-desktop screenshot plus the display layout it was taken with."""

    image: Image.Image
    origin_left: int
    origin_top: int
    displays: list[Display]

    def crop(self, rect: Rect) -> Image.Image:
        x = rect.left - self.origin_left
        y = rect.top - self.origin_top
        return self.image.crop((x, y, x + rect.width, y + rect.height))

    def display_image(self, display: Display) -> Image.Image:
        return self.crop(Rect(display.left, display.top, display.width, display.height))


def grab_desktop() -> DesktopShot:
    displays = get_displays()
    left, top, width, height = virtual_desktop_bounds(displays)
    with mss.MSS() as sct:
        raw = sct.grab({"left": left, "top": top, "width": width, "height": height})
    image = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    return DesktopShot(image=image, origin_left=left, origin_top=top, displays=displays)


def grab_rect(rect: Rect) -> Image.Image:
    """Grab one rectangle directly from the screen (used to verify crops)."""
    with mss.MSS() as sct:
        raw = sct.grab(
            {"left": rect.left, "top": rect.top, "width": rect.width, "height": rect.height}
        )
    return Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
