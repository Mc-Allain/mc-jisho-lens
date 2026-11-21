"""OCR engine interface."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from PIL import Image


@dataclass
class OcrLine:
    text: str
    # (left, top, right, bottom) in input-image pixels, if the engine reports it
    box: tuple[int, int, int, int] | None = None
    score: float | None = None


@dataclass
class OcrResult:
    lines: list[OcrLine] = field(default_factory=list)
    seconds: float = 0.0

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines if line.text)


class OcrEngine(Protocol):
    name: str

    def recognize(self, image: Image.Image) -> OcrResult: ...
