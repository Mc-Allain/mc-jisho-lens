"""RapidOCR (PaddleOCR PP-OCR models on ONNX Runtime).

Variants:
  rapid-v6         RapidOCR's bundled default (PP-OCRv6 small det + rec). No download.
  rapid-v5-server  PP-OCRv5 det (mobile) + PP-OCRv5 rec (server). The PP-OCRv5 "ch" recognizer
                   covers Chinese, Japanese and English. Downloads models on first use.
  rapid-v4-japan   PP-OCRv4 det (mobile) + dedicated Japanese PP-OCRv4 rec (mobile).
                   Downloads models on first use.
"""

from __future__ import annotations

import time

import numpy as np
from PIL import Image

from jisho_lens.core.ocr.base import OcrLine, OcrResult

VARIANTS: dict[str, dict] = {
    "rapid-v6": {},
    "rapid-v5-server": {
        "Det.ocr_version": "PP-OCRv5",
        "Det.model_type": "mobile",
        "Det.lang_type": "ch",
        "Rec.ocr_version": "PP-OCRv5",
        "Rec.model_type": "server",
        "Rec.lang_type": "ch",
    },
    "rapid-v4-japan": {
        "Det.ocr_version": "PP-OCRv4",
        "Det.model_type": "mobile",
        "Det.lang_type": "ch",
        "Rec.ocr_version": "PP-OCRv4",
        "Rec.model_type": "mobile",
        "Rec.lang_type": "japan",
    },
}


def _to_enums(params: dict) -> dict:
    from rapidocr.utils.typings import LangDet, LangRec, ModelType, OCRVersion

    out = {"Global.log_level": "error"}
    for key, value in params.items():
        if key.endswith("ocr_version"):
            value = OCRVersion(value)
        elif key.endswith("model_type"):
            value = ModelType(value)
        elif key == "Det.lang_type":
            value = LangDet(value)
        elif key == "Rec.lang_type":
            value = LangRec(value)
        out[key] = value
    return out


class RapidOcrEngine:
    def __init__(self, variant: str = "rapid-v6") -> None:
        from rapidocr import RapidOCR

        if variant not in VARIANTS:
            raise ValueError(f"unknown RapidOCR variant {variant!r}")
        self.name = variant
        self._ocr = RapidOCR(params=_to_enums(VARIANTS[variant]))

    def recognize(self, image: Image.Image) -> OcrResult:
        arr = np.asarray(image.convert("RGB"))[:, :, ::-1]  # RGB -> BGR
        start = time.perf_counter()
        out = self._ocr(arr)
        seconds = time.perf_counter() - start
        lines: list[OcrLine] = []
        if out.txts:
            for text, box, score in zip(out.txts, out.boxes, out.scores, strict=False):
                xs = [p[0] for p in box]
                ys = [p[1] for p in box]
                lines.append(
                    OcrLine(
                        text=text,
                        box=(int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
                        score=float(score),
                    )
                )
        lines.sort(key=lambda ln: (ln.box[1], ln.box[0]) if ln.box else (0, 0))
        return OcrResult(lines=lines, seconds=seconds)
