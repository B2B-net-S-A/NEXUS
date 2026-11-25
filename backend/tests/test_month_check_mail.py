"""Kontrola miesiąca (0784): terminy i treść maili do Finansów, pętla raz na dzień.

Bez bazy; osoby, klienci, numery faktur i kwoty zmyślone.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services import notification_delivery as delivery
from app.services.month_check import mail
from app.tasks import month_check as loop

WAW = ZoneInfo("Europe/Warsaw")


def test_weekly_mail_on_monday_from_eight():
    assert mail.weekly_key(datetime(2026, 11, 30, 8, 5, tzinfo=WAW)) == "2026-W49"
    assert mail.weekly_key(datetime(2026, 11, 30, 7, 59, tzinfo=WAW)) is None
    assert mail.weekly_key(datetime(2026, 12, 1, 9, 0, tzinfo=WAW)) is None


def test_summary_on_the_twelfth_for_previous_month():
    assert mail.summary_key(datetime(2026, 12, 12, 8, 0, tzinfo=WAW)) == "2026-11"
    assert mail.summary_key(datetime(2027, 1, 12, 10, 0, tzinfo=WAW)) == "2026-12"
    assert mail.summary_key(datetime(2026, 12, 11, 10, 0, tzinfo=WAW)) is None


def test_weekly_text_has_amounts_invoices_and_link():
    rows = [
        {
            "month": "2026-10",
            "client": "Klient Zmyślony",
            "person": "Jan Przykładowy",
            "kind_label": "Inne godziny u klienta i u konsultanta",
            "amount": "-1234.50",
            "details": {
                "sales_invoices": ["FS/1/11/2026"],
                "contractor_invoices": [{"number": "K/10/2026"}],
            },
        }
    ]
    subject, text = mail.render_weekly(rows, "2026-W49")
    assert "2026-W49" in subject
    assert "−1 234,50 zł" in text
    assert "FS/1/11/2026" in text and "K/10/2026" in text
    assert "mcMonth=2026-10&mcTab=diff" in text


def test_mail_kind_is_required_and_in_catalog():
    assert mail.KIND in delivery.REQUIRED_KINDS
    assert mail.KIND in delivery.ROUTINE_KINDS
    assert mail.KIND in delivery.REPORT_KINDS


def test_loop_runs_once_a_day_after_three():
    morning = datetime(2026, 11, 26, 4, 0, tzinfo=WAW)
    assert loop.due(None, morning)
    assert not loop.due("2026-11-26T02:10:00+00:00", morning)
    assert loop.due("2026-11-25T02:10:00+00:00", morning)
    assert not loop.due(None, datetime(2026, 11, 26, 2, 0, tzinfo=WAW))
