from __future__ import annotations
import sys
from pathlib import Path

import pdfplumber
import pytesseract
from PIL import Image, ImageFilter, ImageEnhance

from interfaces import IPdfReader

# ── Windows install paths ──────────────────────────────────────────────────────
# Poppler ships inside the project folder (poppler/Library/bin).
# Tesseract ships inside the project folder (tess_env/Library/bin).
_HERE         = Path(__file__).parent
TESSERACT_CMD = str(_HERE / "tess_env" / "Library" / "bin" / "tesseract.exe")
TESSDATA_DIR  = str(_HERE / "tess_env" / "share" / "tessdata")
POPPLER_PATH  = str(_HERE / "poppler" / "Library" / "bin")

import os as _os
_os.environ["TESSDATA_PREFIX"] = TESSDATA_DIR

if sys.platform == "win32":
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_CMD


class PdfReader(IPdfReader):
    """
    Implements IPdfReader with a two-strategy approach:

    1. pdfplumber  — fast, accurate for digital (text-based) PDFs.
    2. pdf2image + pytesseract — OCR fallback for scanned / image-based PDFs.

    Strategy selection is automatic: if pdfplumber returns non-empty text,
    it is used.  Otherwise the OCR pipeline is activated.
    """

    def __init__(self, dpi: int = 300) -> None:
        self._dpi = dpi

    # ── IPdfReader ─────────────────────────────────────────────────────────────

    def read_text(self, pdf_path: Path) -> str:
        text = self._read_with_pdfplumber(pdf_path)
        if text.strip():
            return text
        # Fallback: convert pages to images and OCR them
        pages = self.read_pages(pdf_path)
        return self._ocr_pages(pages)

    def read_pages(self, pdf_path: Path) -> list[Image.Image]:
        from pdf2image import convert_from_path
        kwargs: dict = {"dpi": self._dpi}
        if sys.platform == "win32":
            kwargs["poppler_path"] = POPPLER_PATH
        return convert_from_path(str(pdf_path), **kwargs)

    # ── private helpers ────────────────────────────────────────────────────────

    def _read_with_pdfplumber(self, pdf_path: Path) -> str:
        lines: list[str] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    tables = page.extract_tables()
                    if tables:
                        for table in tables:
                            for row in table:
                                lines.append("\t".join(cell or "" for cell in row))
                    else:
                        raw = page.extract_text(x_tolerance=3, y_tolerance=3)
                        if raw:
                            lines.append(raw)
        except Exception:
            pass
        return "\n".join(lines)

    def _ocr_pages(self, pages: list[Image.Image]) -> str:
        results: list[str] = []
        for img in pages:
            img = img.convert("L")                          # greyscale
            img = ImageEnhance.Contrast(img).enhance(1.5)  # boost contrast
            img = img.filter(ImageFilter.SHARPEN)           # sharpen edges
            text = pytesseract.image_to_string(
                img,
                lang="heb+eng",
                config="--psm 6 --oem 3",
            )
            results.append(text)
        return "\n".join(results)
