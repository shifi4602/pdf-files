from __future__ import annotations
from dataclasses import dataclass
from datetime import date, time
from decimal import Decimal
from typing import Optional

from models.base_models import DayType


@dataclass
class AttendanceRow:
    """
    Flat dataclass holding every field that can appear in either report type.

    Fields shared by both report types are required (or have sensible defaults).
    Fields that exist only in one report type default to None; the strategy and
    renderer for that type handle None appropriately.

    Strategy pattern:
      TypeATransformationStrategy  → uses hours_100/125/150/shabbat, location
      TypeBTransformationStrategy  → uses hourly_rate, overtime_125_hours, notes
    """

    # ── Common fields ──────────────────────────────────────────────────────────
    date:          date
    day_type:      DayType
    entry:         Optional[time]    = None
    exit_:         Optional[time]    = None
    break_minutes: int               = 30

    # ── Type A only ────────────────────────────────────────────────────────────
    hours_100:         Optional[Decimal] = None   # regular overtime band
    hours_125:         Optional[Decimal] = None   # 125 % overtime band
    hours_150:         Optional[Decimal] = None   # 150 % overtime band
    hours_shabbat:     Optional[Decimal] = None   # Shabbat hours
    location:          str               = ""     # מקום עבודה

    # ── Type B only ────────────────────────────────────────────────────────────
    hourly_rate:       Optional[Decimal] = None   # מחיר לשעה (contract rate)
    overtime_125_hours: Optional[Decimal] = None  # 125 % hours for Type B
    notes:             str               = ""     # הערות
