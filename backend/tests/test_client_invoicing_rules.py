"""Faktury do klientów (E8) — czyste reguły: dopasowanie faktury, wpłaty, część miesiąca.

Bez bazy. Numery zamówień, faktur i KSeF fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.client_invoicing.billing import (
    BillingLine,
    BillingRow,
    OrderRef,
    period_fraction,
)
from app.services.client_invoicing.matching import Target, decide, numbers_found
from app.services.client_invoicing.payments import (
    OpenInvoice,
    decide_credit,
    mpp_vat,
)
from app.services.hr.bank.parsed import StatementLine

KSEF_A = "9876543210-20261103-A1180C0FFEE1-5C"


def _line(order_id, net, consultant="Jan Przykładowy"):
    return BillingLine(
        order_id=order_id,
        consultant=consultant,
        basis="md",
        quantity=Decimal("1"),
        unit_price=Decimal("1"),
        net=None if net is None else Decimal(net),
        currency="PLN",
    )


def _group(group_id, number, *lines):
    return BillingRow(
        client_id=1,
        kind="md",
        group_id=group_id,
        order_id=None,
        order_number=number,
        currency="PLN",
        lines=tuple(lines),
    )


def _periodic(order_id, number, net, currency="PLN"):
    return BillingRow(
        client_id=1,
        kind="periodic",
        group_id=None,
        order_id=order_id,
        order_number=number,
        currency=currency,
        lines=(_line(order_id, net),),
    )


def _refs(*rows):
    return [OrderRef(1, row.group_id, row.order_id, row.order_number) for row in rows]


# ── Numer zamówienia w treści faktury ─────────────────────────────────────────


def test_order_number_is_found_as_a_whole_word_only():
    refs = [OrderRef(1, 10, None, "445"), OrderRef(1, 11, None, "ZAM/2026/12")]
    assert numbers_found(["Usługi wg zamówienia 4450"], refs) == set()
    assert numbers_found(["zam. 445, październik"], refs) == {"g10"}
    # „ZAM/2026/12” nie siedzi w „ZAM/2026/121”.
    assert numbers_found(["ZAM/2026/121"], refs) == set()
    assert numbers_found(["zam/2026/12 — usługi"], refs) == {"g11"}


def test_digits_only_number_matches_without_leading_zeros_and_sap_prefix():
    refs = [
        OrderRef(1, 10, None, "0012345678"),
        OrderRef(1, 11, None, "SAP 4500000123"),
    ]
    assert numbers_found(["PO 12345678"], refs) == {"g10"}
    assert numbers_found(["Zamówienie 4500000123"], refs) == {"g11"}


def test_short_or_digitless_titles_do_not_bind():
    refs = [OrderRef(1, None, 5, "PO"), OrderRef(1, None, 6, "12")]
    assert numbers_found(["PO 12 do zamówienia"], refs) == set()


# ── Dopasowanie ───────────────────────────────────────────────────────────────


def test_number_binds_even_with_a_different_amount():
    row = _group(10, "ZAM/2026/124", _line(1, "22425.00"))
    decision = decide(
        net=Decimal("22500.00"),
        currency="PLN",
        texts=["ZAM/2026/124"],
        rows=[row],
        refs=_refs(row),
    )
    assert decision.targets == (Target(group_id=10),)
    assert decision.method == "order_number"


def test_number_and_one_person_amount_links_to_that_person():
    row = _group(
        10, "445", _line(1, "10000.00"), _line(2, "12000.00", "Ewa Przykładowa")
    )
    decision = decide(
        net=Decimal("12000.00"),
        currency="PLN",
        texts=["zam 445"],
        rows=[row],
        refs=_refs(row),
    )
    assert decision.targets == (Target(order_id=2),)


def test_number_outside_the_month_is_not_guessed():
    row = _group(10, "ZAM/1", _line(1, "100.00"))
    refs = _refs(row) + [OrderRef(1, 99, None, "ZAM/2025/9")]
    decision = decide(
        net=Decimal("100.00"),
        currency="PLN",
        texts=["ZAM/2025/9"],
        rows=[row],
        refs=refs,
    )
    assert not decision.matched
    assert decision.reason == "order_outside_period"


def test_several_numbers_bind_when_the_sum_matches():
    a = _group(10, "ZAM/1", _line(1, "100.00"))
    b = _periodic(20, "ZAM/2", "50.00")
    decision = decide(
        net=Decimal("150.00"),
        currency="PLN",
        texts=["ZAM/1, ZAM/2"],
        rows=[a, b],
        refs=_refs(a, b),
    )
    assert set(decision.targets) == {Target(group_id=10), Target(order_id=20)}
    unclear = decide(
        net=Decimal("120.00"),
        currency="PLN",
        texts=["ZAM/1, ZAM/2"],
        rows=[a, b],
        refs=_refs(a, b),
    )
    assert unclear.reason == "several_orders"


def test_amount_without_number_must_be_unique():
    a = _periodic(20, "ZAM/2", "31920.00")
    b = _periodic(21, "ZAM/3", "24000.00")
    found = decide(
        net=Decimal("24000.00"), currency="PLN", texts=[], rows=[a, b], refs=[]
    )
    assert found.targets == (Target(order_id=21),) and found.method == "amount"

    twins = [_periodic(20, "ZAM/2", "24000.00"), _periodic(21, "ZAM/3", "24000.00")]
    ambiguous = decide(
        net=Decimal("24000.00"), currency="PLN", texts=[], rows=twins, refs=[]
    )
    assert not ambiguous.matched and ambiguous.reason == "amount_ambiguous"


def test_amount_that_matches_nothing_waits_for_finance():
    rows = [_periodic(20, "ZAM/2", "31920.00")]
    decision = decide(
        net=Decimal("31000.00"), currency="PLN", texts=[], rows=rows, refs=[]
    )
    assert decision.reason == "amount_differs"
    unknown = decide(
        net=Decimal("31000.00"),
        currency="PLN",
        texts=[],
        rows=[_group(10, "ZAM/1", _line(1, None))],
        refs=[],
    )
    assert unknown.reason == "expected_unknown"


def test_currency_must_match_and_empty_month_is_reported():
    rows = [_periodic(20, "ZAM/2", "1000.00", currency="EUR")]
    assert (
        decide(
            net=Decimal("1000.00"), currency="PLN", texts=[], rows=rows, refs=[]
        ).reason
        == "currency_differs"
    )
    assert (
        decide(
            net=Decimal("1000.00"), currency="PLN", texts=[], rows=[], refs=[]
        ).reason
        == "no_orders"
    )


# ── Część miesiąca ───────────────────────────────────────────────────────────


def test_period_fraction_counts_working_days_without_holidays():
    first, last = date(2026, 11, 1), date(2026, 11, 30)
    whole, note = period_fraction(date(2026, 1, 1), None, first, last)
    assert whole == Decimal("1") and note is None
    # Listopad 2026: 20 dni roboczych (11.11 to święto); od 16.11 — 11 dni.
    part, note = period_fraction(date(2026, 11, 16), None, first, last)
    assert part == Decimal(11) / Decimal(20)
    assert note == "częściowy miesiąc: 11 z 20 dni roboczych"


# ── Wpłaty z wyciągu ──────────────────────────────────────────────────────────


def _credit(amount, title, currency="PLN"):
    return StatementLine(
        index=1,
        booked_on=date(2026, 11, 14),
        amount=Decimal(amount),
        direction="credit",
        currency=currency,
        title=title,
        counterparty_name="Bank Testowy S.A.",
        bank_ref="REF1",
    )


def _open(invoice_id, number, to_pay, ksef=None, currency="PLN"):
    return OpenInvoice(
        invoice_id=invoice_id,
        currency=currency,
        to_pay=Decimal(to_pay),
        ksef_numbers=(ksef,) if ksef else (),
        invoice_numbers=(number,),
    )


def test_credit_with_ksef_number_pays_the_invoice_or_part_of_it():
    invoices = [_open(1, "FS 10/118/2026", "30996.00", KSEF_A)]
    full = decide_credit(_credit("30996.00", f"Zapłata {KSEF_A}"), invoices)
    assert (full.invoice_id, full.reason) == (1, "ksef")
    part = decide_credit(_credit("10000.00", f"Zapłata {KSEF_A}"), invoices)
    assert part.invoice_id == 1 and part.amount == Decimal("10000.00")
    too_much = decide_credit(_credit("40000.00", f"Zapłata {KSEF_A}"), invoices)
    assert too_much.invoice_id is None and too_much.reason == "amount_exceeds"


def test_credit_for_a_paid_invoice_is_flagged_not_counted_twice():
    invoices = [_open(1, "FS 10/118/2026", "0.00", KSEF_A)]
    decision = decide_credit(_credit("30996.00", "FS 10/118/2026"), invoices)
    assert decision.invoice_id is None and decision.reason == "already_paid"


def test_invoice_number_in_title_is_matched_as_a_whole_word():
    invoices = [_open(1, "1/10/2026", "100.00"), _open(2, "11/10/2026", "200.00")]
    decision = decide_credit(_credit("200.00", "Faktura 11/10/2026"), invoices)
    assert decision.invoice_id == 2
    spaced = decide_credit(_credit("100.00", "fv 1/10/2026 zapłata"), invoices)
    assert spaced.invoice_id == 1


def test_split_payment_counts_vat_paid_to_the_vat_account():
    assert mpp_vat("/VAT/5157,75/IDC/1111111111/INV/FS 10/124/2026/TXT/X") == Decimal(
        "5157.75"
    )
    invoices = [_open(3, "FS 10/124/2026", "27582.75")]
    decision = decide_credit(
        _credit(
            "22425.00", "/VAT/5157,75/IDC/1111111111/INV/FS 10/124/2026/TXT/ZAPLATA"
        ),
        invoices,
    )
    assert decision.invoice_id == 3
    assert decision.amount == Decimal("27582.75")


def test_credit_without_number_is_only_a_hint_and_unrelated_is_skipped():
    invoices = [_open(4, "FS 11/7/2026", "1230.00")]
    hint = decide_credit(_credit("1230.00", "Zapłata za monitor"), invoices)
    assert hint.invoice_id is None and hint.related and hint.reason == "amount_only"
    assert hint.hint_invoice_id == 4
    other = decide_credit(_credit("500.00", "Zwrot kaucji"), invoices)
    assert not other.related
    foreign = decide_credit(
        _credit("1230.00", "FS 11/7/2026", currency="EUR"), invoices
    )
    assert foreign.reason == "currency_differs"
