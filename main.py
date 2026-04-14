"""
main.py — CLI entry point for the attendance report variation generator.

Usage:
    python main.py --input "C:\\path\\to\\report.pdf"
    python main.py --input "C:\\path\\to\\report.pdf" --output "C:\\out\\varied.pdf"
"""
from __future__ import annotations
import sys
from pathlib import Path

import click

from container import Container


def run_pipeline(input_path: Path, output_path: Path) -> None:
    """
    Full pipeline:
      PDF file
        → [PdfReader]         extract text  (pdfplumber / OCR)
        → [KeywordDetector]   identify type (A or B)
        → [TypeA/BParser]     parse into AttendanceReport
        → [TypeA/BVariation]  apply deterministic variation rules
        → [TypeA/BGenerator]  write output PDF

    Every component is resolved from the DI container — nothing here
    instantiates concrete classes directly.
    """
    container = Container()

    reader     = container.pdf_reader()
    detector   = container.detector()
    parsers    = container.parsers()
    variations = container.variations()
    generators = container.generators()

    # Step 1 — Read
    click.echo(f"[1/4] Reading  →  {input_path.name}")
    text = reader.read_text(input_path)
    if not text.strip():
        click.echo("      Warning: no text extracted — PDF may be image-only.", err=True)

    # Step 2 — Detect type
    click.echo("[2/4] Detecting report type …")
    report_type = detector.detect(text)
    click.echo(f"      Detected: {report_type.value}")

    # Step 3 — Parse
    click.echo("[3/4] Parsing report …")
    parser = next((p for p in parsers if p.can_parse(report_type)), None)
    if parser is None:
        raise RuntimeError(f"No parser registered for {report_type}")
    report = parser.parse(text, input_path)
    click.echo(f"      {len(report.days)} day-rows parsed  |  "
               f"{report.summary.total_days if report.summary else '?'} work days")

    # Step 4 — Vary + generate
    click.echo("[4/4] Applying variation rules and generating PDF …")
    engine = next((e for e in variations if e.can_handle(report_type)), None)
    if engine is None:
        raise RuntimeError(f"No variation engine for {report_type}")
    varied = engine.apply(report)

    generator = next((g for g in generators if g.can_generate(report_type)), None)
    if generator is None:
        raise RuntimeError(f"No generator registered for {report_type}")
    generator.generate(varied, output_path)

    click.echo(f"\n✓  Saved to: {output_path}")


BASE_DIR    = Path(__file__).parent
SAMPLES_DIR = BASE_DIR / "samples"
OUTPUT_DIR  = BASE_DIR / "output"


@click.command()
@click.option(
    "--input", "-i", "input_path",
    required=True,
    type=click.Path(path_type=Path),
    help="Filename or full path of the input PDF. "
         "If only a filename is given it is resolved from the samples/ folder.",
)
@click.option(
    "--output", "-o", "output_path",
    default=None,
    type=click.Path(path_type=Path),
    help="Destination path for the generated PDF.  "
         "Defaults to output/<input_stem>_variation.pdf.",
)
def cli(input_path: Path, output_path: Path | None) -> None:
    """Generate a realistic variation of a Hebrew attendance report PDF."""
    # Resolve input: bare filename → samples/<filename>
    if not input_path.is_absolute() and not input_path.parent.name:
        input_path = SAMPLES_DIR / input_path
    if not input_path.exists():
        click.echo(f"Error: input file not found: {input_path}", err=True)
        sys.exit(1)

    # Resolve output: default to output/<stem>_variation.pdf
    if output_path is None:
        OUTPUT_DIR.mkdir(exist_ok=True)
        output_path = OUTPUT_DIR / f"{input_path.stem}_variation.pdf"

    try:
        run_pipeline(input_path, output_path)
    except ValueError as exc:
        click.echo(f"\nDetection error: {exc}", err=True)
        sys.exit(1)
    except Exception as exc:
        click.echo(f"\nError: {exc}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
