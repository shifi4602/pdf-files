"""Unit tests for TypeAVariationEngine."""
from decimal import Decimal
import pytest

from models import DayType, ReportType
from variation_type_a import TypeAVariationEngine


@pytest.fixture
def engine() -> TypeAVariationEngine:
    return TypeAVariationEngine()


# ── Interface contract ─────────────────────────────────────────────────────────

def test_can_handle_type_a(engine: TypeAVariationEngine) -> None:
    assert engine.can_handle(ReportType.TYPE_A) is True


def test_cannot_handle_type_b(engine: TypeAVariationEngine) -> None:
    assert engine.can_handle(ReportType.TYPE_B) is False


# ── Business rules ─────────────────────────────────────────────────────────────

def test_exit_always_after_entry(engine, sample_type_a_report):
    varied = engine.apply(sample_type_a_report)
    for day in varied.days:
        if day.shift:
            assert day.shift.is_valid(), (
                f"Invalid shift on {day.date}: "
                f"entry={day.shift.entry} exit={day.shift.exit}"
            )


def test_total_hours_preserved_per_day(engine, sample_type_a_report):
    """Variation must NOT change the number of hours worked each day."""
    original_totals = {
        d.date: d.shift.total_hours()
        for d in sample_type_a_report.days if d.shift
    }
    varied = engine.apply(sample_type_a_report)
    for day in varied.days:
        if day.shift:
            assert day.shift.total_hours() == original_totals[day.date], (
                f"Total hours changed on {day.date}"
            )


def test_monthly_total_equals_sum_of_rows(engine, sample_type_a_report):
    varied = engine.apply(sample_type_a_report)
    row_total = sum(
        d.shift.total_hours() for d in varied.days if d.shift
    )
    assert varied.summary.total_hours == row_total


def test_shabbat_rows_retain_day_type(engine, sample_type_a_report):
    varied = engine.apply(sample_type_a_report)
    orig_shabbat_dates = {
        d.date for d in sample_type_a_report.days if d.day_type == DayType.SHABBAT
    }
    varied_shabbat_dates = {
        d.date for d in varied.days if d.day_type == DayType.SHABBAT
    }
    assert orig_shabbat_dates == varied_shabbat_dates


def test_breakdown_sums_to_total(engine, sample_type_a_report):
    varied = engine.apply(sample_type_a_report)
    for day in varied.days:
        if day.breakdown and day.shift:
            assert day.breakdown.total() == day.shift.total_hours(), (
                f"Breakdown total != shift total on {day.date}"
            )


def test_deterministic_same_output(engine, sample_type_a_report):
    """Calling apply twice on the same report must yield identical results."""
    r1 = engine.apply(sample_type_a_report)
    r2 = engine.apply(sample_type_a_report)
    for d1, d2 in zip(r1.days, r2.days):
        if d1.shift and d2.shift:
            assert d1.shift.entry == d2.shift.entry
            assert d1.shift.exit  == d2.shift.exit


def test_original_report_not_mutated(engine, sample_type_a_report):
    original_entries = [
        d.shift.entry for d in sample_type_a_report.days if d.shift
    ]
    engine.apply(sample_type_a_report)
    after_entries = [
        d.shift.entry for d in sample_type_a_report.days if d.shift
    ]
    assert original_entries == after_entries
