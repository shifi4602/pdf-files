from __future__ import annotations
import copy
from datetime import datetime, timedelta
from decimal import Decimal

from interfaces import IVariationEngine
from models import (
    AttendanceReport, DayType, HourBreakdown,
    ReportSummary, ReportType, ShiftTime, WorkDay,
)


class TypeAVariationEngine(IVariationEngine):
    """
    Deterministic variation rules for Type A (נשר כח אדם) reports.

    Design (interview note):
    ─────────────────────────────────────────────────────────────────────
    All variation deltas are computed purely from the date of each row
    → no random state, no seeds, no side effects.
    The same input PDF always produces the same output.

    Rules applied per day:
    ┌──────────────────┬───────────────────────────────────────────────┐
    │ Property         │ Rule                                          │
    ├──────────────────┼───────────────────────────────────────────────┤
    │ Entry time       │ ± (day_of_month % 3) × 5 min                 │
    │                  │   odd  day → subtract (earlier start)         │
    │                  │   even day → add      (later start)           │
    │                  │   Clamped to 06:00–10:59                      │
    │ Total hours      │ Preserved exactly from source                 │
    │ Exit time        │ Recalculated: new_entry + total + break       │
    │ Break            │ Unchanged                                     │
    │ Overtime split   │ Re-classified from new total                  │
    │                  │   ≤ 8 h  → 100%                              │
    │                  │   8–9 h  → 125%                              │
    │                  │   > 9 h  → 150%                              │
    │ Shabbat rows     │ Entry ± (day % 2) × 15 min, total preserved  │
    │ Monthly totals   │ Re-summed from all rows (never guessed)       │
    └──────────────────┴───────────────────────────────────────────────┘
    """

    def can_handle(self, report_type: ReportType) -> bool:
        return report_type == ReportType.TYPE_A

    def apply(self, report: AttendanceReport) -> AttendanceReport:
        new_report = copy.deepcopy(report)
        new_report.days = [self._vary_day(d) for d in new_report.days]
        new_report.summary = self._rebuild_summary(new_report.days, report.summary)
        return new_report

    # ── per-day logic ──────────────────────────────────────────────────────────

    def _vary_day(self, day: WorkDay) -> WorkDay:
        if day.shift is None:
            return day  # Shabbat / holiday rows without times → untouched

        d = day.date.day

        # Shabbat: use ±15 min based on even/odd
        if day.day_type == DayType.SHABBAT:
            delta_min = (d % 2) * 15
        else:
            delta_min = (d % 3) * 5   # 0, 5, or 10 minutes

        direction = 1 if d % 2 == 0 else -1
        delta = timedelta(minutes=direction * delta_min)

        # New entry (clamped so it stays in working-hours range)
        base_entry = datetime.combine(day.date, day.shift.entry)
        new_entry_dt = self._clamp(base_entry + delta, hour_min=6, hour_max=11)

        # Preserve total hours → recalculate exit
        total_mins = int(day.shift.total_hours() * 60)
        new_exit_dt = new_entry_dt + timedelta(minutes=total_mins + day.shift.break_minutes)

        new_shift = ShiftTime(
            entry=new_entry_dt.time(),
            exit=new_exit_dt.time(),
            break_minutes=day.shift.break_minutes,
        )
        assert new_shift.is_valid(), f"Variation produced invalid shift on {day.date}"

        breakdown = self._classify(new_shift.total_hours(), day.day_type)

        return WorkDay(
            date=day.date,
            day_type=day.day_type,
            shift=new_shift,
            breakdown=breakdown,
            location=day.location,
            notes=day.notes,
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

    # ── summary rebuild ────────────────────────────────────────────────────────

    def _rebuild_summary(
        self, days: list[WorkDay], original: ReportSummary | None
    ) -> ReportSummary:
        work_days  = [d for d in days if d.shift is not None]
        total_100  = sum(d.breakdown.hours_100     for d in days if d.breakdown)
        total_125  = sum(d.breakdown.hours_125     for d in days if d.breakdown)
        total_150  = sum(d.breakdown.hours_150     for d in days if d.breakdown)
        total_shab = sum(d.breakdown.hours_shabbat for d in days if d.breakdown)
        total_h    = total_100 + total_125 + total_150 + total_shab

        return ReportSummary(
            total_days=len(work_days),
            total_hours=total_h,
            breakdown=HourBreakdown(total_100, total_125, total_150, total_shab),
            bonus =original.bonus  if original else Decimal("0"),
            travel=original.travel if original else Decimal("0"),
        )

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _clamp(dt: datetime, hour_min: int, hour_max: int) -> datetime:
        if dt.hour < hour_min:
            return dt.replace(hour=hour_min, minute=0)
        if dt.hour >= hour_max:
            return dt.replace(hour=hour_max - 1, minute=55)
        return dt
