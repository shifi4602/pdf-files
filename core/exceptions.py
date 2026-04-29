"""Domain exceptions for the attendance report transformation pipeline."""
from __future__ import annotations


class TransformationError(Exception):
    """
    Raised by ValidatingStrategyDecorator when the transformed WorkDay fails
    validation (e.g. exit ≤ entry, entry outside working hours, break out of
    range).

    TransformationService catches this and falls back to the original row.
    """
