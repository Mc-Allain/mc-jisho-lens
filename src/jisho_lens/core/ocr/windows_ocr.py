"""Windows built-in OCR (Windows.Media.Ocr) for Japanese.

Needs the Japanese OCR language capability installed in Windows
(Settings > Time & language > Language > Japanese > Optional features, or
`Add-WindowsCapability -Online -Name "Language.OCR~~~ja-JP~0.0.1.0"`).

Windows OCR puts spaces between Japanese characters; they are removed here.
"""

from __future__ import annotations

import asyncio
import re
import time

from PIL import Image

from jisho_lens.core.ocr.base import OcrLine, OcrResult

# A space between two non-ASCII characters is an artifact of Windows OCR for Japanese.
_CJK_SPACE = re.compile(r"(?<=[^\x00-\x7F])\s+(?=[^\x00-\x7F])")


def _join(text: str) -> str:
    return _CJK_SPACE.sub("", text)


class WindowsOcrEngine:
    name = "windows"

    def __init__(self, language: str = "ja") -> None:
        from winrt.windows.globalization import Language
        from winrt.windows.media.ocr import OcrEngine

        lang = Language(language)
        if not OcrEngine.is_language_supported(lang):
            raise RuntimeError(
                f"Windows OCR language {language!r} is not installed. "
                "Add the Japanese OCR capability in Windows settings."
            )
        self._engine = OcrEngine.try_create_from_language(lang)
        self.max_dimension = OcrEngine.max_image_dimension

    def recognize(self, image: Image.Image) -> OcrResult:
        image = image.convert("RGBA")
        if max(image.size) > self.max_dimension:
            scale = self.max_dimension / max(image.size)
            image = image.resize(
                (int(image.width * scale), int(image.height * scale)), Image.Resampling.LANCZOS
            )
        start = time.perf_counter()
        result = asyncio.run(self._recognize(image))
        seconds = time.perf_counter() - start
        lines: list[OcrLine] = []
        for line in result.lines:
            words = list(line.words)
            box = None
            if words:
                rects = [w.bounding_rect for w in words]
                box = (
                    int(min(r.x for r in rects)),
                    int(min(r.y for r in rects)),
                    int(max(r.x + r.width for r in rects)),
                    int(max(r.y + r.height for r in rects)),
                )
            lines.append(OcrLine(text=_join(line.text), box=box))
        return OcrResult(lines=lines, seconds=seconds)

    async def _recognize(self, image: Image.Image):
        from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
        from winrt.windows.storage.streams import DataWriter

        # SoftwareBitmap wants BGRA8
        r, g, b, a = image.split()
        bgra = Image.merge("RGBA", (b, g, r, a)).tobytes()
        writer = DataWriter()
        writer.write_bytes(bgra)
        buffer = writer.detach_buffer()
        bitmap = SoftwareBitmap.create_copy_from_buffer(
            buffer, BitmapPixelFormat.BGRA8, image.width, image.height
        )
        return await self._engine.recognize_async(bitmap)
