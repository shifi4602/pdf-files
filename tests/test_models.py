"""Unit tests for domain value objects (ShiftTime, HourBreakdown)."""
from datetime import time
from decimal import Decimal
import pytest

from models import ShiftTime, HourBreakdown


class TestShiftTime:

    def test_total_hours_standard(self):
        s = ShiftTime(entry=time(8, 0), exit=time(15, 0), break_minutes=30)
        assert s.total_hours() == Decimal("6.50")

    def test_total_hours_no_break(self):
        s = ShiftTime(entry=time(8, 30), exit=time(12, 0), break_minutes=0)
        assert s.total_hours() == Decimal("3.50")

    def test_total_hours_fractional_minutes(self):
        # 8:01 → 11:04  = 183 min, no break → 3.05 h
        s = ShiftTime(entry=time(8, 1), exit=time(11, 4), break_minutes=0)
        assert s.total_hours() == Decimal("3.05")

    def test_is_valid_true(self):
        s = ShiftTime(entry=time(8, 0), exit=time(15, 0), break_minutes=30)
        assert s.is_valid() is True

    def test_is_valid_false_exit_before_entry(self):
        s = ShiftTime(entry=time(15, 0), exit=time(8, 0), break_minutes=30)
        assert s.is_valid() is False

    def test_is_valid_false_only_break_remains(self):
        # 8:00 → 8:20, break = 30 → net = –10 min → invalid
        s = ShiftTime(entry=time(8, 0), exit=time(8, 20), break_minutes=30)
        assert s.is_valid() is False

    def test_immutable(self):
        s = ShiftTime(entry=time(8, 0), exit=time(15, 0))
        with pytest.raises(Exception):
            s.entry = time(9, 0)  # type: ignore[misc]


class TestHourBreakdown:

    def test_total(self):
        b = HourBreakdown(
            hours_100=Decimal("6.50"),
            hours_125=Decimal("1.00"),
            hours_150=Decimal("0.50"),
            hours_shabbat=Decimal("0"),
        )
        assert b.total() == Decimal("8.00")

    def test_default_zeroes(self):
        b = HourBreakdown()
        assert b.total() == Decimal("0")
