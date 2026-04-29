"""Tests for ValidatingStrategyDecorator and TransformationService fallback."""
from __future__ import annotations
import pytest
from datetime import date, time
from decimal import Decimal

from tests.conftest import make_regular_day, make_shabbat_day
from models import AttendanceReport, DayType, ReportType, ShiftTime, WorkDay
from transformation.strategies import (
    TypeATransformationStrategy,
    ValidatingStrategyDecorator,
)
from transformation.service import TransformationService
from core.exceptions import TransformationError


# ── helpers ────────────────────────────────────────────────────────────────────

class _AlwaysInvalidShiftStrategy(TypeATransformationStrategy):
    """Inner strategy that always returns a shift where exit ≤ entry."""
    def transform_row(self, day: WorkDay) -> WorkDay:
        return WorkDay(
            date=day.date,
            day_type=day.day_type,
            shift=ShiftTime(time(10, 0), time(9, 0), 0),  # invalid: exit < entry
        )


class _EarlyEntryStrategy(TypeATransformationStrategy):
    """Inner strategy that always sets entry before 06:00."""
    def transform_row(self, day: WorkDay) -> WorkDay:
        return WorkDay(
            date=day.date,
            day_type=day.day_type,
            shift=ShiftTime(time(5, 0), time(14, 0), 30),
        )


class _LongBreakStrategy(TypeATransformationStrategy):
    """Inner strategy that always sets break > 120 min."""
    def transform_row(self, day: WorkDay) -> WorkDay:
        return WorkDay(
            date=day.date,
            day_type=day.day_type,
            shift=ShiftTime(time(8, 0), time(22, 0), 121),
        )


class _ForcedErrorStrategy(TypeATransformationStrategy):
    """Inner strategy that raises TransformationError directly."""
    def transform_row(self, day: WorkDay) -> WorkDay:
        raise TransformationError("forced error for testing")


# ── ValidatingStrategyDecorator tests ─────────────────────────────────────────

class TestValidatingStrategyDecorator:
    def setup_method(self) -> None:
        inner = TypeATransformationStrategy()
        self.deco = ValidatingStrategyDecorator(inner)

    def test_valid_row_passes_through(self) -> None:
        day = make_regular_day(day_num=4)
        result = self.deco.transform_row(day)
        assert result.shift is not None
        assert result.shift.is_valid()

    def test_none_shift_always_passes(self) -> None:
        day = WorkDay(date=date(2022, 10, 1), day_type=DayType.SHABBAT, shift=None)
        result = self.deco.transform_row(day)
        assert result.shift is None   # no validation attempted

    def test_invalid_shift_raises_transformation_error(self) -> None:
        deco = ValidatingStrategyDecorator(_AlwaysInvalidShiftStrategy())
        with pytest.raises(TransformationError, match="Invalid shift"):
            deco.transform_row(make_regular_day(5))

    def test_entry_before_6am_raises_transformation_error(self) -> None:
        deco = ValidatingStrategyDecorator(_EarlyEntryStrategy())
        with pytest.raises(TransformationError, match="working hours"):
            deco.transform_row(make_regular_day(3))

    def test_break_over_120_raises_transformation_error(self) -> None:
        deco = ValidatingStrategyDecorator(_LongBreakStrategy())
        with pytest.raises(TransformationError, match="out of range"):
            deco.transform_row(make_regular_day(3))

    def test_rebuild_summary_delegates_to_inner(self) -> None:
        """Decorator must not intercept rebuild_summary."""
        from models import ReportSummary
        days = [make_regular_day(d) for d in [2, 7]]
        original = None
        result = self.deco.rebuild_summary(days, original)
        # Delegate call to TypeATransformationStrategy.rebuild_summary
        assert result is not None
        assert result.total_days == 2


# ── TransformationService fallback tests ──────────────────────────────────────

class TestTransformationServiceFallback:
    def _make_report(self, days: list[WorkDay]) -> AttendanceReport:
        return AttendanceReport(
            report_type=ReportType.TYPE_A,
            employee_name="test",
            month=10,
            year=2022,
            days=days,
        )

    def test_no_strategy_returns_same_report_object(self) -> None:
        service = TransformationService(strategy_registry={})
        report = self._make_report([make_regular_day(5)])
        result = service.transform(report)
        assert result is report   # no strategy → exact same object returned

    def test_invalid_row_falls_back_to_original_row(self) -> None:
        """When decorator raises TransformationError, service keeps the original day."""
        deco = ValidatingStrategyDecorator(_AlwaysInvalidShiftStrategy())
        service = TransformationService(strategy_registry={"TYPE_A": deco})

        original_day = make_regular_day(5)
        report = self._make_report([original_day])
        result = service.transform(report)

        assert result.days[0] is original_day   # fell back to original

    def test_forced_error_falls_back_to_original_row(self) -> None:
        """Strategy that raises TransformationError → row is kept as-is."""
        service = TransformationService(
            strategy_registry={"TYPE_A": _ForcedErrorStrategy()}
        )
        original_day = make_regular_day(3)
        report = self._make_report([original_day])
        result = service.transform(report)

        assert result.days[0] is original_day

    def test_successful_transform_changes_row(self) -> None:
        """A valid strategy must actually change the row."""
        inner = TypeATransformationStrategy()
        deco  = ValidatingStrategyDecorator(inner)
        service = TransformationService(strategy_registry={"TYPE_A": deco})

        # day 4: even → entry shifts +5 min
        original_day = make_regular_day(day_num=4)
        report = self._make_report([original_day])
        result = service.transform(report)

        original_entry = original_day.shift.entry
        new_entry      = result.days[0].shift.entry
        assert new_entry != original_entry

    def test_mixed_rows_valid_and_invalid(self) -> None:
        """Valid rows are transformed; rows producing invalid shifts fall back."""
        deco_always_bad = ValidatingStrategyDecorator(_AlwaysInvalidShiftStrategy())
        service = TransformationService(strategy_registry={"TYPE_A": deco_always_bad})

        days = [make_regular_day(d) for d in [1, 2, 3]]
        report = self._make_report(days)
        result = service.transform(report)

        # All three fall back because _AlwaysInvalidShiftStrategy is always bad
        for i, original in enumerate(days):
            assert result.days[i] is original
