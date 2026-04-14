# Attendance Report Variation Generator

Reads a Hebrew attendance PDF report, applies **deterministic** variation rules, and outputs a new PDF with identical structure but different (realistic) data.

Supports two report types:
- **Type A** — נשר כח אדם (overtime columns: 100% / 125% / 150% / שבת)
- **Type B** — כרטיס עובד (flat hourly rate, variable daily hours)

---

## Prerequisites

### 1 — Tesseract OCR (with Hebrew)
Download from: https://github.com/UB-Mannheim/tesseract/wiki  
During installation check **Hebrew** under *Additional language data*.

Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`

### 2 — Poppler for Windows
Download from: https://github.com/oschwartz10612/poppler-windows/releases  
Extract so the bin folder is at: `C:\poppler\Library\bin`

### 3 — Hebrew font
Download **Noto Sans Hebrew** from https://fonts.google.com/noto/specimen/Noto+Sans+Hebrew  
Place `NotoSansHebrew-Regular.ttf` in the `fonts/` folder.

### 4 — Adjust paths (if needed)
Open `pdf_reader.py` and update:
```python
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH  = r"C:\poppler\Library\bin"
```

---

## Installation

```bash
cd attendance_generator
pip install -r requirements.txt
```

---

## Usage

```bash
# Output saved next to input as <name>_variation.pdf
python main.py --input "C:\reports\october_2022.pdf"

# Specify output path explicitly
python main.py --input "C:\reports\report.pdf" --output "C:\output\varied.pdf"
```

---

## Run Tests

```bash
pytest tests/ -v
```

---

## Project Structure

| File | Responsibility |
|---|---|
| `models.py` | Domain entities: `WorkDay`, `ShiftTime`, `AttendanceReport`, enums |
| `interfaces.py` | ABCs: `IPdfReader`, `IDetector`, `IParser`, `IVariationEngine`, `IGenerator` |
| `pdf_reader.py` | PDF → text via pdfplumber; OCR fallback via pdf2image + pytesseract |
| `detector.py` | Identify Type A vs Type B by Hebrew keyword scoring |
| `parser_type_a.py` | Parse Type A report rows into structured data |
| `parser_type_b.py` | Parse Type B report rows into structured data |
| `variation_type_a.py` | Deterministic variation rules for Type A |
| `variation_type_b.py` | Deterministic variation rules for Type B |
| `generator_type_a.py` | Generate Type A PDF (ReportLab + Hebrew BiDi) |
| `generator_type_b.py` | Generate Type B PDF (ReportLab + Hebrew BiDi) |
| `container.py` | Dependency injection wiring (dependency-injector) |
| `main.py` | CLI entry point (Click) |

---

## Variation Rules Summary

### Type A
| Property | Rule |
|---|---|
| Entry time | ± (day % 3) × 5 min — derived from date, deterministic |
| Total hours | Preserved exactly |
| Exit time | Recalculated from new entry + total |
| Overtime | Re-classified: ≤8h→100%, 8–9h→125%, >9h→150% |
| Shabbat rows | Entry ± (day % 2) × 15 min, total preserved |
| Monthly totals | Re-summed from rows |

### Type B
| Property | Rule |
|---|---|
| Entry time | (day % 5) − 2 minutes |
| Total hours | ± 0.05 × (day % 3), clamped 0.5–12h |
| Exit time | Recalculated from new entry + new total |
| Shabbat / holiday rows | Completely unchanged |
| Monthly total | Re-summed from rows |
| סה"כ לתשלום | new_hours × original_rate |
