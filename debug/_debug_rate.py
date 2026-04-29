from pathlib import Path
import pdfplumber
from parsers.parser_type_b import _normalize_ocr_row
import re

print("=== n_r_5_n pdfplumber tables ===")
with pdfplumber.open(Path("samples/n_r_5_n.pdf")) as pdf:
    for pg_i, page in enumerate(pdf.pages):
        for tbl_i, table in enumerate(page.extract_tables()):
            print(f"Page {pg_i} Table {tbl_i}:")
            for row in table:
                print("  ", row)

print()
print("=== n_r_10_n rate search in raw text ===")
from infrastructure.pdf_reader import PdfReader
reader = PdfReader()
text10 = reader.read_text(Path("samples/n_r_10_n.pdf"))
text5 = reader.read_text(Path("samples/n_r_5_n.pdf"))
print("n_r_10_n full text:")
print(repr(text10))
print()
print("n_r_5_n full text:")
print(repr(text5))
