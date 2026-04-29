from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal
from enum import Enum
from typing import Optional


class ReportType(Enum):
    TYPE_A = "type_a"   # נשר כח אדם — overtime columns
    TYPE_B = "type_b"   # כרטיס עובד  — flat rate


class DayType(Enum):
    REGULAR = "regular"
    SHABBAT = "shabbat"
    HOLIDAY = "holiday"


@dataclass(frozen=True)
class ShiftTime:
    entry: time
    exit: time
    break_minutes: int = 30

    def is_valid(self) -> bool:
        entry_mins = self.entry.hour * 60 + self.entry.minute
        exit_mins  = self.exit.hour  * 60 + self.exit.minute
        return exit_mins > entry_mins + self.break_minutes

    def total_hours(self) -> Decimal:
        entry_mins = self.entry.hour * 60 + self.entry.minute
        exit_mins  = self.exit.hour  * 60 + self.exit.minute
        net = exit_mins - entry_mins - self.break_minutes
        return Decimal(str(round(net / 60, 2)))


@dataclass(frozen=True)
class HourBreakdown:
    """Overtime breakdown — used only in Type A reports."""
    hours_100:     Decimal = Decimal("0")
    hours_125:     Decimal = Decimal("0")
    hours_150:     Decimal = Decimal("0")
    hours_shabbat: Decimal = Decimal("0")

    def total(self) -> Decimal:
        return self.hours_100 + self.hours_125 + self.hours_150 + self.hours_shabbat


@dataclass
class WorkDay:
    date:      date
    day_type:  DayType
    shift:     Optional[ShiftTime]     = None   # None for Shabbat / holiday rows
    breakdown: Optional[HourBreakdown] = None   # Type A only
    notes:     str                     = ""     # Type B הערות
    location:  str                     = ""     # Type A מקום עבודה


@dataclass
class ReportSummary:
    total_days:    int
    total_hours:   Decimal
    # Type A
    breakdown:     Optional[HourBreakdown] = None
    bonus:         Decimal                 = Decimal("0")
    travel:        Decimal                 = Decimal("0")
    # Type B
    hourly_rate:   Optional[Decimal]       = None
    total_payment: Optional[Decimal]       = None


@dataclass
class AttendanceReport:
    report_type:   ReportType
    employee_name: str
    month:         int
    year:          int
    days:          list[WorkDay]           = field(default_factory=list)
    summary:       Optional[ReportSummary] = None
