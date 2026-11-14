"""Rozrachunki (K4b) — reguły bez bazy: konta kontrahentów, wiekowanie, pary.

Kwoty w groszach, daty i konta fikcyjne.
"""

from __future__ import annotations

from datetime import date

from app.services.ledger import bank, closing, settlements
from app.services.ledger.engine import PlanAccount
from app.models.ledger import LedgerBankLine, LedgerBankStatement


def _item(line_id: int, direction: str, value: int, day: int, **extra) -> settlements.Item:
    values = {
        "line_id": line_id,
        "document_id": line_id,
        "line_no": 1,
        "account": "200-15",
        "direction": direction,
        "value": value,
        "used": 0,
        "doc_type": "FVS" if direction == "debit" else "WB",
        "number": f"FS {line_id}/2026",
        "op_date": date(2026, 3, day),
        "description": "",
        "due_on": None,
        "currency": "PLN",
        "amount_cur": None,
        "counterparty_id": None,
        "sensitivity": None,
        "source_type": None,
        "source_id": None,
    }
    values.update(extra)
    return settlements.Item(**values)


def test_counterparty_dictionary_accounts_are_settlement_accounts():
    plan = {
        "200": PlanAccount("200", "Odbiorcy", "settlement", True, "counterparty"),
        "201-2": PlanAccount("201-2", "Dostawcy", "settlement", True, "counterparty"),
        "202": PlanAccount("202", "Stare", "settlement", False, "counterparty"),
        "229": PlanAccount("229", "ZUS", "other", True, None),
        "240": PlanAccount("240", "Urzędy", "other", True, "tax_office"),
    }
    parents = settlements.settlement_parents(plan)
    assert parents == ("200", "201-2")
    assert settlements.is_settlement_account("200-1234", parents)
    assert settlements.is_settlement_account("201-2-15", parents)
    assert not settlements.is_settlement_account("200", parents)
    assert not settlements.is_settlement_account("2001-5", parents)
    assert not settlements.is_settlement_account("202-7", parents)
    assert not settlements.is_settlement_account("240-1", parents)


def test_aging_buckets_count_days_after_the_due_date():
    as_of = date(2026, 12, 31)
    assert settlements.aging_key(None, as_of) == "none"
    assert settlements.aging_key(date(2027, 1, 10), as_of) == "current"
    assert settlements.aging_key(as_of, as_of) == "current"
    assert settlements.aging_key(date(2026, 12, 30), as_of) == "d30"
    assert settlements.aging_key(date(2026, 12, 1), as_of) == "d30"
    assert settlements.aging_key(date(2026, 11, 30), as_of) == "d60"
    assert settlements.aging_key(date(2026, 10, 2), as_of) == "d90"
    assert settlements.aging_key(date(2026, 7, 4), as_of) == "d180"
    assert settlements.aging_key(date(2026, 1, 1), as_of) == "d365"
    assert settlements.aging_key(date(2025, 12, 31), as_of) == "d365"
    assert settlements.aging_key(date(2025, 12, 30), as_of) == "over"
    assert settlements.overdue_days(None, as_of) == 0
    assert settlements.overdue_days(date(2027, 1, 5), as_of) == 0
    assert settlements.overdue_days(date(2026, 12, 21), as_of) == 10


def test_fifo_pairs_oldest_items_first_and_keeps_the_rest_open():
    invoices = [_item(1, "debit", 50_000, 10), _item(2, "debit", 30_000, 5)]
    payments = [_item(3, "credit", 60_000, 20)]
    left = {item.line_id: item.value for item in [*invoices, *payments]}
    pairs = settlements.fifo(invoices, payments, left)
    assert [(debit.line_id, credit.line_id, amount) for debit, credit, amount in pairs] == [
        (2, 3, 30_000),
        (1, 3, 30_000),
    ]
    assert left == {1: 20_000, 2: 0, 3: 0}
    # Pozycja już rozliczona (zostało 0) nie bierze udziału.
    assert settlements.fifo(invoices, payments, left) == []


def test_closing_item_asks_to_run_the_automat():
    href = "/accounting/settlements?year=2026&month=3"
    idle = closing.settlements_check({"bank": 0, "correction": 0, "zero": 0}, href)
    assert (idle["state"], idle["detail"]) == ("ok", "automat nie ma nic do rozliczenia")
    busy = closing.settlements_check({"bank": 3, "correction": 0, "zero": 1}, href)
    assert busy["state"] == "todo"
    assert busy["detail"] == "automat rozliczy pozycje: 4 (z wyciągów 3, salda zerowe 1)"
    assert busy["href"] == href


def test_wb_remembers_which_line_is_which_bank_operation():
    statement = LedgerBankStatement(
        id=7,
        bank_account="61109010140000071219812875",
        ledger_account="130-1",
        first_day=date(2026, 3, 2),
        last_day=date(2026, 3, 20),
    )
    lines = [
        LedgerBankLine(
            id=101,
            booked_on=date(2026, 3, 2),
            direction="debit",
            amount=10_000,
            counter_account="201-2-15",
            counterparty_name="Dostawca",
            title="",
        ),
        LedgerBankLine(
            id=102,
            booked_on=date(2026, 3, 3),
            direction="credit",
            amount=20_000,
            counter_account="200-15",
            counterparty_name="Klient",
            title="",
        ),
    ]
    spec = bank.wb_spec(statement, lines, payroll=False)
    # Obciążenie: konto przeciwstawne pierwsze (Wn), uznanie: drugie (Ma).
    assert spec.meta["bank_lines"] == {"1": 101, "4": 102}
    assert spec.lines[0].account == "201-2-15" and spec.lines[0].side == "debit"
    assert spec.lines[3].account == "200-15" and spec.lines[3].side == "credit"
