from __future__ import annotations
import re
from datetime import date, time
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from interfaces import IParser
from models import (
    AttendanceReport, DayType, ReportSummary,
    ReportType, ShiftTime, WorkDay,
)

_DATE_RE = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})")
_TIME_RE = re.compile(r"\b(\d{1,2}):(\d{2})\b")

_HOLIDAY_LABELS: set[str] = {
    "שבת", "ראש השנה", "ערב ראש השנה", "יום כיפור",
    "סוכות", "פסח", "שבועות", "חנוכה", "פורים",
}


def _parse_dec(s: str) -> Decimal:
    try:
        return Decimal(re.sub(r"[^\d.]", "", s))
    except InvalidOperation:
        return Decimal("0")


class TypeBParser(IParser):
    """
    Parses Type B reports (כרטיס עובד).

    Column order (RTL physical):
      תאריך | יום בשבוע | שעת כניסה | שעת יציאה | סה"כ שעות | הערות

    Summary box (top of page):
      סה"כ ימי עבודה | סה"כ שעות חודשיות | מחיר לשעה | סה"כ לתשלום

    Shabbat / holiday rows have no shift times — only a label in הערות.
    """

    def can_parse(self, report_type: ReportType) -> bool:
        return report_type == ReportType.TYPE_B

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
        month, year = self._month_year(days, text)

        return AttendanceReport(
            report_type=ReportType.TYPE_B,
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
                            row_str = " ".join(cells)
                            has_date    = bool(_DATE_RE.search(row_str))
                            has_holiday = any(lbl in row_str for lbl in _HOLIDAY_LABELS)
                            if has_date or has_holiday:
                                rows.append(cells)
        except Exception:
            pass
        return rows

    def _text_to_rows(self, text: str) -> list[list[str]]:
        rows = []
        for line in text.splitlines():
            has_date    = bool(_DATE_RE.search(line))
            has_holiday = any(lbl in line for lbl in _HOLIDAY_LABELS)
            if has_date or has_holiday:
                rows.append(line.split())
        return rows

    # ── row parsing ────────────────────────────────────────────────────────────

    def _parse_row(self, cells: list[str]) -> WorkDay | None:
        row_str = " ".join(str(c) for c in cells)

        # Holiday / Shabbat rows: label present, no date
        if not _DATE_RE.search(row_str):
            for label in _HOLIDAY_LABELS:
                if label in row_str:
                    day_type = DayType.SHABBAT if label == "שבת" else DayType.HOLIDAY
                    return WorkDay(
                        date=date(1900, 1, 1),  # sentinel — no date on these rows
                        day_type=day_type,
                        notes=label,
                    )
            return None

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

        times = _TIME_RE.findall(row_str)
        shift: ShiftTime | None = None
        if len(times) >= 2:
            entry = time(int(times[0][0]), int(times[0][1]))
            exit_ = time(int(times[1][0]), int(times[1][1]))
            shift = ShiftTime(entry=entry, exit=exit_, break_minutes=0)

        notes = ""
        for label in _HOLIDAY_LABELS:
            if label in row_str:
                notes = label
                break

        return WorkDay(
            date=work_date,
            day_type=DayType.REGULAR,
            shift=shift,
            notes=notes,
        )

    # ── summary ────────────────────────────────────────────────────────────────

    def _build_summary(self, days: list[WorkDay], text: str) -> ReportSummary:
        work_days   = [d for d in days if d.shift is not None]
        total_hours = sum(d.shift.total_hours() for d in work_days if d.shift)

        hourly_rate   = self._extract_rate(text)
        total_payment = (
            (total_hours * hourly_rate).quantize(Decimal("0.01"))
            if hourly_rate else None
        )

        return ReportSummary(
            total_days=len(work_days),
            total_hours=total_hours,
            hourly_rate=hourly_rate,
            total_payment=total_payment,
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_rate(text: str) -> Decimal | None:
        m = re.search(r"מחיר לשעה[\s:₪]*([\d,]+\.?\d*)", text)
        return _parse_dec(m.group(1)) if m else None

    @staticmethod
    def _employee_name(text: str) -> str:
        m = re.search(r"שם העובד[:\s]*([\u05d0-\u05ea ]+)", text)
        return m.group(1).strip() if m else "עובד"

    @staticmethod
    def _month_year(days: list[WorkDay], text: str) -> tuple[int, int]:
        real = [d for d in days if d.date.year > 1900]
        if real:
            return real[0].date.month, real[0].date.year
        m = re.search(r"(\d{1,2})[/-](\d{2,4})", text)
        if m:
            month = int(m.group(1))
            year  = int(m.group(2))
            if year < 100:
                year += 2000
            return month, year
        return 1, 2022
