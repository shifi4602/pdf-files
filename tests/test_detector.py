"""Unit tests for KeywordDetector."""
import pytest
from infrastructure.detector import KeywordDetector
from models import ReportType


@pytest.fixture
def detector() -> KeywordDetector:
    return KeywordDetector()


def test_detects_type_a(detector: KeywordDetector) -> None:
    text = 'תאריך יום מקום כניסה יציאה הפסקה סה"כ 100% 125% 150% שבת נשר'
    assert detector.detect(text) == ReportType.TYPE_A


def test_detects_type_b(detector: KeywordDetector) -> None:
    text = 'שם העובד\nכרטיס עובד לחודש ספטמבר\nמחיר לשעה 30.65\nסה"כ לתשלום 2500'
    assert detector.detect(text) == ReportType.TYPE_B


def test_type_a_wins_when_more_keywords(detector: KeywordDetector) -> None:
    # Mix of keywords from both types but more from A
    text = "100% 125% 150% שבת נשר כרטיס עובד"
    assert detector.detect(text) == ReportType.TYPE_A


def test_raises_on_unknown_text(detector: KeywordDetector) -> None:
    with pytest.raises(ValueError, match="Could not detect"):
        detector.detect("hello world no hebrew keywords here")


def test_raises_on_empty_text(detector: KeywordDetector) -> None:
    with pytest.raises(ValueError):
        detector.detect("")
