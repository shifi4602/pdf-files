"""Unit tests for TypeBVariationEngine."""
from decimal import Decimal
import pytest

from models import DayType, ReportType
from variation_type_b import TypeBVariationEngine


@pytest.fixture
def engine() -> TypeBVariationEngine:
    return TypeBVariationEngine()


# ── Interface contract ─────────────────────────────────────────────────────────

def test_can_handle_type_b(engine: TypeBVariationEngine) -> None:
    assert engine.can_handle(ReportType.TYPE_B) is True


def test_cannot_handle_type_a(engine: TypeBVariationEngine) -> None:
    assert engine.can_handle(ReportType.TYPE_A) is False


# ── Business rules ─────────────────────────────────────────────────────────────

def test_exit_always_after_entry(engine, sample_type_b_report):
    varied = engine.apply(sample_type_b_report)
    for day in varied.days:
        if day.shift:
            assert day.shift.is_valid(), (
                f"Invalid shift on {day.date}: "
                f"entry={day.shift.entry} exit={day.shift.exit}"
            )


def test_hourly_rate_not_below_minimum(engine, sample_type_b_report):
    """Hourly rate in the varied report must be at least the 33 ILS minimum."""
    from decimal import Decimal
    MIN_RATE = Decimal("33")
    varied = engine.apply(sample_type_b_report)
    if varied.summary.hourly_rate is not None:
        assert varied.summary.hourly_rate >= MIN_RATE

    # Rate above the minimum must stay unchanged (it's a contract rate)
    original_rate = sample_type_b_report.summary.hourly_rate
    if original_rate is not None and original_rate >= MIN_RATE:
        assert varied.summary.hourly_rate == original_rate


def test_payment_equals_hours_times_rate(engine, sample_type_b_report):
    varied = engine.apply(sample_type_b_report)
    s = varied.summary
    if s.hourly_rate and s.total_payment:
        expected = (s.total_hours * s.hourly_rate).quantize(Decimal("0.01"))
        assert s.total_payment == expected


def test_monthly_hours_equals_sum_of_rows(engine, sample_type_b_report):
    varied = engine.apply(sample_type_b_report)
    row_sum = sum(
        d.shift.total_hours() for d in varied.days
        if d.shift and d.day_type == DayType.REGULAR
    ).quantize(Decimal("0.01"))
    assert varied.summary.total_hours == row_sum


def test_shabbat_rows_completely_unchanged(engine, sample_type_b_report):
    """Shabbat / holiday rows must be bit-for-bit identical after variation."""
    from copy import deepcopy
    from models import DayType

    # Add a shabbat row to the fixture
    import models, datetime
    shabbat_day = models.WorkDay(
        date=datetime.date(2022, 9, 3),
        day_type=DayType.SHABBAT,
        notes="שבת",
    )
    sample_type_b_report.days.append(shabbat_day)

    orig_shabbat = deepcopy([
        d for d in sample_type_b_report.days
        if d.day_type in (DayType.SHABBAT, DayType.HOLIDAY)
    ])
    varied = engine.apply(sample_type_b_report)
    varied_shabbat = [
        d for d in varied.days
        if d.day_type in (DayType.SHABBAT, DayType.HOLIDAY)
    ]

    for orig, var in zip(orig_shabbat, varied_shabbat):
        assert orig.date     == var.date
        assert orig.notes    == var.notes
        assert orig.shift    == var.shift


def test_deterministic(engine, sample_type_b_report):
    r1 = engine.apply(sample_type_b_report)
    r2 = engine.apply(sample_type_b_report)
    for d1, d2 in zip(r1.days, r2.days):
        if d1.shift and d2.shift:
            assert d1.shift.entry         == d2.shift.entry
            assert d1.shift.total_hours() == d2.shift.total_hours()


def test_original_not_mutated(engine, sample_type_b_report):
    original_entries = [
        d.shift.entry for d in sample_type_b_report.days if d.shift
    ]
    engine.apply(sample_type_b_report)
    after_entries = [
        d.shift.entry for d in sample_type_b_report.days if d.shift
    ]
    assert original_entries == after_entries
