from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from models import AttendanceReport, ReportSummary, ReportType, WorkDay

if TYPE_CHECKING:
    pass


class IPdfReader(ABC):
    """Reads a PDF file and returns either raw text or page images."""

    @abstractmethod
    def read_text(self, pdf_path: Path) -> str:
        """Return full extracted text from all pages of the PDF."""

    @abstractmethod
    def read_pages(self, pdf_path: Path) -> list[Image.Image]:
        """Return each PDF page as a PIL Image (for OCR fallback)."""


class IDetector(ABC):
    """Identifies which report type a PDF belongs to."""

    @abstractmethod
    def detect(self, text: str) -> ReportType:
        """Detect ReportType from extracted text. Raises ValueError if unknown."""


class IParser(ABC):
    """Parses raw extracted text into a structured AttendanceReport."""

    @abstractmethod
    def can_parse(self, report_type: ReportType) -> bool:
        """Return True if this parser handles the given ReportType."""

    @abstractmethod
    def parse(self, text: str, pdf_path: Path) -> AttendanceReport:
        """Parse extracted text into a structured AttendanceReport."""


class BaseParser(IParser):
    """
    Template Method base for all parsers.

    ``parse()`` defines the fixed algorithm skeleton:
      1. _extract_rows   — unified row extraction (pdfplumber + fallback)
      2. _is_header_line — filter non-data rows (default: pass all through)
      3. _parse_row      — per-row WorkDay construction
      4. _post_process   — optional post-processing (gap-fill, dedup, etc.)
      5. _parse_summary  — monthly totals / rate summary
      6. _assemble_report — final AttendanceReport construction

    Subclasses override only the steps that differ per report type.
    """

    def parse(self, text: str, pdf_path: Path) -> AttendanceReport:
        rows = self._extract_rows(text, pdf_path)
        raw_pairs: list[tuple[WorkDay | None, list[str]]] = [
            (self._parse_row(row), row)
            for row in rows
            if not self._is_header_line(row)
        ]
        days = self._post_process(raw_pairs, text, pdf_path)
        summary = self._parse_summary(days, text)
        return self._assemble_report(days, summary, text)

    # ── abstract hooks ─────────────────────────────────────────────────────────

    @abstractmethod
    def _extract_rows(self, text: str, pdf_path: Path) -> list[list[str]]:
        """Return all candidate rows (as cell lists) for this report type."""

    @abstractmethod
    def _parse_row(self, row: list[str]) -> WorkDay | None:
        """Parse one cell-list into a WorkDay, or None if not a valid data row."""

    @abstractmethod
    def _parse_summary(
        self, days: list[WorkDay], text: str
    ) -> ReportSummary | None:
        """Build a ReportSummary from the parsed days and raw text."""

    @abstractmethod
    def _assemble_report(
        self,
        days: list[WorkDay],
        summary: ReportSummary | None,
        text: str,
    ) -> AttendanceReport:
        """Create the final AttendanceReport from assembled data."""

    # ── hooks with default implementations ────────────────────────────────────

    def _is_header_line(self, row: list[str]) -> bool:
        """Return True to skip this row. Default: no skipping (extraction already filters)."""
        return False

    def _post_process(
        self,
        raw_pairs: list[tuple[WorkDay | None, list[str]]],
        text: str,
        pdf_path: Path,
    ) -> list[WorkDay]:
        """Optional post-processing. Default: filter out None WorkDays."""
        return [wd for wd, _ in raw_pairs if wd is not None]


class IVariationEngine(ABC):
    """Applies deterministic variation rules to an AttendanceReport."""

    @abstractmethod
    def can_handle(self, report_type: ReportType) -> bool:
        """Return True if this engine handles the given ReportType."""

    @abstractmethod
    def apply(self, report: AttendanceReport) -> AttendanceReport:
        """
        Apply variation rules and return a NEW report.
        Rules must be deterministic — same input always gives same output.
        The original report is never mutated.
        """


class IGenerator(ABC):
    """Generates a PDF from an AttendanceReport, matching the original format."""

    @abstractmethod
    def can_generate(self, report_type: ReportType) -> bool:
        """Return True if this generator handles the given ReportType."""

    @abstractmethod
    def generate(self, report: AttendanceReport, output_path: Path) -> None:
        """Write a PDF to output_path that visually matches the original format."""


class BaseTransformationStrategy(ABC):
    """
    Strategy interface for per-row attendance transformations.

    Each concrete strategy (TypeATransformationStrategy, TypeBTransformationStrategy)
    encapsulates the variation logic for one report type without any if/else
    branching on the type token.

    ValidatingStrategyDecorator wraps any BaseTransformationStrategy and adds
    post-transform validation without modifying the inner strategy.

    TransformationService selects the right strategy from a registry keyed by
    ``ReportType.name`` ("TYPE_A" / "TYPE_B") and calls these methods — it
    cannot distinguish a raw strategy from a decorated one.
    """

    @abstractmethod
    def transform_row(self, day: WorkDay) -> WorkDay:
        """
        Apply deterministic variation rules to a single WorkDay.
        Must return a NEW WorkDay — never mutate the input.
        """

    @abstractmethod
    def rebuild_summary(
        self,
        days: list[WorkDay],
        original: ReportSummary | None,
    ) -> ReportSummary | None:
        """Re-compute the monthly summary from all (possibly varied) rows."""
