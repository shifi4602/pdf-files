from __future__ import annotations

from interfaces import IDetector
from models import ReportType

# Signature keywords for each type.
# Type A (נשר כח אדם): contains overtime-rate column headers.
# Type B (כרטיס עובד): contains salary-summary labels.
_TYPE_A_KEYWORDS: list[str] = ["100%", "125%", "150%", "שבת", "נשר"]
_TYPE_B_KEYWORDS: list[str] = ["מחיר לשעה", 'סה"כ לתשלום', "כרטיס עובד", "יום שעת"]


class KeywordDetector(IDetector):
    """
    Detects report type by counting how many signature keywords appear
    in the extracted text.  The type with the higher score wins.

    Design rationale (interview note):
    - Simple, transparent, zero false-magic — every decision is traceable
      to a keyword match.
    - Scores are additive so partial OCR noise doesn't flip the result.
    - Raises ValueError when neither type is recognisable, so callers
      can surface a clear error instead of silently producing wrong output.
    """

    def detect(self, text: str) -> ReportType:
        score_a = sum(1 for kw in _TYPE_A_KEYWORDS if kw in text)
        score_b = sum(1 for kw in _TYPE_B_KEYWORDS if kw in text)

        if score_a == 0 and score_b == 0:
            raise ValueError(
                "Could not detect report type — no known keywords found in the PDF.\n"
                "Make sure the file is not encrypted or a low-quality scan."
            )

        return ReportType.TYPE_A if score_a >= score_b else ReportType.TYPE_B
