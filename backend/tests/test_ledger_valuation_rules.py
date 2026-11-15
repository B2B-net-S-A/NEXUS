"""Wycena walut na koniec miesiąca (K4c-2) — reguły bez bazy.

Kwoty w groszach/centach, konta i kursy fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.ledger import closing, settlements, valuation


def _item(
    line_id: int, direction: str, pln: int, cur: int | None, **extra
) -> settlements.Item:
    values = {
        "line_id": line_id,
        "document_id": line_id,
        "line_no": 1,
        "account": "200-15",
        "direction": direction,
        "value": pln,
        "used": 0,
        "doc_type": "FVS",
        "number": f"FS {line_id}",
        "op_date": date(2026, 3, 10),
        "description": "",
        "due_on": None,
        "currency": "EUR" if cur is not None else "PLN",
        "amount_cur": cur,
        "counterparty_id": 7,
        "sensitivity": None,
        "source_type": None,
        "source_id": None,
    }
    values.update(extra)
    return settlements.Item(**values)


RATES = {"EUR": (Decimal("4.4"), date(2026, 3, 31))}


def test_month_end_and_key():
    assert valuation.month_end(2026, 2) == date(2026, 2, 28)
    assert valuation.month_end(2028, 2) == date(2028, 2, 29)
    assert valuation.key(2026, 3) == "2026-03"


def test_open_currency_items_are_valued_net_per_account_without_payroll():
    items = [
        _item(1, "debit", 215_000, 50_000),  # należność 500 EUR po 4,30
        _item(2, "credit", 85_000, 20_000),  # nadpłata 200 EUR po 4,25
        _item(3, "debit", 10_000, None),  # PLN — poza wyceną
        _item(4, "debit", 43_000, 10_000, sensitivity="payroll"),  # D2 — poza wyceną
        _item(5, "debit", 215_000, 50_000, used=215_000),  # rozliczona
    ]
    [position] = valuation.settlement_positions(items, RATES)
    assert (position.account, position.amount_cur, position.book) == (
        "200-15",
        30_000,
        130_000,
    )
    # 300 EUR × 4,40 = 1 320,00 → +20,00 (dodatnia: Wn konto).
    assert (position.valued, position.diff) == (132_000, 2_000)


def test_valuation_lines_aggregate_gains_and_losses():
    up = valuation.Position(
        "200-15", "settlement", "EUR", 50_000, 215_000, Decimal("4.4"), 7
    )
    down = valuation.Position(
        "201-2-9", "settlement", "EUR", -10_000, -42_000, Decimal("4.4"), 8
    )
    bank = valuation.Position("131-1", "bank", "EUR", 10_000, 42_500, Decimal("4.4"))
    lines = valuation.valuation_lines(
        [up, down, bank], gain="750", loss="751", text_="Wycena"
    )
    assert [(line.side, line.account, line.amount) for line in lines] == [
        ("debit", "200-15", 5_000),  # 2 200,00 − 2 150,00
        ("credit", "201-2-9", 2_000),  # zobowiązanie wzrosło do 440,00
        ("debit", "131-1", 1_500),  # 440,00 − 425,00
        ("credit", "750", 6_500),
        ("debit", "751", 2_000),
    ]
    assert sum(l.amount for l in lines if l.side == "debit") == sum(
        l.amount for l in lines if l.side == "credit"
    )
    back = valuation.reversed_lines(lines)
    assert [(line.side, line.account) for line in back][:2] == [
        ("credit", "200-15"),
        ("debit", "201-2-9"),
    ]
    assert (
        valuation.valuation_lines(
            [
                valuation.Position(
                    "200-15", "settlement", "EUR", 50_000, 220_000, Decimal("4.4")
                )
            ],
            gain="750",
            loss="751",
            text_="x",
        )
        == []
    )


def test_closing_item_for_valuation():
    href = "/accounting/settlements?year=2026&month=12"
    base = {"positions": [{"account": "200-15"}], "documents": {"valuation": None}}
    assert closing.valuation_check({**base, "positions": []}, href) is None
    december = closing.valuation_check({**base, "month": 12}, href)
    assert (december["state"], december["detail"]) == (
        "todo",
        "wycena na dzień bilansowy (art. 30 ust. 1 UoR)",
    )
    october = closing.valuation_check({**base, "month": 10}, href)
    assert october["state"] == "ok" and "opcjonalna" in october["detail"]
    draft = closing.valuation_check(
        {
            **base,
            "month": 10,
            "documents": {"valuation": {"number": "PK 9/10/2026", "status": "draft"}},
        },
        href,
    )
    assert (draft["state"], draft["detail"]) == ("todo", "PK 9/10/2026 w buforze")
