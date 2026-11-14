"""Automaty księgi (K3a) — harmonogram bez bazy: raty RMK z resztą w ostatniej,
granice miesięcy wzoru PK, źródło miesiąca. Kwoty i konta fikcyjne."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.ledger import automations


def test_installments_sum_to_total_with_remainder_last():
    rates = [automations.installment(100_000, 3, n) for n in (1, 2, 3)]
    assert rates == [33_333, 33_333, 33_334] and sum(rates) == 100_000
    assert automations.installment(5_000, 1, 1) == 5_000


def test_month_index_and_last_day():
    assert automations.month_index(date(2026, 11, 1), date(2027, 2, 1)) == 3
    assert automations.last_day(date(2028, 2, 1)) == date(2028, 2, 29)


def _template(**values):
    data = {
        "id": 7,
        "name": "Najem biura",
        "description": "",
        "active": True,
        "start_month": date(2026, 3, 1),
        "end_month": date(2026, 5, 1),
        "lines": [
            {"side": "debit", "account": "402-215", "amount": 100_000, "mpk": "OG"},
            {"side": "credit", "account": "201-2-17", "amount": 100_000, "counterparty_id": 4},
        ],
    }
    data.update(values)
    return SimpleNamespace(**data)


def test_recurring_posts_only_inside_its_months():
    template = _template()
    assert automations.recurring_spec(template, date(2026, 2, 1)) is None
    assert automations.recurring_spec(template, date(2026, 6, 1)) is None
    assert automations.recurring_spec(_template(active=False), date(2026, 4, 1)) is None
    spec = automations.recurring_spec(template, date(2026, 4, 1))
    assert spec.op_date == date(2026, 4, 30)
    assert (spec.source_type, spec.source_id) == ("ledger_recurring", "7:2026-04")
    assert [(l.side, l.account, l.amount, l.mpk, l.counterparty_id) for l in spec.lines] == [
        ("debit", "402-215", 100_000, "OG", None),
        ("credit", "201-2-17", 100_000, None, 4),
    ]
    open_ended = automations.recurring_spec(_template(end_month=None), date(2030, 1, 1))
    assert open_ended is not None


def _prepayment(**values):
    data = {
        "id": 3,
        "name": "Polisa OC",
        "reference": "PL-1",
        "active": True,
        "cost_account": "402-901",
        "prepaid_account": "640",
        "mpk": None,
        "counterparty_id": None,
        "total_amount": 100_000,
        "start_month": date(2026, 11, 1),
        "months": 3,
    }
    data.update(values)
    return SimpleNamespace(**data)


def test_prepayment_installments_follow_schedule():
    item = _prepayment()
    assert automations.prepayment_spec(item, date(2026, 10, 1)) is None
    assert automations.prepayment_spec(item, date(2027, 2, 1)) is None
    first = automations.prepayment_spec(item, date(2026, 11, 1))
    last = automations.prepayment_spec(item, date(2027, 1, 1))
    assert [(l.side, l.account, l.amount) for l in first.lines] == [
        ("debit", "402-901", 33_333),
        ("credit", "640", 33_333),
    ]
    assert last.lines[0].amount == 33_334
    assert "rata 3/3" in last.description and "PL-1" in last.description
    assert last.source_id == "3:2027-01"
