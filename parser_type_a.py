from __future__ import annotations
import re
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from interfaces import IParser
from models import (
    AttendanceReport, DayType, HourBreakdown,
    ReportSummary, ReportType, ShiftTime, WorkDay,
)

_DATE_RE = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

_DAY_NAMES = {"ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"}


def _parse_dec(s: str) -> Decimal:
    try:
        return Decimal(re.sub(r"[^\d.]", "", s))
    except InvalidOperation:
        return Decimal("0")


class TypeAParser(IParser):
    """
    Parses Type A reports (נשר כח אדם).

    Column order (RTL physical, read right-to-left on the page):
      תאריך | יום | מקום עבודה | כניסה | יציאה | הפסקה | סה"כ | 100% | 125% | 150% | שבת

    Strategy:
    1. Try pdfplumber structured table extraction (best for digital PDFs).
    2. Fall back to regex-based line parsing on the raw OCR text.
    """

    def can_parse(self, report_type: ReportType) -> bool:
        return report_type == ReportType.TYPE_A

    def parse(self, text: str, pdf_path: Path) -> AttendanceReport:
        rows = self._extract_table_rows(pdf_path)
        if not rows:
            rows = self._text_to_rows(text)

        days: list[WorkDay] = []
        for row in rows:
            day = self._parse_row(row)
            if day:
                days.append(day)

        summary = self._build_summary(days, text)
        month, year = self._month_year(days)

        return AttendanceReport(
            report_type=ReportType.TYPE_A,
            employee_name=self._employee_name(text),
            month=month,
            year=year,
            days=days,
            summary=summary,
        )

    # ── extraction ─────────────────────────────────────────────────────────────

    def _extract_table_rows(self, pdf_path: Path) -> list[list[str]]:
        rows: list[list[str]] = []
        try:
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    for table in page.extract_tables():
                        for row in table:
                            cells = [c or "" for c in row]
                            if any(_DATE_RE.search(c) for c in cells):
                                rows.append(cells)
        except Exception:
            pass
        return rows

    def _text_to_rows(self, text: str) -> list[list[str]]:
        rows = []
        for line in text.splitlines():
            if _DATE_RE.search(line):
                rows.append(line.split())
        return rows

    # ── row parsing ────────────────────────────────────────────────────────────

    def _parse_row(self, cells: list[str]) -> WorkDay | None:
        row_str = " ".join(str(c) for c in cells)

        m = _DATE_RE.search(row_str)
        if not m:
            return None

        day_n  = int(m.group(1))
        mon_n  = int(m.group(2))
        year_n = int(m.group(3))
        if year_n < 100:
            year_n += 2000

        try:
            work_date = date(year_n, mon_n, day_n)
        except ValueError:
            return None

        day_type = DayType.SHABBAT if "שבת" in row_str else DayType.REGULAR

        # Extract all HH:MM times
        times = _TIME_RE.findall(row_str)
        shift: ShiftTime | None = None
        if len(times) >= 2:
            entry = time(int(times[0][0]), int(times[0][1]))
            exit_ = time(int(times[1][0]), int(times[1][1]))
            break_mins = 30  # default; overwrite if third time found
            if len(times) >= 3:
                bh, bm = int(times[2][0]), int(times[2][1])
                break_mins = bh * 60 + bm
            shift = ShiftTime(entry=entry, exit=exit_, break_minutes=break_mins)

        # Extract decimal numbers (excluding the time-like tokens)
        float_nums: list[Decimal] = []
        for token in row_str.split():
            if ":" in token:
                continue
            try:
                float_nums.append(Decimal(token.replace(",", "")))
            except InvalidOperation:
                pass

        breakdown: HourBreakdown | None = None
        if day_type == DayType.SHABBAT:
            shab = float_nums[0] if float_nums else Decimal("0")
            breakdown = HourBreakdown(hours_shabbat=shab)
        elif len(float_nums) >= 5:
            # Order from the table: total | 100% | 125% | 150% | שבת
            breakdown = HourBreakdown(
                hours_100=float_nums[1],
                hours_125=float_nums[2],
                hours_150=float_nums[3],
                hours_shabbat=float_nums[4] if len(float_nums) > 4 else Decimal("0"),
            )
        elif shift:
            # Derive breakdown from computed total hours
            total = shift.total_hours()
            breakdown = self._classify(total, day_type)

        location = self._location(row_str)

        return WorkDay(
            date=work_date,
            day_type=day_type,
            shift=shift,
            breakdown=breakdown,
            location=location,
        )

    # ── overtime classification ────────────────────────────────────────────────

    @staticmethod
    def _classify(total: Decimal, day_type: DayType) -> HourBreakdown:
        if day_type == DayType.SHABBAT:
            return HourBreakdown(hours_shabbat=total)
        h100 = min(total, Decimal("8"))
        rem  = total - h100
        h125 = min(rem, Decimal("1"))
        h150 = max(rem - Decimal("1"), Decimal("0"))
        return HourBreakdown(hours_100=h100, hours_125=h125, hours_150=h150)

    # ── summary ────────────────────────────────────────────────────────────────

    def _build_summary(self, days: list[WorkDay], text: str) -> ReportSummary:
        work_days  = [d for d in days if d.shift is not None]
        total_100  = sum(d.breakdown.hours_100     for d in days if d.breakdown)
        total_125  = sum(d.breakdown.hours_125     for d in days if d.breakdown)
        total_150  = sum(d.breakdown.hours_150     for d in days if d.breakdown)
        total_shab = sum(d.breakdown.hours_shabbat for d in days if d.breakdown)
        total_h    = total_100 + total_125 + total_150 + total_shab

        bonus  = self._labelled_decimal(text, "בונוס")
        travel = self._labelled_decimal(text, "נסיעות")

        return ReportSummary(
            total_days=len(work_days),
            total_hours=total_h,
            breakdown=HourBreakdown(total_100, total_125, total_150, total_shab),
            bonus=bonus,
            travel=travel,
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _labelled_decimal(text: str, label: str) -> Decimal:
        m = re.search(rf"{label}[\s:]+(\d+\.?\d*)", text)
        return _parse_dec(m.group(1)) if m else Decimal("0")

    @staticmethod
    def _location(row_str: str) -> str:
        words = re.findall(r"[\u05d0-\u05ea]{2,}", row_str)
        for w in reversed(words):
            if w not in _DAY_NAMES:
                return w
        return ""

    @staticmethod
    def _employee_name(text: str) -> str:
        m = re.search(r'הנשר כח אדם בע["\u05f4]?מ', text)
        return 'הנשר כח אדם בע"מ' if m else ""

    @staticmethod
    def _month_year(days: list[WorkDay]) -> tuple[int, int]:
        if days:
            return days[0].date.month, days[0].date.year
        return 1, 2022
