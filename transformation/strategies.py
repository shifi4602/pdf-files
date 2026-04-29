"""
Transformation strategies and the validating decorator.

Patterns implemented:
  Strategy  — TypeATransformationStrategy / TypeBTransformationStrategy
              each encapsulates the variation rules for one report type.
              TransformationService selects via registry; no if/else on type.

  Decorator — ValidatingStrategyDecorator wraps any BaseTransformationStrategy,
              calls the inner strategy, then validates the result.
              Raises TransformationError on constraint violations.
              The service cannot distinguish a raw strategy from a decorated one.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from decimal import Decimal, ROUND_HALF_UP

from core.exceptions import TransformationError
from core.interfaces import BaseTransformationStrategy
from models import (
    AttendanceReport, DayType, HourBreakdown,
    ReportSummary, ReportType, ShiftTime, WorkDay,
)

_MIN_HOURLY_RATE = Decimal("33")

# ── shared helper ──────────────────────────────────────────────────────────────

def _clamp(dt: datetime, hour_min: int, hour_max: int) -> datetime:
    """Clamp datetime to [hour_min:00 … (hour_max-1):55]."""
    if dt.hour < hour_min:
        return dt.replace(hour=hour_min, minute=0)
    if dt.hour >= hour_max:
        return dt.replace(hour=hour_max - 1, minute=55)
    return dt


# ── Type A strategy ────────────────────────────────────────────────────────────

class TypeATransformationStrategy(BaseTransformationStrategy):
    """
    Deterministic variation rules for Type A (נשר כח אדם) reports.

    Rules applied per row:
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
    │ Rows without     │ Returned unchanged (no shift to vary)         │
    │  a shift         │                                               │
    └──────────────────┴───────────────────────────────────────────────┘
    """

    def transform_row(self, day: WorkDay) -> WorkDay:
        if day.shift is None:
            return day  # Shabbat / holiday rows without times → untouched

        d = day.date.day

        if day.day_type == DayType.SHABBAT:
            delta_min = (d % 2) * 15
        else:
            delta_min = (d % 3) * 5   # 0, 5, or 10 minutes

        direction = 1 if d % 2 == 0 else -1
        delta = timedelta(minutes=direction * delta_min)

        base_entry = datetime.combine(day.date, day.shift.entry)
        new_entry_dt = _clamp(base_entry + delta, hour_min=6, hour_max=11)

        total_mins = int(day.shift.total_hours() * 60)
        new_exit_dt = new_entry_dt + timedelta(minutes=total_mins + day.shift.break_minutes)

        new_shift = ShiftTime(
            entry=new_entry_dt.time(),
            exit=new_exit_dt.time(),
            break_minutes=day.shift.break_minutes,
        )

        breakdown = self._classify(new_shift.total_hours(), day.day_type)

        return WorkDay(
            date=day.date,
            day_type=day.day_type,
            shift=new_shift,
            breakdown=breakdown,
            location=day.location,
            notes=day.notes,
        )

    def rebuild_summary(
        self,
        days: list[WorkDay],
        original: ReportSummary | None,
    ) -> ReportSummary | None:
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


# ── Type B strategy ────────────────────────────────────────────────────────────

class TypeBTransformationStrategy(BaseTransformationStrategy):
    """
    Deterministic variation rules for Type B (כרטיס עובד) reports.

    Rules applied per row:
    ┌──────────────────┬───────────────────────────────────────────────┐
    │ Property         │ Rule                                          │
    ├──────────────────┼───────────────────────────────────────────────┤
    │ Entry time       │ (day % 5) - 2  →  range [–2 … +2] minutes   │
    │ Total hours      │ ± 0.05 × (day % 3)  →  0, ±0.05, or ±0.10  │
    │                  │   even day → subtract; odd day → add          │
    │                  │   Clamped to [0.50 … 12.00] hours             │
    │ Exit time        │ Recalculated: new_entry + new_total + break   │
    │ Shabbat/holiday  │ Rows left completely unchanged                │
    │ Monthly hours    │ Re-summed from all rows                       │
    │ סה"כ לתשלום      │ new_total_hours × original hourly_rate        │
    │ Hourly rate      │ Never changed (it's a contract rate)          │
    └──────────────────┴───────────────────────────────────────────────┘
    """

    def transform_row(self, day: WorkDay) -> WorkDay:
        if day.day_type in (DayType.SHABBAT, DayType.HOLIDAY) or day.shift is None:
            return day  # Shabbat / holiday rows → untouched

        d = day.date.day

        entry_delta = timedelta(minutes=(d % 5) - 2)
        new_entry_dt = datetime.combine(day.date, day.shift.entry) + entry_delta
        new_entry = new_entry_dt.time()

        magnitude = Decimal("0.05") * (d % 3)
        direction = Decimal("-1") if d % 2 == 0 else Decimal("1")
        _quarter = Decimal("0.25")
        original_total = (day.shift.total_hours() / _quarter).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        ) * _quarter
        new_total = (original_total + direction * magnitude).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        new_total = max(new_total, Decimal("0.50"))
        new_total = min(new_total, Decimal("12.00"))

        new_exit_dt = new_entry_dt + timedelta(
            minutes=int(new_total * 60) + day.shift.break_minutes
        )

        new_shift = ShiftTime(
            entry=new_entry,
            exit=new_exit_dt.time(),
            break_minutes=day.shift.break_minutes,
        )

        return WorkDay(
            date=day.date,
            day_type=day.day_type,
            shift=new_shift,
            notes=day.notes,
            location=day.location,
        )

    def rebuild_summary(
        self,
        days: list[WorkDay],
        original: ReportSummary | None,
    ) -> ReportSummary | None:
        work_days   = [d for d in days if d.shift is not None]
        total_hours = sum(
            d.shift.total_hours() for d in work_days if d.shift
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        hourly_rate = original.hourly_rate if original else None
        if hourly_rate is not None:
            hourly_rate = max(hourly_rate, _MIN_HOURLY_RATE)
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


# ── Validating Decorator ───────────────────────────────────────────────────────

class ValidatingStrategyDecorator(BaseTransformationStrategy):
    """
    Decorator that wraps any BaseTransformationStrategy and validates the
    result of transform_row() before returning it.

    Implements the same BaseTransformationStrategy interface, so
    TransformationService cannot distinguish it from a raw strategy.

    Validation rules (applied when the transformed row has a shift):
      • shift.is_valid()              — exit > entry + break
      • entry ∈ [06:00 … 23:00)      — sensible working-hour range
      • break_minutes ∈ [0 … 120]    — at most 2-hour break

    On any failure → raises TransformationError.
    TransformationService catches that and falls back to the original row.
    """

    def __init__(self, inner: BaseTransformationStrategy) -> None:
        self._inner = inner

    def transform_row(self, day: WorkDay) -> WorkDay:
        result = self._inner.transform_row(day)
        if result.shift is not None:
            self._validate(result)
        return result

    def rebuild_summary(
        self,
        days: list[WorkDay],
        original: ReportSummary | None,
    ) -> ReportSummary | None:
        return self._inner.rebuild_summary(days, original)

    # ── validation ─────────────────────────────────────────────────────────────

    def _validate(self, day: WorkDay) -> None:
        shift = day.shift
        assert shift is not None  # caller guarantees this

        if not shift.is_valid():
            raise TransformationError(
                f"Invalid shift on {day.date}: exit {shift.exit} ≤ entry {shift.entry}"
            )
        if not (time(6, 0) <= shift.entry < time(23, 0)):
            raise TransformationError(
                f"Entry time {shift.entry} on {day.date} is outside working hours"
            )
        if not (0 <= shift.break_minutes <= 120):
            raise TransformationError(
                f"Break of {shift.break_minutes} min on {day.date} is out of range [0..120]"
            )
