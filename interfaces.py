from __future__ import annotations
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from models import AttendanceReport, ReportType

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
