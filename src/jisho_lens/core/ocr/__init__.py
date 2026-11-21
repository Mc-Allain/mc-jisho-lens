"""OCR engines and preprocessing."""

from jisho_lens.core.ocr.base import OcrEngine, OcrLine, OcrResult

ENGINE_NAMES = ("windows", "rapid-v6", "rapid-v5-server", "rapid-v4-japan")


def create_engine(name: str) -> OcrEngine:
    if name == "windows":
        from jisho_lens.core.ocr.windows_ocr import WindowsOcrEngine

        return WindowsOcrEngine()
    from jisho_lens.core.ocr.rapid import RapidOcrEngine

    return RapidOcrEngine(name)


__all__ = ["ENGINE_NAMES", "OcrEngine", "OcrLine", "OcrResult", "create_engine"]
