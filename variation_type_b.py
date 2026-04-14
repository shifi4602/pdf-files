from __future__ import annotations
import copy
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from interfaces import IVariationEngine
from models import (
    AttendanceReport, DayType, ReportSummary,
    ReportType, ShiftTime, WorkDay,
)


class TypeBVariationEngine(IVariationEngine):
    """
    Deterministic variation rules for Type B (כרטיס עובד) reports.

    Design (interview note):
    ─────────────────────────────────────────────────────────────────────
    All deltas are derived from the day number of each row — no random
    state, fully reproducible.

    Rules applied per day:
    ┌──────────────────┬───────────────────────────────────────────────┐
    │ Property         │ Rule                                          │
    ├──────────────────┼───────────────────────────────────────────────┤
    │ Entry time       │ (day % 5) - 2  →  range [–2 … +2] minutes   │
    │ Total hours      │ ± 0.05 × (day % 3)  →  0, ±0.05, or ±0.10  │
    │                  │   even day → subtract; odd day → add          │
    │                  │   Clamped to [0.50 … 12.00] hours             │
    │ Exit time        │ Recalculated: new_entry + new_total           │
    │ Shabbat/holiday  │ Rows left completely unchanged                │
    │ Monthly hours    │ Re-summed from all rows                       │
    │ סה"כ לתשלום      │ new_total_hours × original hourly_rate        │
    │ Hourly rate      │ Never changed (it's a contract rate)          │
    └──────────────────┴───────────────────────────────────────────────┘
    """

    def can_handle(self, report_type: ReportType) -> bool:
        return report_type == ReportType.TYPE_B

    def apply(self, report: AttendanceReport) -> AttendanceReport:
        new_report = copy.deepcopy(report)
        new_report.days = [self._vary_day(d) for d in new_report.days]
        new_report.summary = self._rebuild_summary(new_report.days, report.summary)
        return new_report

    # ── per-day logic ──────────────────────────────────────────────────────────

    def _vary_day(self, day: WorkDay) -> WorkDay:
        # Never touch Shabbat / holiday rows
        if day.day_type in (DayType.SHABBAT, DayType.HOLIDAY) or day.shift is None:
            return day

        d = day.date.day

        # Entry delta: –2 to +2 minutes
        entry_delta = timedelta(minutes=(d % 5) - 2)
        new_entry_dt = datetime.combine(day.date, day.shift.entry) + entry_delta
        new_entry = new_entry_dt.time()

        # Total-hours delta: 0, +0.05, or –0.10 (even: subtract, odd: add)
        magnitude = Decimal("0.05") * (d % 3)          # 0, 0.05, 0.10
        direction = Decimal("-1") if d % 2 == 0 else Decimal("1")
        original_total = day.shift.total_hours()
        new_total = (original_total + direction * magnitude).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_total = max(new_total, Decimal("0.50"))
        new_total = min(new_total, Decimal("12.00"))

        # Exit = entry + total
        new_exit_dt = new_entry_dt + timedelta(minutes=int(new_total * 60))
        new_exit = new_exit_dt.time()

        new_shift = ShiftTime(
            entry=new_entry,
            exit=new_exit,
            break_minutes=day.shift.break_minutes,
        )
        assert new_shift.is_valid(), f"Variation produced invalid shift on {day.date}"

        return WorkDay(
            date=day.date,
            day_type=day.day_type,
            shift=new_shift,
            notes=day.notes,
            location=day.location,
        )

    # ── summary rebuild ────────────────────────────────────────────────────────

    def _rebuild_summary(
        self, days: list[WorkDay], original: ReportSummary | None
    ) -> ReportSummary:
        work_days   = [d for d in days if d.shift is not None]
        total_hours = sum(
            d.shift.total_hours() for d in work_days if d.shift
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        hourly_rate   = original.hourly_rate if original else None
        total_payment = (
            (total_hours * hourly_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if hourly_rate else None
        )

        return ReportSummary(
            total_days=len(work_days),
            total_hours=total_hours,
            hourly_rate=hourly_rate,
            total_payment=total_payment,
        )
