"""Źródła księgi (K2) — reguły bez bazy.

Dekret faktury sprzedaży (strony, korekta in minus, odwrotne obciążenie, kurs
waluty z netto jako różnicą), konto rozrachunkowe odbiorcy, identyfikator
nabywcy, kurs faktury (z wystawienia w NEXUSIE, z faktury pierwotnej, NBP),
odcisk dokumentu i dokument FVZ z gotowego dekretu E2 (okres = dzień wpływu
w czasie firmy, faktura osoby zespołu = dokument płacowy). Kwoty fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

from app.services.finance_ledger.posting import rate_day
from app.services.ledger import sources


def _lines(**overrides):
    values = {
        "net": Decimal("1000.00"),
        "vat": Decimal("230.00"),
        "gross": Decimal("1230.00"),
        "currency": "PLN",
        "rate": Decimal("1"),
        "receivable": "200-17",
        "revenue": "701",
        "vat_account": "222",
        "counterparty_id": 5,
    }
    values.update(overrides)
    return sources.sales_lines(**values)


def _sides(lines):
    return [(line.side, line.account, line.amount) for line in lines]


def test_invoice_in_pln_debits_receivable_and_credits_revenue_and_vat():
    lines = _lines()
    assert _sides(lines) == [
        ("debit", "200-17", 123_000),
        ("credit", "701", 100_000),
        ("credit", "222", 23_000),
    ]
    assert lines[0].counterparty_id == 5
    assert lines[1].counterparty_id is None


def test_invoice_without_vat_has_no_vat_line():
    lines = _lines(vat=Decimal("0"), gross=Decimal("1000.00"))
    assert [line.account for line in lines] == ["200-17", "701"]


def test_correction_in_minus_swaps_sides_and_keeps_positive_amounts():
    lines = _lines(
        net=Decimal("-100.00"), vat=Decimal("-23.00"), gross=Decimal("-123.00")
    )
    assert _sides(lines) == [
        ("credit", "200-17", 12_300),
        ("debit", "701", 10_000),
        ("debit", "222", 2_300),
    ]


def test_foreign_invoice_converts_gross_and_vat_with_net_as_difference():
    lines = _lines(
        currency="EUR",
        rate=Decimal("4.2512"),
        vat=Decimal("0"),
        gross=Decimal("1000.00"),
    )
    assert _sides(lines) == [("debit", "200-17", 425_120), ("credit", "701", 425_120)]
    assert (lines[0].currency, lines[0].amount_cur) == ("EUR", 100_000)
    awkward = _lines(
        currency="EUR",
        rate=Decimal("4.3333"),
        net=Decimal("1000.01"),
        vat=Decimal("230.00"),
        gross=Decimal("1230.01"),
    )
    debit = sum(line.amount for line in awkward if line.side == "debit")
    credit = sum(line.amount for line in awkward if line.side == "credit")
    assert debit == credit == 533_000


def test_amounts_that_do_not_add_up_are_a_problem():
    problem = _lines(gross=Decimal("1230.01"))
    assert isinstance(problem, str) and "nie sumują się" in problem


def test_zero_correction_has_no_lines():
    assert _lines(net=Decimal("0"), vat=Decimal("0"), gross=Decimal("0")) == []


def test_receivable_account_prefers_counterparty_then_symfonia_id():
    own = SimpleNamespace(revenue_account="200-2-55", symfonia_partner_id="77")
    assert sources.receivable_account(own, "200") == "200-2-55"
    by_id = SimpleNamespace(revenue_account=None, symfonia_partner_id=" 77 ")
    assert sources.receivable_account(by_id, "200") == "200-77"
    unknown = SimpleNamespace(revenue_account=None, symfonia_partner_id="T-12")
    assert sources.receivable_account(unknown, "200") is None


def test_buyer_key_is_nip_or_eu_vat_number():
    assert sources.buyer_key(
        SimpleNamespace(buyer_nip="5260250274", buyer_foreign_id=None)
    ) == ("nip", "5260250274")
    assert sources.buyer_key(
        SimpleNamespace(buyer_nip=None, buyer_foreign_id="DE 123456789")
    ) == ("vat_eu", "DE123456789")
    # Spoza UE — tak, jak kartoteka E1 zapisuje taki identyfikator („inny”).
    assert sources.buyer_key(
        SimpleNamespace(buyer_nip=None, buyer_foreign_id="GB123456789")
    ) == ("other", "GB123456789")
    assert (
        sources.buyer_key(SimpleNamespace(buyer_nip=None, buyer_foreign_id=None))
        is None
    )


def test_advance_invoice_and_its_correction_wait_for_the_advance_rule():
    for invoice_type in ("ZAL", "KOR_ZAL"):
        invoice = SimpleNamespace(invoice_type=invoice_type)
        assert sources.sales_spec(invoice, _ctx(), None) == sources.ADVANCE


def _invoice(**overrides):
    values = {
        "id": 1,
        "currency": "EUR",
        "sale_date": date(2026, 10, 31),
        "issue_date": date(2026, 11, 3),
        "corrects_invoice_id": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _ctx(**overrides):
    values = {"counterparties": {}, "issued_rates": {}, "originals": {}, "nbp": {}}
    values.update(overrides)
    return sources._SalesContext(**values)


def test_rate_comes_from_issue_in_nexus_then_original_then_nbp():
    invoice = _invoice()
    day = rate_day(date(2026, 10, 31))
    nbp = {("EUR", day): Decimal("4.2400")}
    assert sources.invoice_rate(invoice, _ctx(nbp=nbp)) == (
        Decimal("4.2400"),
        day,
        "nbp",
    )
    issued = {1: (Decimal("4.2500"), date(2026, 10, 30))}
    assert sources.invoice_rate(invoice, _ctx(issued_rates=issued, nbp=nbp))[2] == "e4"
    correction = _invoice(id=2, issue_date=date(2026, 11, 20), corrects_invoice_id=1)
    via_original = sources.invoice_rate(
        correction, _ctx(originals={1: invoice}, issued_rates=issued)
    )
    assert via_original == (Decimal("4.2500"), date(2026, 10, 30), "original")
    by_original_day = sources.invoice_rate(
        correction, _ctx(originals={1: invoice}, nbp=nbp)
    )
    assert by_original_day == (Decimal("4.2400"), day, "original")
    missing = sources.invoice_rate(invoice, _ctx())
    assert missing[0] is None and missing[1] == day


def test_pln_invoice_needs_no_rate():
    assert sources.invoice_rate(_invoice(currency="PLN"), _ctx()) == (
        Decimal("1"),
        None,
        "pln",
    )


def _decree(**overrides):
    decree = {
        "manual": False,
        "currency": "PLN",
        "description": "Usługi IT 10/2026",
        "doc_type": "FVZ",
        "positions": [
            {"kind": "cost", "account": "402-203", "side": "debit", "amount": 100_000},
            {"kind": "vat", "account": "221", "side": "debit", "amount": 23_000},
            {
                "kind": "counterparty",
                "account": "201-2-1042",
                "side": "credit",
                "amount": 123_000,
            },
        ],
        "problems": [],
    }
    decree.update(overrides)
    return decree


def _entry(**overrides):
    values = {
        "id": 7,
        "decree": _decree(),
        "counterparty_id": 3,
        "source_type": "contractor_invoice",
        # 23:30 UTC 30.11 = 00:30 1.12 w Warszawie — wpływ w grudniu.
        "received_at": datetime(2026, 11, 30, 23, 30, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _cost_spec(entry, **overrides):
    values = {
        "number": "FV 10/2026",
        "seller": "Dostawca",
        "issue_date": date(2026, 11, 28),
        "ksef_number": None,
        "gross": Decimal("1230.00"),
        "currency": "PLN",
    }
    values.update(overrides)
    return sources.cost_spec(entry, **values)


def test_cost_document_copies_e2_decree_in_month_of_receipt():
    spec = _cost_spec(_entry())
    assert spec.doc_type == "FVZ"
    assert spec.op_date == date(2026, 12, 1)
    assert spec.doc_date == date(2026, 11, 28)
    assert _sides(spec.lines) == [
        ("debit", "402-203", 100_000),
        ("debit", "221", 23_000),
        ("credit", "201-2-1042", 123_000),
    ]
    assert [line.counterparty_id for line in spec.lines] == [None, None, 3]
    assert (spec.source_type, spec.source_id) == ("finance_cost_entry", "7")
    assert spec.sensitivity is None


def test_team_member_invoice_is_a_payroll_document():
    spec = _cost_spec(_entry(source_type="payroll_invoice"))
    assert spec.sensitivity == "payroll"


def test_foreign_cost_needs_rate_from_decree():
    missing = _cost_spec(_entry(decree=_decree(currency="EUR")), currency="EUR")
    assert isinstance(missing, str) and "kursu NBP" in missing
    spec = _cost_spec(
        _entry(
            decree=_decree(currency="EUR", fx_rate="4.25", fx_date="2026-11-27")
        ),
        currency="EUR",
    )
    assert spec.fx_rate == Decimal("4.25") and spec.fx_date == date(2026, 11, 27)
    assert (spec.lines[2].currency, spec.lines[2].amount_cur) == ("EUR", 123_000)


def test_unreadable_rate_in_manual_decree_is_a_problem_not_an_error():
    for rate, day in (("abc", "2026-11-27"), ("4.25", "27.11.2026"), ("-1", "2026-11-27")):
        problem = _cost_spec(
            _entry(decree=_decree(currency="EUR", fx_rate=rate, fx_date=day)),
            currency="EUR",
        )
        assert isinstance(problem, str) and "nieczytelny" in problem


def test_cost_without_decree_is_a_problem():
    assert isinstance(_cost_spec(_entry(decree={"positions": []})), str)


def test_fingerprint_follows_amounts_and_dates():
    spec = _cost_spec(_entry())
    same = _cost_spec(_entry())
    assert sources.fingerprint(spec) == sources.fingerprint(same)
    changed = _cost_spec(
        _entry(
            decree=_decree(
                positions=[
                    {
                        "kind": "cost",
                        "account": "402-203",
                        "side": "debit",
                        "amount": 100_001,
                    },
                    {
                        "kind": "counterparty",
                        "account": "201-2-1042",
                        "side": "credit",
                        "amount": 100_001,
                    },
                ]
            )
        )
    )
    assert sources.fingerprint(changed) != sources.fingerprint(spec)
    later = _cost_spec(_entry(received_at=datetime(2026, 12, 2, 9, tzinfo=timezone.utc)))
    assert sources.fingerprint(later) != sources.fingerprint(spec)
