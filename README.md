# 📄 Attendance Report Variation Generator

> Reads a **Hebrew attendance PDF**, applies **deterministic variation rules**, and outputs a brand-new PDF with the same structure but realistically altered data — indistinguishable from a genuine report.

---

## 🧠 What Does This Project Do?

This tool takes Israeli payroll/attendance PDF reports as input, automatically understands their type, extracts all the structured data from them, **tweaks the values** according to deterministic rules (same input → same output, always), and produces a clean output PDF.

It is purpose-built for two real-world Hebrew report formats:

| Report Type | Hebrew Name | Description |
|---|---|---|
| **Type A** | נשר כח אדם | Overtime-column report (100% / 125% / 150% / שבת) |
| **Type B** | כרטיס עובד | Flat hourly-rate report with variable daily hours |

---

## 🔄 Processing Pipeline

Every PDF goes through a 4-step pipeline, fully orchestrated by the DI container:

```
📂 PDF File
    │
    ▼
📖 [1] PdfReader          — extract text (pdfplumber + Tesseract OCR fallback)
    │
    ▼
🔍 [2] KeywordDetector    — detect Type A or Type B via Hebrew keyword scoring
    │
    ▼
🧩 [3] Parser (A or B)    — parse rows into structured AttendanceReport objects
    │
    ▼
⚙️  [4] TransformationService → Strategy → Decorator → apply variation rules
    │
    ▼
🖨️ [5] Generator (A or B) — write the output PDF (ReportLab + Hebrew BiDi)
    │
    ▼
✅  output/<name>_variation.pdf
```

---

## 🏗️ Architecture & Design Patterns

This project is a deliberate showcase of **clean OOP architecture**. Every major component follows a named design pattern.

### 1. 🎯 Strategy Pattern
**Where:** `transformation/strategies.py`

Each report type has its **own transformation strategy** class:
- `TypeATransformationStrategy` — variation logic for Type A
- `TypeBTransformationStrategy` — variation logic for Type B

The `TransformationService` selects the right strategy from a **registry** (see below) without any `if/else` on report type. Adding a new report type = one new class + one registry entry.

---

### 2. 🎀 Decorator Pattern
**Where:** `transformation/strategies.py` → `ValidatingStrategyDecorator`

Every strategy is **wrapped** in a `ValidatingStrategyDecorator` before being registered. The decorator:
1. Calls the inner strategy's `transform_row()`
2. Validates the result against business constraints (e.g., minimum hourly rate)
3. Raises `TransformationError` if the output is invalid

The `TransformationService` cannot tell whether it holds a raw strategy or a decorated one — both look identical through the `BaseTransformationStrategy` interface.

---

### 3. 📋 Template Method Pattern
**Where:** `core/interfaces.py` → `BaseParser`

The `parse()` method defines a **fixed algorithm skeleton**:

```
parse()
  ├── _extract_rows()    ← abstract: how to get rows from text
  ├── _is_header_line()  ← hook: filter non-data rows
  ├── _parse_row()       ← abstract: row → WorkDay
  ├── _post_process()    ← hook: gap-fill, dedup, etc.
  ├── _parse_summary()   ← hook: monthly totals
  └── _assemble_report() ← hook: build final AttendanceReport
```

`TypeAParser` and `TypeBParser` only override the steps that differ. The common flow is inherited and never duplicated.

---

### 4. 📦 Registry Pattern
**Where:** `transformation/service.py` + `container.py`

A `strategy_registry` dictionary maps `ReportType.name → strategy`:

```python
strategy_registry = {
    "TYPE_A": ValidatingStrategyDecorator(TypeATransformationStrategy()),
    "TYPE_B": ValidatingStrategyDecorator(TypeBTransformationStrategy()),
}
```

`TransformationService` looks up by key — zero branching, fully open for extension.

---

### 5. 💉 Dependency Injection Pattern
**Where:** `container.py`

Every component is registered as a **Singleton provider** in a `dependency-injector` `DeclarativeContainer`. `main.py` never calls a constructor directly — it asks the container for ready-made objects.

This makes every component **trivially swappable** for a test fake:
```python
container.pdf_reader.override(FakePdfReader())
```

---

### 6. 🔌 Interface Segregation (ABCs)
**Where:** `core/interfaces.py`

All cross-layer contracts are defined as Python Abstract Base Classes:

| Interface | Responsibility |
|---|---|
| `IPdfReader` | `read_text()` / `read_pages()` |
| `IDetector` | `detect(text) → ReportType` |
| `IParser` | `can_parse()` / `parse()` |
| `BaseTransformationStrategy` | `transform_row()` / `rebuild_summary()` |
| `IGenerator` | `can_generate()` / `generate()` |

Concrete classes depend only on these interfaces — never on each other.

---

## 📁 Project Structure

```
📦 pdfFiles/
├── 🚀 main.py                          CLI entry point (Click)
├── 💉 container.py                     DI container — all wiring lives here
├── 📐 pyproject.toml
├── 📋 requirements.txt
│
├── 🧠 core/
│   ├── interfaces.py                   ABCs for every layer + BaseParser Template Method
│   └── exceptions.py                   TransformationError and friends
│
├── 📊 models/
│   ├── base_models.py                  WorkDay, ShiftTime, HourBreakdown, AttendanceReport
│   └── attendance_row.py               Row-level data classes
│
├── 🏗️ infrastructure/
│   ├── pdf_reader.py                   pdfplumber + Tesseract OCR fallback
│   └── detector.py                     Hebrew keyword scorer → ReportType
│
├── 🧩 parsers/
│   ├── parser_type_a.py                Template Method impl for Type A
│   └── parser_type_b.py                Template Method impl for Type B
│
├── ⚙️ transformation/
│   ├── strategies.py                   Strategy + Decorator implementations
│   └── service.py                      Registry-based TransformationService
│
├── 🖨️ generators/
│   ├── generator_type_a.py             ReportLab PDF writer for Type A
│   └── generator_type_b.py             ReportLab PDF writer for Type B
│
├── 🧪 tests/
│   ├── conftest.py
│   ├── test_decorator.py               ValidatingStrategyDecorator tests
│   ├── test_detector.py                KeywordDetector tests
│   ├── test_models.py                  Domain model tests
│   └── test_transformation_strategies.py
│
├── 🔤 fonts/                           NotoSansHebrew-Regular.ttf goes here
├── 📂 samples/                         Place input PDFs here
└── 📤 output/                          Generated PDFs land here
```

---

## ⚙️ Variation Rules

### Type A — נשר כח אדם

| Field | Rule |
|---|---|
| ⏰ Entry time | ± `(day % 3) × 5` min — deterministic from date |
| ⏱️ Total hours | Preserved exactly from source |
| 🚪 Exit time | Recalculated: `new_entry + total + break` |
| 📊 Overtime split | Re-classified: ≤8h → 100%, 8–9h → 125%, >9h → 150% |
| 🕍 Shabbat rows | Entry ± `(day % 2) × 15` min, total preserved |
| 📅 Monthly totals | Re-summed from all rows |

### Type B — כרטיס עובד

| Field | Rule |
|---|---|
| ⏰ Entry time | `(day % 5) − 2` minutes shift |
| ⏱️ Total hours | ± `0.05 × (day % 3)`, clamped to 0.5–12h |
| 🚪 Exit time | Recalculated from new entry + new total |
| 🕍 Shabbat / holiday rows | Completely unchanged |
| 📅 Monthly total | Re-summed from rows |
| 💰 סה"כ לתשלום | `new_hours × original_rate` |

> 🔁 All rules are **deterministic**: the same input PDF always produces the same output — no randomness involved.

---

## 🛠️ Prerequisites

### 1️⃣ Tesseract OCR (with Hebrew)
Download from: https://github.com/UB-Mannheim/tesseract/wiki  
During installation check **Hebrew** under *Additional language data*.

Default install path: `C:\Program Files\Tesseract-OCR\tesseract.exe`

### 2️⃣ Poppler for Windows
Download from: https://github.com/oschwartz10612/poppler-windows/releases  
Extract so the bin folder is at: `C:\poppler\Library\bin`

### 3️⃣ Hebrew Font
Download **Noto Sans Hebrew** from https://fonts.google.com/noto/specimen/Noto+Sans+Hebrew  
Place `NotoSansHebrew-Regular.ttf` in the `fonts/` folder.

### 4️⃣ Adjust paths (if needed)
Open `infrastructure/pdf_reader.py` and update:
```python
TESSERACT_CMD = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
POPPLER_PATH  = r"C:\poppler\Library\bin"
```

---

## 📦 Installation

```bash
pip install -r requirements.txt
```

---

## 🚀 Usage

```bash
# Output saved automatically as output/<name>_variation.pdf
python main.py --input "C:\reports\october_2022.pdf"

# Specify an explicit output path
python main.py --input "C:\reports\report.pdf" --output "C:\output\varied.pdf"
```

---

## 🧪 Run Tests

```bash
pytest tests/ -v
```

---

## 🔑 Key Design Decisions

| Decision | Why |
|---|---|
| 🚫 **No `if report_type == ...` anywhere** | Strategy + Registry pattern — open/closed principle |
| 🔁 **Deterministic variation** | Same input → same output; reproducible and testable |
| 🖼️ **OCR fallback** | Works on scanned image-PDFs, not just text-layer PDFs |
| 💉 **DI container** | Every dependency is swappable; zero global state |
| 🧊 **Frozen dataclasses** | `WorkDay`, `ShiftTime` etc. are immutable — transformation always returns new objects |
| 🎀 **Decorator for validation** | Validation is transparently added without touching strategy logic |
