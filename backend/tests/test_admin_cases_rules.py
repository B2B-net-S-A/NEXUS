"""Sprawy administracja@ — reguły bez bazy (SLA, obszar z tematu, wątki, treść)."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.services.admin_cases import rules
from app.services.admin_cases.mail_ingest import _header_ids, mail_source_key

_WARSAW = ZoneInfo("Europe/Warsaw")


def _at(day: date, hour: int = 10) -> datetime:
    return datetime(day.year, day.month, day.day, hour, tzinfo=_WARSAW)


@pytest.mark.parametrize(
    ("start", "priority", "expected"),
    [
        # Środa przed Wigilią: 24–26.12 wolne (Wigilia ustawowo od 2025).
        (date(2026, 12, 23), "P1", date(2026, 12, 29)),
        (date(2026, 10, 16), "P2", date(2026, 10, 23)),
        (date(2026, 10, 16), "P3", date(2026, 10, 30)),
        # 2031: Compass miał własną listę świąt kończącą się na 2030 r. i liczyłby
        # Poniedziałek Wielkanocny (14.04.2031) jako dzień roboczy.
        (date(2031, 4, 11), "P1", date(2031, 4, 16)),
    ],
)
def test_due_date_counts_business_days_with_polish_holidays(
    start: date, priority: str, expected: date
) -> None:
    assert rules.due_date_for(priority, _at(start)) == expected


def test_due_date_uses_the_company_calendar_day_not_utc() -> None:
    # 00:30 w poniedziałek w Warszawie to jeszcze niedziela w UTC; liczymy od
    # poniedziałku (od niedzieli wyszedłby wtorek 20.10).
    monday_night = datetime(2026, 10, 19, 0, 30, tzinfo=_WARSAW)
    assert rules.due_date_for("P1", monday_night) == date(2026, 10, 21)


@pytest.mark.parametrize(
    ("subject", "area"),
    [
        ("Zakończenie współpracy — zwrot sprzętu", "offboarding"),
        ("Wypowiedzenie umowy B2B", "offboarding"),
        ("Onboarding: Anna Przykładowa od 2.11", "onboarding"),
        ("Wejście nowego konsultanta", "onboarding"),
        ("RE: Aneks — nowa stawka od listopada", "negotiation"),
        ("Post na LinkedIn: kariera", "marketing"),
        ("Faktura za szkolenie BHP", "administration"),
        ("", "administration"),
        (None, "administration"),
    ],
)
def test_area_from_subject(subject, area: str) -> None:
    assert rules.area_from_subject(subject) == area


def test_case_title_strips_reply_prefixes_and_nul() -> None:
    assert rules.case_title_from_subject("RE: FW: Odp: Polisa OC") == "Polisa OC"
    assert (
        rules.case_title_from_subject("PD:\x00 Badania   okresowe")
        == "Badania okresowe"
    )
    assert rules.case_title_from_subject("   ") == "Wiadomość bez tematu"
    assert len(rules.case_title_from_subject("x" * 500)) == rules.TITLE_MAX


def test_body_to_text_drops_markup_and_keeps_lines() -> None:
    html_body = "<p>Dzień dobry,</p><p>proszę o polisę &amp; zaświadczenie.</p>\x00"
    text = rules.body_to_text(html_body, "html")
    assert "<p>" not in text
    assert "&amp;" not in text
    assert "polisę & zaświadczenie" in text
    assert "\x00" not in text
    assert rules.body_to_text("a\r\n\r\n\r\n\r\nb", "text") == "a\n\nb"


def test_normalize_checklist() -> None:
    assert rules.normalize_checklist(
        [
            {"text": " Badania ", "done": True},
            {"text": ""},
            {"text": "BHP", "done": "tak"},
        ]
    ) == [{"text": "Badania", "done": True}, {"text": "BHP", "done": False}]
    with pytest.raises(rules.ChecklistError):
        rules.normalize_checklist([{"text": "x"}] * (rules.CHECKLIST_MAX_ITEMS + 1))
    with pytest.raises(rules.ChecklistError):
        rules.normalize_checklist(["tekst bez obiektu"])


def test_thread_headers_prefer_in_reply_to_then_latest_reference() -> None:
    msg = {
        "internetMessageHeaders": [
            {"name": "References", "value": "<a@example.com> <b@example.com>"},
            {"name": "In-Reply-To", "value": "<b@example.com>"},
            {"name": "Subject", "value": "<nie-id>"},
        ]
    }
    assert _header_ids(msg) == ["<b@example.com>", "<a@example.com>"]
    assert _header_ids({}) == []


def test_mail_source_key_has_no_message_content() -> None:
    key = mail_source_key("AAMkAGI2THVSAAA=")
    assert key.startswith("mail:")
    assert "AAMk" not in key
    assert len(key) <= 200
