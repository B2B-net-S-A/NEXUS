"""Rozrachunki (K4b) — reguły bez bazy: konta kontrahentów, wiekowanie, pary.

Kwoty w groszach, daty i konta fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.ledger import bank, closing, settlements
from app.services.ledger.engine import PlanAccount
from app.models.ledger import LedgerBankLine, LedgerBankStatement


def _item(
    line_id: int, direction: str, value: int, day: int, **extra
) -> settlements.Item:
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
    left = settlements.Left.of([*invoices, *payments])
    pairs = settlements.fifo(invoices, payments, left, method="manual")
    assert [(p.debit.line_id, p.credit.line_id, p.amount) for p in pairs] == [
        (2, 3, 30_000),
        (1, 3, 30_000),
    ]
    assert left.pln == {1: 20_000, 2: 0, 3: 0}
    # Pozycja już rozliczona (zostało 0) nie bierze udziału.
    assert settlements.fifo(invoices, payments, left, method="manual") == []


def test_closing_item_asks_to_run_the_automat():
    href = "/accounting/settlements?year=2026&month=3"
    idle = closing.settlements_check({"bank": 0, "correction": 0, "zero": 0}, href)
    assert (idle["state"], idle["detail"]) == (
        "ok",
        "automat nie ma nic do rozliczenia",
    )
    busy = closing.settlements_check({"bank": 3, "correction": 0, "zero": 1}, href)
    assert busy["state"] == "todo"
    assert (
        busy["detail"] == "automat rozliczy pozycje: 4 (z wyciągów 3, salda zerowe 1)"
    )
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


# ── Waluty (K4c-1) ──────────────────────────────────────────────────────────


def _cur(line_id: int, direction: str, pln: int, cur: int, day: int = 10, **extra):
    return _item(line_id, direction, pln, day, currency="EUR", amount_cur=cur, **extra)


def test_share_is_proportional_and_the_last_part_takes_the_rest():
    assert settlements.share(215_000, 50_000, 50_000) == 215_000
    assert settlements.share(215_000, 50_000, 20_000) == 86_000
    # Zaokrąglenie połowy w górę, jak przeliczenia na PLN w E2 i K2.
    assert settlements.share(1_000, 3, 1) == 333
    assert settlements.share(1_001, 2, 1) == 501


def test_terms_settle_currency_pairs_in_currency_with_the_fx_difference():
    invoice = _cur(1, "debit", 215_000, 50_000)  # 500 EUR po 4,30
    payment = _cur(2, "credit", 212_500, 50_000, day=25)  # 500 EUR po 4,25
    left = settlements.Left.of([invoice, payment])
    full = settlements.terms(invoice, payment, left, method="bank")
    assert (full.amount, full.credit_share, full.amount_cur) == (
        215_000,
        212_500,
        50_000,
    )
    assert full.fx == 2_500 and full.currency == "EUR"
    assert full.settled_on == date(2026, 3, 25)
    part = settlements.terms(
        invoice,
        _cur(3, "credit", 85_000, 20_000),
        settlements.Left.of([invoice, _cur(3, "credit", 85_000, 20_000)]),
        method="manual",
    )
    # 200 EUR z 500: udział faktury 860,00, wpłata 850,00 → różnica 10,00.
    assert (part.amount, part.credit_share, part.amount_cur, part.fx) == (
        86_000,
        85_000,
        20_000,
        1_000,
    )
    settlements.take(left, full)
    assert (left.pln, left.cur) == ({1: 0, 2: 0}, {1: 0, 2: 0})


def test_terms_settle_a_currency_invoice_paid_in_pln_in_pln():
    invoice = _cur(1, "debit", 215_000, 50_000)
    pln_payment = _item(2, "credit", 107_500, 20)
    left = settlements.Left.of([invoice, pln_payment])
    mixed = settlements.terms(invoice, pln_payment, left, method="manual")
    # Połowa PLN faktury = połowa waluty; bez różnicy kursowej.
    assert (mixed.amount, mixed.credit_share, mixed.amount_cur, mixed.fx) == (
        107_500,
        107_500,
        25_000,
        0,
    )
    settlements.take(left, mixed)
    assert (left.pln[1], left.cur[1], left.pln[2]) == (107_500, 25_000, 0)
    usd = _item(3, "credit", 100_000, 20, currency="USD", amount_cur=25_000)
    assert (
        settlements.terms(
            invoice, usd, settlements.Left.of([invoice, usd]), method="manual"
        )
        is None
    )


def test_fx_document_needs_its_account_and_an_open_month():
    loss = settlements.Proposal(
        _cur(1, "debit", 215_000, 50_000),
        _cur(2, "credit", 212_500, 50_000),
        215_000,
        "bank",
        amount_cur=50_000,
        credit_amount=212_500,
    )
    gain = settlements.Proposal(
        _cur(1, "debit", 212_500, 50_000),
        _cur(2, "credit", 215_000, 50_000),
        212_500,
        "bank",
        amount_cur=50_000,
        credit_amount=215_000,
    )
    march = frozenset({(2026, 3)})
    ready = settlements.FxContext("750-1", "751-1", march)
    assert ready.blocker(loss) is None and ready.blocker(gain) is None
    assert "ujemnych" in settlements.FxContext("750-1", "", march).blocker(loss)
    assert "dodatnich" in settlements.FxContext("", "751-1", march).blocker(gain)
    assert "zamknięty okres 03.2026" in settlements.FxContext(
        "750-1", "751-1", frozenset()
    ).blocker(loss)
    even = settlements.Proposal(
        loss.debit,
        loss.credit,
        215_000,
        "bank",
        amount_cur=50_000,
        credit_amount=215_000,
    )
    assert settlements.FxContext().blocker(even) is None


def test_statement_file_has_one_currency_of_the_company_accounts():
    from app.services.finance_ledger.costs import LedgerError
    from app.services.hr.bank.parsed import ParsedStatement, StatementLine

    def line(currency: str) -> StatementLine:
        return StatementLine(
            index=1,
            booked_on=date(2026, 3, 2),
            amount=Decimal("10.00"),
            direction="credit",
            currency=currency,
            title="",
            counterparty_name="",
            counterparty_account=None,
            bank_ref="R1",
        )

    def parsed(currency: str, *lines: StatementLine) -> ParsedStatement:
        return ParsedStatement(
            format="mt940", account=None, currency=currency, lines=lines
        )

    assert bank.file_currency(parsed("EUR", line("EUR")), (line("EUR"),)) == "EUR"
    for header, lines, message in (
        ("PLN", (line("PLN"), line("EUR")), "kilku walutach"),
        ("GBP", (line("GBP"),), "rachunki firmy są w PLN, EUR, USD"),
    ):
        try:
            bank.file_currency(parsed(header, *lines), lines)
        except LedgerError as exc:
            assert exc.status == 422 and message in exc.message
        else:  # pragma: no cover
            raise AssertionError("plik powinien być odrzucony")


def test_currency_wb_lines_carry_pln_currency_and_their_rate():
    statement = LedgerBankStatement(
        id=8,
        bank_account="61109010140000071219812876",
        ledger_account="131-1",
        currency="EUR",
        first_day=date(2026, 3, 25),
        last_day=date(2026, 3, 25),
    )
    line = LedgerBankLine(
        id=201,
        booked_on=date(2026, 3, 25),
        direction="credit",
        amount=50_000,
        currency="EUR",
        amount_pln=212_500,
        fx_rate=Decimal("4.25"),
        fx_date=date(2026, 3, 24),
        counter_account="200-15",
        counterparty_name="Klient",
        title="",
    )
    spec = bank.wb_spec(statement, [line], payroll=False)
    assert [(item.side, item.account, item.amount) for item in spec.lines] == [
        ("debit", "131-1", 212_500),
        ("credit", "200-15", 212_500),
    ]
    assert {
        (item.currency, item.amount_cur, item.fx_rate, item.fx_date)
        for item in spec.lines
    } == {("EUR", 50_000, Decimal("4.25"), date(2026, 3, 24))}


def test_pln_document_fingerprint_is_the_same_as_before_line_rates():
    """Kursy pozycji (K4c-1) wchodzą do odcisku tylko, gdy są — odciski dokumentów
    w PLN (zatwierdzone WB, FVS, FVZ) zostają te same, inaczej K2 pokazałby
    zatwierdzone dokumenty jako zmienione źródła."""

    import hashlib
    import json

    from app.services.ledger import sources
    from app.services.ledger.documents import DocumentSpec
    from app.services.ledger.engine import LineIn

    spec = DocumentSpec(
        doc_type="WB",
        op_date=date(2026, 3, 20),
        doc_date=date(2026, 3, 20),
        lines=[
            LineIn("debit", "130-1", 1_000, "x"),
            LineIn("credit", "200-15", 1_000, "x", counterparty_id=7),
        ],
        description="Wyciąg",
        source_type="bank_statement",
        source_id="1",
    )
    before = {
        "type": "WB",
        "number": None,
        "op_date": "2026-03-20",
        "doc_date": "2026-03-20",
        "description": "Wyciąg",
        "counterparty": None,
        "currency": "PLN",
        "fx_rate": None,
        "fx_date": None,
        "sensitivity": None,
        "lines": [
            ["debit", "130-1", 1_000, None, None, "PLN", None],
            ["credit", "200-15", 1_000, 7, None, "PLN", None],
        ],
    }
    raw = json.dumps(before, sort_keys=True, ensure_ascii=False)
    assert (
        sources.fingerprint(spec)
        == hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    )
