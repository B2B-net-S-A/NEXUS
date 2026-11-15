"""Zakup zagraniczny (K5b-2) — reguły bez bazy: grupa JPK z numeru dostawcy,
kwoty po kursie NBP, dekret FVZ importu usług, pola formularza i odmowy.
Dostawcy, numery i kwoty fikcyjne."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import engine, foreign

TODAY = date(2026, 11, 15)
ACCOUNTS = {
    "cost_account": "402-1",
    "input_account": "221",
    "output_account": "222",
    "supplier_account": "202-1-7",
}


def _form(**extra) -> dict:
    values = {
        "number": "INV-0042",
        "issue_date": "2026-10-31",
        "service_date": "2026-10-31",
        "currency": "EUR",
        "net": "100.00",
        "vat_rate": "23",
        "deduction": "full",
        "cost_account": "402-1",
        "description": None,
    }
    values.update(extra)
    return values


def test_group_follows_the_suppliers_eu_vat_number():
    assert foreign.jpk_group("vat_eu", "IE1234567T") == "imp_28b"
    # Irlandia Północna (XI) to VAT UE tylko dla towarów.
    assert foreign.jpk_group("vat_eu", "XI123456789") == "imp_other"
    assert foreign.jpk_group("other", "GB123456789") == "imp_other"
    assert foreign.jpk_group(None, None) == "imp_other"


def test_amounts_use_the_nbp_rate_and_round_vat_to_a_grosz():
    euro = foreign.figures(Decimal("100.00"), rate=Decimal("4.2512"), vat_rate="23")
    assert (euro.net, euro.vat, euro.net_cur) == (42_512, 9_778, 10_000)
    correction = foreign.figures(Decimal("-100.00"), rate=Decimal("4.2512"), vat_rate="23")
    assert (correction.net, correction.vat, correction.net_cur) == (-42_512, -9_778, -10_000)
    zloty = foreign.figures(Decimal("200.00"), rate=None, vat_rate="8")
    assert (zloty.net, zloty.vat, zloty.net_cur) == (20_000, 1_600, 20_000)


def _decree(amounts: foreign.Figures, **extra) -> list[engine.LineIn]:
    values = {
        "currency": "EUR",
        "deduction": "full",
        "supplier_id": 7,
        "text": "Dostawca SaaS INV-0042",
        **ACCOUNTS,
    }
    values.update(extra)
    return foreign.decree(amounts, **values)


def test_decree_books_output_and_input_vat_and_the_supplier_in_currency():
    amounts = foreign.Figures(net=42_512, vat=9_778, net_cur=10_000)
    lines = _decree(amounts)
    assert [(line.side, line.account, line.amount) for line in lines] == [
        ("debit", "402-1", 42_512),
        ("debit", "221", 9_778),
        ("credit", "222", 9_778),
        ("credit", "202-1-7", 42_512),
    ]
    supplier = lines[-1]
    assert (supplier.counterparty_id, supplier.currency, supplier.amount_cur) == (7, "EUR", 10_000)
    assert engine.totals(lines)[0] == engine.totals(lines)[1]


def test_decree_without_deduction_puts_vat_into_the_cost():
    lines = _decree(foreign.Figures(net=20_000, vat=4_600, net_cur=20_000), currency="PLN", deduction="none")
    assert [(line.side, line.account, line.amount) for line in lines] == [
        ("debit", "402-1", 24_600),
        ("credit", "222", 4_600),
        ("credit", "202-1-7", 20_000),
    ]
    assert (lines[-1].currency, lines[-1].amount_cur) == ("PLN", None)


def test_correction_reverses_the_sides():
    lines = _decree(foreign.Figures(net=-42_512, vat=-9_778, net_cur=-10_000))
    assert [(line.side, line.amount) for line in lines] == [
        ("credit", 42_512),
        ("credit", 9_778),
        ("debit", 9_778),
        ("debit", 42_512),
    ]
    assert lines[-1].amount_cur == 10_000


def test_invoice_number_case_and_spaces_do_not_make_a_new_source():
    assert foreign.source_key(7, "inv 0042") == foreign.source_key(7, "INV0042")
    assert foreign.source_key(7, "INV-0042") != foreign.source_key(8, "INV-0042")
    assert len(foreign.source_key(2**62, "X" * 80)) <= 64


def test_form_fields_are_cleaned():
    invoice = foreign.clean_invoice(_form(net="1 234,50", currency="eur"), today=TODAY)
    assert (invoice.net, invoice.currency) == (Decimal("1234.50"), "EUR")
    assert invoice.service_date == date(2026, 10, 31)


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ({"number": "  "}, "numer faktury"),
        ({"currency": "EURO"}, "Waluta"),
        ({"net": "0"}, "zerem"),
        ({"net": "10.005"}, "dwa miejsca"),
        ({"net": "abc"}, "liczbę"),
        ({"vat_rate": "0"}, "Stawka VAT"),
        ({"deduction": "half"}, "Odliczenie"),
        ({"service_date": "2026-11-16"}, "przyszłości"),
        ({"issue_date": ""}, "Data wystawienia"),
        ({"cost_account": ""}, "Konto kosztu"),
    ],
)
def test_form_refuses_bad_fields(extra, message):
    with pytest.raises(LedgerError) as caught:
        foreign.clean_invoice(_form(**extra), today=TODAY)
    assert caught.value.status == 422 and message in caught.value.message


def test_supplier_number_gets_the_country_prefix_and_refuses_polish_ids():
    irish = foreign.clean_tax_id("1234567t", "IE")
    assert (irish.type, irish.value) == ("vat_eu", "IE1234567T")
    greek = foreign.clean_tax_id("EL123456789", "GR")
    assert (greek.type, greek.value) == ("vat_eu", "EL123456789")
    assert foreign.clean_tax_id("123456789", "GR").value == "EL123456789"
    american = foreign.clean_tax_id("12-3456789", "US")
    assert (american.type, american.value) == ("other", "123456789")
    assert foreign.clean_tax_id(" ", "US") is None
    with pytest.raises(LedgerError) as caught:
        foreign.clean_tax_id("PL5260300517", "US")
    assert "polski numer" in caught.value.message


def test_supplier_country_must_be_in_the_mf_dictionary():
    """Przegląd K5b-2: „UK” nie ma w słowniku krajów MF — plik JPK z takim
    kodem nie przechodził schematu, a kraju w kartotece nie da się poprawić."""

    assert [foreign.clean_country(code) for code in ("ie", "UK", "EL", "US", "XI")] == ["IE", "GB", "GR", "US", "XI"]
    for code in ("XX", "U", "PL"):
        with pytest.raises(LedgerError) as caught:
            foreign.clean_country(code)
        assert caught.value.status == 422


def test_eu_vat_number_typed_as_other_still_counts_as_eu():
    """Import z eBI24 bywa z typem „inny” — numer z prefiksem kraju UE to dalej
    podatnik VAT z UE (art. 28b, K_29/K_30); spoza UE i XI — K_27/K_28."""

    assert foreign.jpk_group("other", "DE123456789") == "imp_28b"
    assert foreign.jpk_group("other", "CHE123456789MWST") == "imp_other"
    assert foreign.jpk_group("other", "123456789") == "imp_other"
