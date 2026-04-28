"""Quick debug: show parsed rows after normalization"""
from pathlib import Path
import re
from pdf_reader import PdfReader
from parser_type_b import TypeBParser, _normalize_ocr_row

p = Path("samples/n_r_10_n.pdf")

r = PdfReader()
text = r.read_text(p)

print("=== normalized OCR lines (data rows only) ===")
from parser_type_b import TypeBParser
parser = TypeBParser()

_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

for line in text.splitlines():
    s = _normalize_ocr_row(line.strip())
    if s and parser._looks_like_data_row(s):
        times = _TIME_RE.findall(s)
        print(f"  times={len(times)}  {repr(s)}")
