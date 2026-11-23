"""OCR integration (FR-032, FR-060, FR-066, NFR-101).

Uses Tesseract via pytesseract with light pre-processing (grayscale,
auto-contrast, orientation via OSD when available).  Returns the recognised
text and the mean word confidence (0-100) so low-confidence pages can be
flagged and excluded from answer context by policy.
"""
from __future__ import annotations

import io
import logging
import shutil
from dataclasses import dataclass

from app.core.config import get_settings

log = logging.getLogger("app.ocr")


@dataclass
class OcrResult:
    text: str
    confidence: float
    engine: str = "tesseract"
    language: str = "eng"


def ocr_available() -> bool:
    s = get_settings()
    return bool(s.tesseract_cmd or shutil.which("tesseract"))


def ocr_image(image) -> OcrResult:  # PIL.Image.Image
    import pytesseract
    from PIL import ImageOps

    s = get_settings()
    if s.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = s.tesseract_cmd
    img = ImageOps.autocontrast(ImageOps.grayscale(image))
    try:  # orientation detection (deskew of 90/180/270 rotations)
        osd = pytesseract.image_to_osd(img, output_type=pytesseract.Output.DICT)
        if osd.get("rotate"):
            img = img.rotate(-int(osd["rotate"]), expand=True)
    except Exception as exc:  # OSD needs enough text; failure is not an error
        log.debug("orientation detection skipped: %s", type(exc).__name__)
    data = pytesseract.image_to_data(img, lang=s.ocr_languages, output_type=pytesseract.Output.DICT)
    words, confs, lines, current, last_key = [], [], [], [], None
    for i, word in enumerate(data["text"]):
        conf = float(data["conf"][i]) if str(data["conf"][i]) not in ("-1", "") else -1
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != last_key and current:
            lines.append(" ".join(current))
            current = []
        last_key = key
        if word and word.strip() and conf >= 0:
            current.append(word.strip())
            words.append(word)
            confs.append(conf)
    if current:
        lines.append(" ".join(current))
    confidence = sum(confs) / len(confs) if confs else 0.0
    return OcrResult(text="\n".join(lines), confidence=round(confidence, 1), language=s.ocr_languages)


def ocr_bytes(data: bytes) -> OcrResult:
    from PIL import Image

    with Image.open(io.BytesIO(data)) as img:
        img.load()
        return ocr_image(img.convert("RGB"))
