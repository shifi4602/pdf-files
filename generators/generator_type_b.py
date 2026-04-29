from __future__ import annotations
from decimal import Decimal
from pathlib import Path

from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.interfaces import IGenerator
from models import AttendanceReport, DayType, ReportSummary, ReportType

FONT_PATH = Path(__file__).parent.parent / "fonts" / "NotoSansHebrew-Regular.ttf"
FONT_NAME = "NotoSansHebrew"

_GREY  = colors.HexColor("#D3D3D3")
_DARK  = colors.HexColor("#707070")
_LIGHT = colors.HexColor("#F5F5F5")
_WHITE = colors.white
_BLACK = colors.black

_HEADERS = [
    "הערות", 'סה"כ שעות', "שעת יציאה", "שעת כניסה", "יום בשבוע", "תאריך",
]
_COL_WIDTHS = [3.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm]

_HEB_MONTHS = [
    "", "ינואר", "פברואר", "מרץ", "אפריל", "מאי", "יוני",
    "יולי", "אוגוסט", "ספטמבר", "אוקטובר", "נובמבר", "דצמבר",
]


def _register_font() -> None:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))


def _h(text: str) -> str:
    return get_display(str(text))


def _f(val: Decimal) -> str:
    return f"{val:.2f}"


class TypeBGenerator(IGenerator):
    """
    Generates a Type B attendance PDF (כרטיס עובד format).

    Layout:
    - Employee name header (right-aligned)
    - Summary box (top-right): ימי עבודה / שעות / מחיר לשעה / סה"כ לתשלום
    - Month header bar (dark, centred)
    - Attendance table: one row per day, Shabbat / holiday rows grey + label
    - Totals row at the bottom
    """

    def can_generate(self, report_type: ReportType) -> bool:
        return report_type == ReportType.TYPE_B

    def generate(self, report: AttendanceReport, output_path: Path) -> None:
        _register_font()

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=1.2*cm, leftMargin=1.2*cm,
            topMargin=1.5*cm,   bottomMargin=1.5*cm,
        )

        s_title = ParagraphStyle("Title", fontName=FONT_NAME, fontSize=11,
                                 leading=16, alignment=2)

        elements = []

        # ── Employee header ────────────────────────────────────────────────────
        emp = report.employee_name or "עובד"
        elements.append(Paragraph(_h(f"שם העובד: {emp}"), s_title))
        elements.append(Spacer(1, 0.3*cm))

        # ── Summary box ────────────────────────────────────────────────────────
        if report.summary:
            elements.append(self._summary_box(report.summary))
            elements.append(Spacer(1, 0.4*cm))

        # ── Month header bar ───────────────────────────────────────────────────
        month_name = _HEB_MONTHS[report.month] if 1 <= report.month <= 12 else str(report.month)
        year_short = str(report.year)[2:]
        header_label = _h(f"כרטיס עובד לחודש: {month_name}-{year_short}")

        hdr_tbl = Table([[header_label]], colWidths=[sum(_COL_WIDTHS)])
        hdr_tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), _DARK),
            ("TEXTCOLOR",  (0, 0), (-1, -1), _WHITE),
            ("FONTNAME",   (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE",   (0, 0), (-1, -1), 10),
            ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
            ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        elements.append(hdr_tbl)
        elements.append(Spacer(1, 0.3*cm))

        # ── Attendance table ───────────────────────────────────────────────────
        table_data: list[list[str]] = [[_h(col) for col in _HEADERS]]

        for day in report.days:
            is_special = day.day_type in (DayType.SHABBAT, DayType.HOLIDAY)

            if day.date.year > 1900:
                date_str = day.date.strftime("%d/%m/%y").lstrip("0")
                day_name = _h(self._day_name(day.date.weekday()))
            else:
                date_str = ""
                day_name = ""

            if day.shift and not is_special:
                entry = day.shift.entry.strftime("%H:%M")
                exit_ = day.shift.exit.strftime("%H:%M")
                total = _f(day.shift.total_hours())
            else:
                entry = exit_ = ""
                total = "0.00" if not is_special else ""

            notes = _h(day.notes) if day.notes else ""
            table_data.append([notes, total, exit_, entry, day_name, date_str])

        # Totals row
        s = report.summary
        if s:
            table_data.append(["", _f(s.total_hours), "", "", "", str(s.total_days)])

        tbl = Table(table_data, colWidths=_COL_WIDTHS, repeatRows=1)
        style = TableStyle([
            ("BACKGROUND",     (0, 0),  (-1, 0),  _DARK),
            ("TEXTCOLOR",      (0, 0),  (-1, 0),  _WHITE),
            ("FONTNAME",       (0, 0),  (-1, -1), FONT_NAME),
            ("FONTSIZE",       (0, 0),  (-1, -1), 8),
            ("ALIGN",          (0, 0),  (-1, -1), "CENTER"),
            ("VALIGN",         (0, 0),  (-1, -1), "MIDDLE"),
            ("GRID",           (0, 0),  (-1, -1), 0.4, _BLACK),
            ("ROWBACKGROUNDS", (0, 1),  (-1, -2), [_WHITE, _LIGHT]),
            ("BACKGROUND",     (0, -1), (-1, -1), _LIGHT),
        ])

        for i, day in enumerate(report.days, start=1):
            if day.day_type in (DayType.SHABBAT, DayType.HOLIDAY):
                style.add("BACKGROUND", (0, i), (-1, i), _GREY)

        tbl.setStyle(style)
        elements.append(tbl)

        doc.build(elements)

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _summary_box(s: ReportSummary) -> Table:
        rate_str    = f"\u20aa {s.hourly_rate:.2f}"   if s.hourly_rate    else ""
        payment_str = f"\u20aa {s.total_payment:.2f}" if s.total_payment  else ""

        rows: list[list[str]] = [
            [str(s.total_days),   _h('סה"כ ימי עבודה לחודש')],
            [_f(s.total_hours),   _h('סה"כ שעות חודשיות')],
            [_h(rate_str),        _h("מחיר לשעה")],
            [_h(payment_str),     _h('סה"כ לתשלום')],
        ]

        tbl = Table(rows, colWidths=[3.5*cm, 5*cm], hAlign="RIGHT")
        tbl.setStyle(TableStyle([
            ("FONTNAME",   (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE",   (0, 0), (-1, -1), 9),
            ("ALIGN",      (0, 0), (0, -1),  "CENTER"),
            ("ALIGN",      (1, 0), (1, -1),  "RIGHT"),
            ("GRID",       (0, 0), (-1, -1), 0.4, _BLACK),
            ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
        ]))
        return tbl

    @staticmethod
    def _day_name(weekday: int) -> str:
        names = ["שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת", "ראשון"]
        return names[weekday]
