from __future__ import annotations
import re
from calendar import monthrange
from datetime import date, time, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pdfplumber

from interfaces import IParser
from models import (
    AttendanceReport, DayType, ReportSummary,
    ReportType, ShiftTime, WorkDay,
)

_DATE_RE         = re.compile(r"(\d{1,2})[/.](\d{1,2})[/.](\d{2,4})")
_DATE_PARTIAL_RE = re.compile(r"\b(\d{1,2})[/.](\d{2,4})\b")   # DD/YY – missing month
_TIME_RE         = re.compile(r"\b(\d{1,2}):(\d{2})\b")

# Minimum hourly rate enforced by business rule (ILS)
_MIN_HOURLY_RATE = Decimal("33")

# Hebrew day name → Python weekday (Mon=0 … Sun=6)
_HEB_WEEKDAY: dict[str, int] = {
    "ראשון": 6, "שני": 0, "שלישי": 1, "רביעי": 2,
    "חמישי": 3, "שישי": 4, "שבת": 5,
}

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

        # ── Pass 1: infer ref month / year from first unambiguous full date ────
        ref_month, ref_year = self._detect_period(rows, text)

        # ── Pass 2: parse every row (strict + partial-date + weekday hints) ───
        # Result: ordered list of (WorkDay | None, row_str)
        parsed: list[tuple[WorkDay | None, str]] = []
        for row in rows:
            row_str = " ".join(str(c) for c in row)
            wd = self._parse_row(row, ref_month=ref_month, ref_year=ref_year)
            parsed.append((wd, row_str))

        # ── Pass 3: identify "anchor" dates and check consistency ─────────────
        # An anchor is a WorkDay whose date came from a full D/M/Y token AND the
        # weekday name (when present) matches.  Provisional dates from partial tokens
        # are validated against their surrounding anchors; if they jump outside the
        # expected range they are cleared so Pass 4 can reassign them sequentially.
        parsed = self._validate_against_anchors(parsed, ref_month, ref_year)

        # ── Pass 4: weekday-based + sequential gap-filling ─────────────────────
        parsed = self._fill_gaps(parsed, ref_month, ref_year)

        # ── Collect & deduplicate (prefer row with shift) ──────────────────────
        date_map: dict[date, WorkDay] = {}
        for wd, _ in parsed:
            if wd is None:
                continue
            existing = date_map.get(wd.date)
            if existing is None or (wd.shift is not None and existing.shift is None):
                date_map[wd.date] = wd
        days = sorted(date_map.values(), key=lambda d: d.date)

        # ── Fill any remaining days of the month (e.g. Shabbat / missing rows) ─
        if ref_month and ref_year:
            days_in_month = monthrange(ref_year, ref_month)[1]
            existing = {d.date for d in days}
            for day_num in range(1, days_in_month + 1):
                d = date(ref_year, ref_month, day_num)
                if d not in existing:
                    # Determine day type by weekday: Saturday → Shabbat
                    if d.weekday() == 5:
                        day_type = DayType.SHABBAT
                    else:
                        day_type = DayType.REGULAR
                    days.append(WorkDay(date=d, day_type=day_type, shift=None))
            days.sort(key=lambda d: d.date)

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
                            if self._looks_like_data_row(row_str):
                                rows.append(cells)
        except Exception:
            pass
        return rows

    def _text_to_rows(self, text: str) -> list[list[str]]:
        rows = []
        for line in text.splitlines():
            s = line.strip()
            if s and self._looks_like_data_row(s):
                rows.append(s.split())
        return rows

    @staticmethod
    def _looks_like_data_row(s: str) -> bool:
        """Return True when s looks like an attendance table row."""
        if _DATE_RE.search(s) or _DATE_PARTIAL_RE.search(s):
            return True
        if any(lbl in s for lbl in _HOLIDAY_LABELS):
            return True
        # Hebrew day name present
        if any(name in s for name in _HEB_WEEKDAY):
            return True
        # Prefix-match for garbled day names (e.g. "שיש" prefix of "שישי")
        for name in _HEB_WEEKDAY:
            if len(name) >= 3 and name[:3] in s:
                return True
        # Pipe-structured line with at least 2 numeric tokens (looks like table row)
        if s.count("|") >= 2 and len(re.findall(r"\d+", s)) >= 2:
            return True
        return False

    # ── period detection ───────────────────────────────────────────────────────

    @staticmethod
    def _detect_period(
        rows: list[list[str]], text: str
    ) -> tuple[int | None, int | None]:
        """Return (month, year) from the first valid full date found in rows."""
        for row in rows:
            row_str = " ".join(str(c) for c in row)
            m = _DATE_RE.search(row_str)
            if m:
                d_n, mo, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
                if yr < 100:
                    yr += 2000
                if 1 <= mo <= 12:
                    try:
                        date(yr, mo, d_n)
                        return mo, yr
                    except ValueError:
                        pass
        # fallback: header text e.g. "ינואר-23"
        heb_months = {
            "ינואר": 1, "פברואר": 2, "מרץ": 3, "אפריל": 4,
            "מאי": 5, "יוני": 6, "יולי": 7, "אוגוסט": 8,
            "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
        }
        for name, mo in heb_months.items():
            m2 = re.search(rf"{name}[-–/](\d{{2,4}})", text)
            if m2:
                yr = int(m2.group(1))
                if yr < 100:
                    yr += 2000
                return mo, yr
        return None, None

    # ── anchor-based consistency check ────────────────────────────────────────

    def _validate_against_anchors(
        self,
        parsed: list[tuple[WorkDay | None, str]],
        ref_month: int | None,
        ref_year:  int | None,
    ) -> list[tuple[WorkDay | None, str]]:
        """
        Clear WorkDay assignments that contradict the monotone ordering imposed
        by reliably-parsed "anchor" dates (full D/M/Y with valid month).

        Example: if line N has provisional date 20/Jan but lines N+3 has anchor
        4/Jan, the provisional date is clearly wrong → cleared to None so that
        Pass 4 (sequential fill) can reassign it.
        """
        # Collect indices and dates of "anchor" rows (full 3-part date, valid month)
        anchors: list[tuple[int, date]] = []
        for i, (wd, row_str) in enumerate(parsed):
            if wd is None or wd.date.year <= 1900:
                continue
            m = _DATE_RE.search(row_str)
            if m:
                mo = int(m.group(2))
                yr = int(m.group(3))
                if yr < 100:
                    yr += 2000
                if 1 <= mo <= 12 and mo == (ref_month or mo) and yr == (ref_year or yr):
                    anchors.append((i, wd.date))

        if not anchors:
            return parsed

        result = list(parsed)

        # For each non-anchor WorkDay, verify it falls within the window
        # defined by the nearest preceding and following anchors.
        for i, (wd, row_str) in enumerate(result):
            if wd is None or wd.date.year <= 1900:
                continue
            # skip if this IS an anchor
            if any(ai == i for ai, _ in anchors):
                continue
            # find surrounding anchors
            prev_anchors = [(ai, ad) for ai, ad in anchors if ai < i]
            next_anchors = [(ai, ad) for ai, ad in anchors if ai > i]
            lo = prev_anchors[-1][1] if prev_anchors else date(ref_year or 1900, ref_month or 1, 1)
            hi = next_anchors[0][1]  if next_anchors else date(ref_year or 9999, ref_month or 12, 31)
            if not (lo < wd.date < hi):
                result[i] = (None, row_str)   # clear → gap-fill will reassign

        return result

    # ── gap-filling (weekday then sequential) ─────────────────────────────────

    def _fill_gaps(
        self,
        parsed: list[tuple[WorkDay | None, str]],
        ref_month: int | None,
        ref_year:  int | None,
    ) -> list[tuple[WorkDay | None, str]]:
        """
        Two strategies in order:
        1. If a None row has a recognisable Hebrew day-of-week name, find the
           first date in ref_month with that weekday that comes after the last
           assigned date.
        2. Otherwise (day name unreadable / missing), assign the next sequential
           date after the last assigned date, using row has numeric/time content
           as the condition (skip pure-noise rows).
        """
        if not ref_month or not ref_year:
            return parsed

        days_in_month = monthrange(ref_year, ref_month)[1]
        used_dates: set[date] = {
            wd.date for wd, _ in parsed if wd is not None and wd.date.year > 1900
        }
        # last confirmed date so far (initialise before the first row)
        last_date = date(ref_year, ref_month, 1) - timedelta(days=1)

        # update last_date to max known date before we start
        known = [wd.date for wd, _ in parsed if wd and wd.date.year > 1900]
        # don't pre-set last_date; we'll advance it row by row in order

        result = list(parsed)
        # Snap last_date to one day before the first real date
        last_date = date(ref_year, ref_month, 1) - timedelta(days=1)

        for i, (wd, row_str) in enumerate(result):
            if wd is not None and wd.date.year > 1900:
                last_date = wd.date
                continue

            # Is this row worth assigning a date to?
            # Skip only if it has neither numeric content nor a recognisable day name.
            has_digits   = bool(re.search(r"\d", row_str))
            has_day_name = self._find_weekday(row_str) is not None
            if not has_digits and not has_day_name:
                continue

            # Strategy 1: weekday name
            weekday = self._find_weekday(row_str)
            if weekday is not None:
                resolved = self._next_date_with_weekday(
                    weekday, last_date, ref_month, ref_year, used_dates
                )
                if resolved:
                    new_wd = self._build_workday(resolved, row_str)
                    result[i] = (new_wd, row_str)
                    used_dates.add(resolved)
                    last_date = resolved
                    continue

            # Strategy 2: sequential
            next_day = last_date + timedelta(days=1)
            while next_day.month == ref_month and next_day in used_dates:
                next_day += timedelta(days=1)
            if next_day.month == ref_month:
                new_wd = self._build_workday(next_day, row_str)
                result[i] = (new_wd, row_str)
                used_dates.add(next_day)
                last_date = next_day

        return result

    # ── weekday helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _find_weekday(row_str: str) -> int | None:
        """Return Python weekday (0=Mon…6=Sun) from a (possibly garbled) day name."""
        for heb, wd in _HEB_WEEKDAY.items():
            if heb in row_str:
                return wd
            # Prefix match (OCR often drops last char)
            if len(heb) >= 3 and heb[:3] in row_str:
                return wd
        return None

    @staticmethod
    def _nearest_date_with_weekday(
        near_day: int, weekday: int, ref_month: int, ref_year: int
    ) -> date | None:
        """Date in ref_month with given weekday whose day-number is nearest to near_day."""
        days_in_month = monthrange(ref_year, ref_month)[1]
        best: date | None = None
        best_dist = float("inf")
        for d in range(1, days_in_month + 1):
            candidate = date(ref_year, ref_month, d)
            if candidate.weekday() == weekday:
                dist = abs(d - near_day)
                if dist < best_dist:
                    best_dist = dist
                    best = candidate
        return best

    @staticmethod
    def _next_date_with_weekday(
        weekday: int,
        after: date,
        ref_month: int,
        ref_year: int,
        used: set[date] | None = None,
    ) -> date | None:
        """First date in ref_month whose weekday == weekday and > after."""
        days_in_month = monthrange(ref_year, ref_month)[1]
        for d in range(1, days_in_month + 1):
            candidate = date(ref_year, ref_month, d)
            if candidate.weekday() == weekday and candidate > after:
                if used is None or candidate not in used:
                    return candidate
        return None

    # ── row parsing ────────────────────────────────────────────────────────────

    def _parse_row(
        self,
        cells: list[str],
        ref_month: int | None = None,
        ref_year:  int | None = None,
    ) -> WorkDay | None:
        row_str = " ".join(str(c) for c in cells)

        # Holiday / Shabbat rows: label present, no date
        if not _DATE_RE.search(row_str):
            for label in _HOLIDAY_LABELS:
                if label in row_str:
                    day_type = DayType.SHABBAT if label == "שבת" else DayType.HOLIDAY
                    return WorkDay(
                        date=date(1900, 1, 1),
                        day_type=day_type,
                        notes=label,
                    )
            # ── Partial-date fallback: DD/YY without a month component ─────────
            partial = _DATE_PARTIAL_RE.search(row_str)
            if partial and ref_month and ref_year:
                work_date = self._partial_to_date(
                    int(partial.group(1)), int(partial.group(2)),
                    ref_month, ref_year, row_str,
                )
                if work_date:
                    return self._build_workday(work_date, row_str)
            return None

        m = _DATE_RE.search(row_str)
        if not m:
            return None

        day_n  = int(m.group(1))
        mon_n  = int(m.group(2))
        year_n = int(m.group(3))
        if year_n < 100:
            year_n += 2000

        # ── Fix invalid month and/or year via context ─────────────────────────
        month_was_garbled = (mon_n == 0 or mon_n > 12)
        if month_was_garbled and ref_month:
            mon_n = ref_month
        if ref_year and year_n != ref_year:
            try:
                candidate = date(year_n, mon_n, day_n)
                if not self._weekday_ok(candidate, row_str):
                    fixed = date(ref_year, ref_month or mon_n, day_n)
                    if self._weekday_ok(fixed, row_str):
                        mon_n  = fixed.month
                        year_n = fixed.year
            except ValueError:
                pass

        try:
            work_date = date(year_n, mon_n, day_n)
        except ValueError:
            if ref_month and ref_year:
                try:
                    work_date = date(ref_year, ref_month, day_n)
                except ValueError:
                    return None
            else:
                return None

        # ── Weekday correction when month was garbled / year was wrong ────────
        # After all fixes, if the day-name in the row doesn't match the date
        # we built, find the date in ref_month with the matching weekday that
        # is closest in day-number to what we parsed.
        if ref_month and ref_year and not self._weekday_ok(work_date, row_str):
            weekday = self._find_weekday(row_str)
            if weekday is not None:
                corrected = self._nearest_date_with_weekday(
                    day_n, weekday, ref_month, ref_year
                )
                if corrected:
                    work_date = corrected

        return self._build_workday(work_date, row_str)

    # ── helper: build WorkDay from a resolved date + raw row string ───────────

    @staticmethod
    def _build_workday(work_date: date, row_str: str) -> WorkDay:
        times = _TIME_RE.findall(row_str)
        shift: ShiftTime | None = None
        if len(times) >= 2:
            try:
                entry = time(int(times[0][0]), int(times[0][1]))
                exit_ = time(int(times[1][0]), int(times[1][1]))
                shift = ShiftTime(entry=entry, exit=exit_, break_minutes=0)
            except ValueError:
                pass

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

    # ── helper: validate date against Hebrew day-of-week name in row ──────────

    @staticmethod
    def _weekday_ok(d: date, row_str: str) -> bool:
        """Return True if no day name in row, or the name matches the date."""
        for heb, wd in _HEB_WEEKDAY.items():
            if heb in row_str:
                return d.weekday() == wd
        return True    # no day name found → cannot validate

    # ── helper: resolve partial DD/YY token to a full date ───────────────────

    @staticmethod
    def _partial_to_date(
        day: int, year_short: int,
        ref_month: int, ref_year: int,
        row_str: str,
    ) -> date | None:
        year = year_short if year_short >= 100 else year_short + 2000
        try:
            d = date(year, ref_month, day)
        except ValueError:
            return None
        if TypeBParser._weekday_ok(d, row_str):
            return d
        # Day name disagrees — find closest matching weekday in month
        wd = TypeBParser._find_weekday(row_str)
        if wd is not None:
            return TypeBParser._nearest_date_with_weekday(day, wd, ref_month, year)
        return d

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
        # Try label-before-number (LTR OCR rendering)
        m = re.search(r"מחיר לשעה[\s:₪]*([\d,]+\.?\d*)", text)
        # Try number-before-label (RTL OCR rendering, occasionally produced by pdfplumber)
        if not m:
            m = re.search(r"([\d,]+\.?\d*)[\s₪]*מחיר לשעה", text)
        if not m:
            return None
        rate = _parse_dec(m.group(1))
        if rate <= Decimal("0"):
            return None
        # Enforce business-rule minimum
        return max(rate, _MIN_HOURLY_RATE)

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
