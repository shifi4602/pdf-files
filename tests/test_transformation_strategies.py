"""Tests for TypeA and TypeB transformation strategies."""
from __future__ import annotations
import pytest
from datetime import date, time
from decimal import Decimal

from tests.conftest import make_regular_day, make_shabbat_day
from models import DayType, ShiftTime, WorkDay
from transformation.strategies import (
    TypeATransformationStrategy,
    TypeBTransformationStrategy,
)


class TestTypeATransformationStrategy:
    def setup_method(self) -> None:
        self.strategy = TypeATransformationStrategy()

    def test_no_shift_row_returned_unchanged(self) -> None:
        day = WorkDay(date=date(2022, 10, 1), day_type=DayType.SHABBAT, shift=None)
        result = self.strategy.transform_row(day)
        assert result is day

    def test_total_hours_preserved_exactly(self) -> None:
        # Any regular day — total hours must be identical before and after.
        day = make_regular_day(day_num=3)
        original_total = day.shift.total_hours()
        result = self.strategy.transform_row(day)
        assert result.shift is not None
        assert result.shift.total_hours() == original_total

    def test_entry_delta_even_day_adds_minutes(self) -> None:
        # day 6: (6 % 3) * 5 = 0 → no shift
        # day 4: (4 % 3) * 5 = 5 min, even → +5 min
        day = make_regular_day(day_num=4)
        original_entry_mins = day.shift.entry.hour * 60 + day.shift.entry.minute
        result = self.strategy.transform_row(day)
        new_entry_mins = result.shift.entry.hour * 60 + result.shift.entry.minute
        assert new_entry_mins == original_entry_mins + 5

    def test_entry_delta_odd_day_subtracts_minutes(self) -> None:
        # day 7: (7 % 3) * 5 = 5 min, odd → -5 min
        day = make_regular_day(day_num=7)
        original_entry_mins = day.shift.entry.hour * 60 + day.shift.entry.minute
        result = self.strategy.transform_row(day)
        new_entry_mins = result.shift.entry.hour * 60 + result.shift.entry.minute
        assert new_entry_mins == original_entry_mins - 5

    def test_shabbat_uses_15_min_rule(self) -> None:
        # Shabbat rule: delta_min = (d % 2) * 15, direction = -1 for odd days.
        # day 7 (odd): (7 % 2) * 15 = 15 min, direction = -1 → entry - 15 min
        day = make_shabbat_day(day_num=7)
        original_entry_mins = day.shift.entry.hour * 60 + day.shift.entry.minute
        result = self.strategy.transform_row(day)
        new_entry_mins = result.shift.entry.hour * 60 + result.shift.entry.minute
        assert new_entry_mins == original_entry_mins - 15

    def test_entry_clamped_to_working_hours(self) -> None:
        # Very early entry should be clamped to 06:00
        early_shift = ShiftTime(entry=time(6, 1), exit=time(14, 31), break_minutes=30)
        day = WorkDay(
            date=date(2022, 10, 7),   # odd day → subtract
            day_type=DayType.REGULAR,
            shift=early_shift,
        )
        result = self.strategy.transform_row(day)
        assert result.shift.entry >= time(6, 0)

    def test_result_shift_is_valid(self) -> None:
        for day_num in range(1, 16):
            day = make_regular_day(day_num=day_num)
            result = self.strategy.transform_row(day)
            assert result.shift.is_valid(), f"Invalid shift on day {day_num}"

    def test_determinism(self) -> None:
        day = make_regular_day(day_num=5)
        r1 = self.strategy.transform_row(day)
        r2 = self.strategy.transform_row(day)
        assert r1.shift.entry == r2.shift.entry
        assert r1.shift.exit  == r2.shift.exit

    def test_rebuild_summary_sums_breakdown(self) -> None:
        from tests.conftest import make_regular_day as mrd
        days = [mrd(2), mrd(7), make_shabbat_day(8)]
        original_summary = None
        summary = self.strategy.rebuild_summary(days, original_summary)
        assert summary is not None
        assert summary.total_days == 3  # all have shifts
        expected = sum(
            d.shift.total_hours() for d in days if d.shift
        )
        assert summary.total_hours == expected


class TestTypeBTransformationStrategy:
    def setup_method(self) -> None:
        self.strategy = TypeBTransformationStrategy()

    def test_shabbat_row_returned_unchanged(self) -> None:
        day = make_shabbat_day(day_num=8)
        result = self.strategy.transform_row(day)
        assert result is day

    def test_holiday_row_returned_unchanged(self) -> None:
        day = WorkDay(
            date=date(2022, 9, 26),
            day_type=DayType.HOLIDAY,
            shift=ShiftTime(time(9, 0), time(15, 0), 0),
            notes="ראש השנה",
        )
        result = self.strategy.transform_row(day)
        assert result is day

    def test_entry_delta_range(self) -> None:
        # day 5: (5 % 5) - 2 = -2 min
        day = WorkDay(
            date=date(2022, 9, 5),
            day_type=DayType.REGULAR,
            shift=ShiftTime(entry=time(8, 30), exit=time(12, 0), break_minutes=0),
        )
        result = self.strategy.transform_row(day)
        assert result.shift.entry == time(8, 28)

    def test_total_hours_clamped_minimum(self) -> None:
        # Very short shift → total must be ≥ 0.50 h after variation
        short_shift = ShiftTime(entry=time(8, 0), exit=time(8, 35), break_minutes=0)
        day = WorkDay(
            date=date(2022, 9, 2),
            day_type=DayType.REGULAR,
            shift=short_shift,
        )
        result = self.strategy.transform_row(day)
        assert result.shift.total_hours() >= Decimal("0.50")

    def test_total_hours_clamped_maximum(self) -> None:
        long_shift = ShiftTime(entry=time(6, 0), exit=time(20, 0), break_minutes=0)
        day = WorkDay(
            date=date(2022, 9, 1),
            day_type=DayType.REGULAR,
            shift=long_shift,
        )
        result = self.strategy.transform_row(day)
        assert result.shift.total_hours() <= Decimal("12.00")

    def test_result_shift_is_valid(self) -> None:
        for day_num in range(1, 16):
            shift = ShiftTime(entry=time(8, 30), exit=time(12, 0), break_minutes=0)
            day = WorkDay(
                date=date(2022, 9, day_num),
                day_type=DayType.REGULAR,
                shift=shift,
            )
            result = self.strategy.transform_row(day)
            assert result.shift.is_valid(), f"Invalid shift on day {day_num}"

    def test_determinism(self) -> None:
        shift = ShiftTime(entry=time(9, 0), exit=time(14, 0), break_minutes=0)
        day = WorkDay(
            date=date(2022, 9, 3),
            day_type=DayType.REGULAR,
            shift=shift,
        )
        r1 = self.strategy.transform_row(day)
        r2 = self.strategy.transform_row(day)
        assert r1.shift.entry        == r2.shift.entry
        assert r1.shift.total_hours() == r2.shift.total_hours()

    def test_rebuild_summary_respects_minimum_rate(self) -> None:
        from models import ReportSummary, ReportType
        days = [
            WorkDay(
                date=date(2022, 9, d),
                day_type=DayType.REGULAR,
                shift=ShiftTime(time(8, 0), time(12, 0), 0),
            )
            for d in [1, 2, 3]
        ]
        original = ReportSummary(
            total_days=3, total_hours=Decimal("12"),
            hourly_rate=Decimal("10"),   # below minimum → should be bumped to 33
        )
        summary = self.strategy.rebuild_summary(days, original)
        assert summary is not None
        assert summary.hourly_rate == Decimal("33")
