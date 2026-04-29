"""
TransformationService — applies row-level strategies via a registry.

Registry Pattern:
  strategy_registry maps ReportType.name ("TYPE_A" / "TYPE_B") to a
  BaseTransformationStrategy instance.  Adding support for a new report type
  requires one new strategy class and one new registry entry; nothing else
  changes.

Error handling:
  ValidatingStrategyDecorator raises TransformationError on invalid rows.
  The service catches it and falls back to the original (pre-transform) row,
  so a single bad row never aborts the entire report.
"""
from __future__ import annotations

import dataclasses

from core.exceptions import TransformationError
from core.interfaces import BaseTransformationStrategy
from models import AttendanceReport, ReportSummary, WorkDay


class TransformationService:
    """
    Applies deterministic variation rules to an AttendanceReport.

    The service is completely unaware of report-type specifics:
      • It selects the strategy via the registry key (ReportType.name).
      • It calls transform_row() and rebuild_summary() on whatever object
        the registry provides — raw strategy or ValidatingStrategyDecorator.
      • It never inspects or branches on the report type itself.
    """

    def __init__(
        self,
        strategy_registry: dict[str, BaseTransformationStrategy],
    ) -> None:
        self._registry = strategy_registry

    def transform(self, report: AttendanceReport) -> AttendanceReport:
        """
        Return a NEW AttendanceReport with all rows varied according to the
        registered strategy.  The original report is never mutated.

        If no strategy is registered for this report type, the original report
        is returned unchanged.
        """
        strategy = self._registry.get(report.report_type.name)
        if strategy is None:
            return report

        new_days: list[WorkDay] = []
        for day in report.days:
            try:
                new_days.append(strategy.transform_row(day))
            except TransformationError:
                new_days.append(day)   # fallback: keep the original row

        new_summary: ReportSummary | None = strategy.rebuild_summary(
            new_days, report.summary
        )

        return dataclasses.replace(report, days=new_days, summary=new_summary)
