"""Zapłaty z eBI24 — czyste reguły (bez bazy): odczyt nagłówka, decyzja, pierwszeństwo NEXUSA.

Kształt nagłówka z pomiaru na UAT 12.11.2026: ``paid`` jest w nagłówku
``bucket/index``, kwoty w groszach, daty ``RRRR-MM-DDT…``. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.services.client_invoicing import ebi24_payments as ep
from app.services.client_invoicing import payments
from app.services.client_invoicing.ledger import Chain

TODAY = date(2026, 11, 20)
KSEF = "5260000000-20261103-0100A1B2C3D4-E5"


def _header(**extra: object) -> dict[str, object]:
    return {
        "_id": "6af5cb4eb422eb0f0c4e6eb2",
        "_ksefReferenceNumber": KSEF,
        "grossAmount": 1230000,
        "paid": False,
        **extra,
    }


def _paid(**extra: object) -> ep.Ebi24Paid:
    found = ep.read_header(_header(**extra))
    assert found is not None
    return found


def _chain(*payments: SimpleNamespace, paid_in_invoice_on: date | None = None) -> Chain:
    head = SimpleNamespace(
        id=1,
        gross_amount=Decimal("12300.00"),
        net_amount=Decimal("10000.00"),
        paid_in_invoice_on=paid_in_invoice_on,
        currency="PLN",
        ksef_number=KSEF,
        invoice_number="FS 11/1/2026",
    )
    return Chain(head=head, payments=list(payments))  # type: ignore[arg-type]


def _payment(kind: str, amount: str) -> SimpleNamespace:
    return SimpleNamespace(
        kind=kind, amount=Decimal(amount), match_status="matched", reason=None
    )


# ── Odczyt nagłówka ──────────────────────────────────────────────────────────


def test_header_paid_in_full_takes_gross_in_zloty():
    found = _paid(paid=True, paidDate="2026-11-14T00:00:00.000")
    assert (found.value, found.paid_on, found.ksef_number) == (
        Decimal("12300.00"),
        date(2026, 11, 14),
        KSEF,
    )


def test_header_partial_payment_uses_paid_amount():
    found = _paid(paid=False, paidAmount=500000)
    assert found.value == Decimal("5000.00")


def test_header_unpaid_has_no_value():
    assert _paid().value is None


def test_header_rejects_bad_values_instead_of_guessing():
    assert ep.read_header({"_id": None}) is None
    assert ep.read_header({"_id": "x" * 33}) is None
    found = _paid(paid=True, grossAmount="12300", paidAmount=True, paidDate="wczoraj")
    assert (found.gross, found.paid_amount, found.paid_on) == (None, None, None)
    assert found.value is None
    assert _paid(paidAmount=-5).paid_amount is None
    assert _paid(_ksefReferenceNumber="  ").ksef_number is None


# ── Decyzja ──────────────────────────────────────────────────────────────────


def test_new_payment_is_created_with_today_when_date_missing():
    decision = ep.decide(_paid(paid=True), None, recorded_elsewhere=False, today=TODAY)
    assert (decision.action, decision.amount, decision.booked_on) == (
        "create",
        Decimal("12300.00"),
        TODAY,
    )


def test_same_state_twice_changes_nothing():
    existing = ep.Existing(Decimal("12300.00"), date(2026, 11, 14), "matched")
    decision = ep.decide(
        _paid(paid=True, paidDate="2026-11-14"),
        existing,
        recorded_elsewhere=False,
        today=TODAY,
    )
    assert decision.action == "keep"


def test_larger_partial_payment_updates_the_mirror():
    existing = ep.Existing(Decimal("5000.00"), date(2026, 11, 10), "matched")
    decision = ep.decide(
        _paid(paidAmount=800000), existing, recorded_elsewhere=False, today=TODAY
    )
    assert (decision.action, decision.amount, decision.booked_on) == (
        "update",
        Decimal("8000.00"),
        date(2026, 11, 10),
    )


def test_payment_withdrawn_in_ebi24_is_revoked_with_reason():
    existing = ep.Existing(Decimal("12300.00"), date(2026, 11, 14), "matched")
    decision = ep.decide(_paid(), existing, recorded_elsewhere=False, today=TODAY)
    assert (decision.action, decision.reason) == ("revoke", ep.REVOKED)
    assert (
        ep.decide(_paid(), None, recorded_elsewhere=False, today=TODAY).action == "skip"
    )


def test_revoked_mirror_comes_back_when_ebi24_marks_paid_again():
    existing = ep.Existing(Decimal("12300.00"), date(2026, 11, 14), "ignored")
    decision = ep.decide(
        _paid(paid=True, paidDate="2026-11-18"),
        existing,
        recorded_elsewhere=False,
        today=TODAY,
    )
    assert (decision.action, decision.booked_on) == ("update", date(2026, 11, 18))


def test_nexus_record_wins_over_ebi24():
    existing = ep.Existing(Decimal("12300.00"), date(2026, 11, 14), "matched")
    paid = _paid(paid=True)
    assert ep.decide(
        paid, existing, recorded_elsewhere=True, today=TODAY
    ) == ep.Decision("revoke", reason=ep.SUPERSEDED)
    assert ep.decide(paid, None, recorded_elsewhere=True, today=TODAY).action == "skip"


def test_recorded_in_nexus_ignores_the_ebi24_mirror_itself():
    assert not ep.recorded_in_nexus(_chain(_payment("ebi24", "12300.00")))
    assert ep.recorded_in_nexus(_chain(_payment("statement_line", "100.00")))
    assert ep.recorded_in_nexus(_chain(_payment("manual", "100.00")))
    assert ep.recorded_in_nexus(_chain(paid_in_invoice_on=date(2026, 11, 3)))


# ── Wyciąg ma pierwszeństwo ──────────────────────────────────────────────────


def test_statement_matching_does_not_see_ebi24_payment_as_paid():
    chain = _chain(_payment("ebi24", "12300.00"))
    assert chain.to_pay == Decimal("0.00")
    assert payments.own_to_pay(chain) == Decimal("12300.00")
    assert payments.open_invoice(chain).to_pay == Decimal("12300.00")


def test_supersede_ebi24_leaves_only_nexus_payments():
    mirror = _payment("ebi24", "12300.00")
    statement = _payment("statement_line", "12300.00")
    chain = _chain(mirror, statement)
    assert payments.supersede_ebi24(chain) == 1
    assert (mirror.match_status, mirror.reason) == ("ignored", ep.SUPERSEDED)
    assert chain.payments == [statement]
    assert chain.payment_status == "paid"


def test_criteria_filters_income_invoices_by_issue_date():
    found = ep.criteria(date(2026, 5, 24))
    assert found["criteria"] == [
        {"fieldName": "_schemaName", "operator": "equals", "value": "INCOME_INVOICE"},
        {
            "fieldName": "issuedDate",
            "operator": "greaterOrEqual",
            "value": "2026-05-24",
        },
    ]
