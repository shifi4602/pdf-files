"""Shared pytest fixtures used across all test modules."""
from __future__ import annotations
import pytest
from datetime import date, time
from decimal import Decimal

from models import (
    AttendanceReport, DayType, HourBreakdown,
    ReportSummary, ReportType, ShiftTime, WorkDay,
)


# ── Factory helpers ────────────────────────────────────────────────────────────

def make_regular_day(
    day_num: int,
    month: int = 10,
    year:  int = 2022,
    entry: tuple[int, int] = (8, 0),
    exit_: tuple[int, int] = (15, 0),
    break_mins: int = 30,
    location: str = "גליליון",
) -> WorkDay:
    shift = ShiftTime(
        entry=time(*entry),
        exit=time(*exit_),
        break_minutes=break_mins,
    )
    total = shift.total_hours()
    h100  = min(total, Decimal("8"))
    rem   = total - h100
    h125  = min(rem, Decimal("1"))
    h150  = max(rem - Decimal("1"), Decimal("0"))
    return WorkDay(
        date=date(year, month, day_num),
        day_type=DayType.REGULAR,
        shift=shift,
        breakdown=HourBreakdown(h100, h125, h150),
        location=location,
    )


def make_shabbat_day(day_num: int, month: int = 10, year: int = 2022) -> WorkDay:
    shift = ShiftTime(entry=time(9, 0), exit=time(15, 30), break_minutes=30)
    total = shift.total_hours()
    return WorkDay(
        date=date(year, month, day_num),
        day_type=DayType.SHABBAT,
        shift=shift,
        breakdown=HourBreakdown(hours_shabbat=total),
        location="גליליון",
    )


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def sample_type_a_report() -> AttendanceReport:
    days = [
        make_regular_day(2),
        make_regular_day(7),
        make_shabbat_day(8),
        make_regular_day(9),
        make_regular_day(14),
        make_regular_day(15),
    ]
    total_100  = sum(d.breakdown.hours_100     for d in days if d.breakdown)
    total_125  = sum(d.breakdown.hours_125     for d in days if d.breakdown)
    total_150  = sum(d.breakdown.hours_150     for d in days if d.breakdown)
    total_shab = sum(d.breakdown.hours_shabbat for d in days if d.breakdown)
    total_h    = total_100 + total_125 + total_150 + total_shab

    return AttendanceReport(
        report_type=ReportType.TYPE_A,
        employee_name='הנשר כח אדם בע"מ',
        month=10, year=2022,
        days=days,
        summary=ReportSummary(
            total_days=5,
            total_hours=total_h,
            breakdown=HourBreakdown(total_100, total_125, total_150, total_shab),
        ),
    )


@pytest.fixture
def sample_type_b_report() -> AttendanceReport:
    days: list[WorkDay] = []
    for day_num in [1, 2, 4, 5, 7, 8, 11, 12]:
        shift = ShiftTime(entry=time(8, 30), exit=time(12, 0), break_minutes=0)
        days.append(WorkDay(
            date=date(2022, 9, day_num),
            day_type=DayType.REGULAR,
            shift=shift,
        ))
    total_h = sum(d.shift.total_hours() for d in days if d.shift)
    rate    = Decimal("30.65")
    return AttendanceReport(
        report_type=ReportType.TYPE_B,
        employee_name="עובד לדוגמה",
        month=9, year=2022,
        days=days,
        summary=ReportSummary(
            total_days=len(days),
            total_hours=total_h,
            hourly_rate=rate,
            total_payment=(total_h * rate).quantize(Decimal("0.01")),
        ),
    )
