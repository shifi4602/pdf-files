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

# Column headers (ReportLab draws LTR; the page is RTL so we list them
# in visual left-to-right order as they should appear on the printed page).
_HEADERS = [
    "שבת", "150%", "125%", "100%",
    'סה"כ', "הפסקה", "יציאה", "כניסה", "מקום", "יום", "תאריך",
]
_COL_WIDTHS = [
    1.3*cm, 1.3*cm, 1.3*cm, 1.3*cm,
    1.4*cm, 1.4*cm, 1.5*cm, 1.5*cm, 2.0*cm, 2.2*cm, 2.4*cm,
]


def _register_font() -> None:
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT_PATH)))


def _h(text: str) -> str:
    """Apply Unicode BiDi algorithm so Hebrew renders correctly in ReportLab."""
    return get_display(str(text))


def _f(val: Decimal) -> str:
    return f"{val:.2f}"


class TypeAGenerator(IGenerator):
    """
    Generates a Type A attendance PDF (נשר כח אדם format).

    Layout:
    - Company name header (right-aligned)
    - Main table: one row per WorkDay, Shabbat rows highlighted grey
    - Totals row at the bottom of the table
    - Summary mini-table (bottom-right): ימים / שעות / breakdown / בונוס / נסיעות
    """

    def can_generate(self, report_type: ReportType) -> bool:
        return report_type == ReportType.TYPE_A

    def generate(self, report: AttendanceReport, output_path: Path) -> None:
        _register_font()

        doc = SimpleDocTemplate(
            str(output_path),
            pagesize=A4,
            rightMargin=0.8*cm, leftMargin=0.8*cm,
            topMargin=1.5*cm,   bottomMargin=1.5*cm,
        )

        s_title = ParagraphStyle("Title", fontName=FONT_NAME, fontSize=11,
                                 leading=16, alignment=2)   # right
        s_cell  = ParagraphStyle("Cell",  fontName=FONT_NAME, fontSize=8,
                                 leading=12, alignment=1)   # centre

        elements = []

        # ── Header ────────────────────────────────────────────────────────────
        elements.append(Paragraph(_h('נ.ע. הנשר כח אדם בע"מ'), s_title))
        elements.append(Spacer(1, 0.3*cm))

        # ── Main table ─────────────────────────────────────────────────────────
        table_data: list[list[str]] = [[_h(col) for col in _HEADERS]]

        for day in report.days:
            date_str  = day.date.strftime("%d/%m/%Y")
            day_name  = _h(self._day_name(day.date.weekday()))
            location  = _h(day.location or "")

            if day.shift:
                entry  = day.shift.entry.strftime("%H:%M")
                exit_  = day.shift.exit.strftime("%H:%M")
                brk_h  = day.shift.break_minutes // 60
                brk_m  = day.shift.break_minutes % 60
                brk    = f"{brk_h:02d}:{brk_m:02d}"
                total  = _f(day.shift.total_hours())
            else:
                entry = exit_ = brk = total = ""

            if day.breakdown:
                h100 = _f(day.breakdown.hours_100)
                h125 = _f(day.breakdown.hours_125)
                h150 = _f(day.breakdown.hours_150)
                shab = _f(day.breakdown.hours_shabbat)
            else:
                h100 = h125 = h150 = shab = "0.00"

            table_data.append([
                shab, h150, h125, h100, total, brk, exit_, entry,
                location, day_name, date_str,
            ])

        # Totals row
        s = report.summary
        if s and s.breakdown:
            table_data.append([
                _f(s.breakdown.hours_shabbat),
                _f(s.breakdown.hours_150),
                _f(s.breakdown.hours_125),
                _f(s.breakdown.hours_100),
                _f(s.total_hours),
                "", "", "", "", "",
                str(s.total_days),
            ])

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
            # Bold totals row
            ("FONTNAME",       (0, -1), (-1, -1), FONT_NAME),
            ("BACKGROUND",     (0, -1), (-1, -1), _LIGHT),
        ])

        # Grey-highlight Shabbat rows
        for i, day in enumerate(report.days, start=1):
            if day.day_type == DayType.SHABBAT:
                style.add("BACKGROUND", (0, i), (-1, i), _GREY)

        tbl.setStyle(style)
        elements.append(tbl)
        elements.append(Spacer(1, 0.5*cm))

        # ── Summary box ────────────────────────────────────────────────────────
        if s:
            elements.append(self._summary_table(s))

        doc.build(elements)

    # ── helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _summary_table(s: ReportSummary) -> Table:
        rows: list[list[str]] = [
            [str(s.total_days),   _h("ימים")],
            [_f(s.total_hours),   _h('סה"כ שעות')],
        ]
        if s.breakdown:
            rows += [
                [_f(s.breakdown.hours_100),     _h("שעות 100%")],
                [_f(s.breakdown.hours_125),     _h("שעות 125%")],
                [_f(s.breakdown.hours_150),     _h("שעות 150%")],
                [_f(s.breakdown.hours_shabbat), _h("שבת 150%")],
            ]
        rows += [
            [_f(s.bonus),  _h("בונוס")],
            [_f(s.travel), _h("נסיעות")],
        ]

        tbl = Table(rows, colWidths=[3*cm, 3.5*cm], hAlign="RIGHT")
        tbl.setStyle(TableStyle([
            ("FONTNAME",   (0, 0), (-1, -1), FONT_NAME),
            ("FONTSIZE",   (0, 0), (-1, -1), 8),
            ("ALIGN",      (0, 0), (0, -1),  "CENTER"),
            ("ALIGN",      (1, 0), (1, -1),  "RIGHT"),
            ("GRID",       (0, 0), (-1, -1), 0.4, _BLACK),
            ("BACKGROUND", (0, 0), (-1, -1), _LIGHT),
        ]))
        return tbl

    @staticmethod
    def _day_name(weekday: int) -> str:
        # Python weekday(): 0=Monday … 6=Sunday
        names = [
            "יום שני", "יום שלישי", "יום רביעי", "יום חמישי",
            "יום שישי", "שבת", "יום ראשון",
        ]
        return names[weekday]
