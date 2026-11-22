"""Dodatki do rozliczenia kontraktora bez bazy: kwota oczekiwana faktury,
uwaga „czeka na zatwierdzenie dodatku”, pozycje faktury dla klienta. Kwoty fikcyjne."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services.client_settlements import client_invoice
from app.services.client_settlements import contractor_invoices as ci
from app.services.client_settlements import extras

RULES = {
    "ci.amount": {"level": "block", "params": {"tolerance": "0,00"}},
    "ci.buyer_nip": {"level": "off", "params": {}},
    "ci.payment_days": {"level": "off", "params": {}},
}


def _settlement(cost: str) -> SimpleNamespace:
    return SimpleNamespace(amount_cost=Decimal(cost), status="accepted")


def _invoice(net: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        nip_state=ci.KNOWN,
        net_amount=Decimal(net),
        gross_amount=Decimal(net) * Decimal("1.23"),
        ksef_number="K",
        invoice_number="FV 1",
        issue_date=None,
        acquired_at=None,
        seller_name="Firma",
        seller_nip="9980000000",
        buyer_nip=None,
        # Pola korekt i białej listy z E4 (``invoice_chain``): zwykła faktura.
        invoice_type="Vat",
        details=None,
        vat_amount=Decimal(net) * Decimal("0.23"),
        vat_whitelist=None,
    )


def _extra(kind: str, status: str, amount: str, **kw) -> SimpleNamespace:
    return SimpleNamespace(
        kind=kind,
        status=status,
        amount=Decimal(amount),
        bill_to_client=kw.get("bill", False),
    )


def test_faktura_rowna_godzinom_plus_zatwierdzonemu_dodatkowi_jest_w_ksef() -> None:
    added = extras.totals([_extra("tech_check", "approved", "200")])
    state = ci.state(_settlement("10000"), [_invoice("10200")], RULES, added)
    assert state == ci.IN_KSEF
    card = ci.card(
        _settlement("10000"), [_invoice("10200")], RULES, amounts=True, extras=added
    )
    assert card["checks"][0] == {
        "state": "ok",
        "title": "Kwota równa wyliczeniu z RCP i dodatkom",
    }


def test_bez_dodatkow_ta_sama_faktura_to_inna_kwota() -> None:
    assert ci.state(_settlement("10000"), [_invoice("10200")], RULES) == ci.DIFFERS


def test_roznica_rowna_zgloszonemu_dodatkowi_to_uwaga_nie_blad() -> None:
    added = extras.totals(
        [_extra("referral", "pending", "500"), _extra("travel", "pending", "300")]
    )
    # Jeden ze zgłoszonych, potem oba razem.
    for net in ("10500", "10300", "10800"):
        assert ci.state(_settlement("10000"), [_invoice(net)], RULES, added) == (
            ci.EXTRA_PENDING
        )
    card = ci.card(
        _settlement("10000"), [_invoice("10500")], RULES, amounts=True, extras=added
    )
    check = card["checks"][0]
    assert check["state"] == "warn"  # nigdy „fail”, choć ci.amount blokuje
    assert check["title"] == "Czeka na zatwierdzenie dodatku"
    assert "różnica 500,00 zł" in check["detail"]
    # Inna różnica dalej jest błędem kwoty.
    assert ci.state(_settlement("10000"), [_invoice("10400")], RULES, added) == (
        ci.DIFFERS
    )


def test_odrzucony_i_integracja_nie_licza_sie_do_kwoty_faktury() -> None:
    added = extras.totals(
        [
            _extra("referral", "rejected", "500"),
            _extra("integration", "approved", "800"),
            _extra("integration", "pending", "100"),
        ]
    )
    assert added.approved == Decimal("0") and added.pending == ()
    assert ci.expected(_settlement("10000"), added) == Decimal("10000")


@pytest.mark.parametrize("raw", ["0", "-5", "abc", "100000.01", "NaN"])
def test_kwota_dodatku_odmawia(raw: str) -> None:
    with pytest.raises(extras.ExtraError):
        extras.clean_amount(raw)


def test_kwota_dodatku_z_przecinkiem_i_spacja() -> None:
    assert extras.clean_amount("1 200,5") == Decimal("1200.50")


def _base() -> list[client_invoice.Position]:
    return [
        client_invoice.Position(
            name="Usługi; Osoba",
            unit="MD",
            quantity=Decimal("20"),
            unit_price=Decimal("1100"),
            net=Decimal("22000.00"),
            kind="base",
        )
    ]


def test_dodatek_dla_klienta_osobna_pozycja_z_reguly() -> None:
    rule = {"level": "warn", "params": {"item": "Koszty delegacji"}}
    items, note = client_invoice.with_extras(
        _base(),
        [_extra("travel", "approved", "350", bill=True)],
        rule=rule,
        currency="PLN",
        name="Usługi; Osoba",
    )
    assert note is None
    assert [(p.name, p.net, p.kind) for p in items] == [
        ("Usługi; Osoba", Decimal("22000.00"), "base"),
        ("Koszty delegacji", Decimal("350.00"), "extra"),
    ]


def test_dodatek_dla_klienta_doliczony_do_pozycji_zasadniczej() -> None:
    rule = {"level": "warn", "params": {"item": ""}}
    items, note = client_invoice.with_extras(
        _base(),
        [_extra("travel", "approved", "350", bill=True)],
        rule=rule,
        currency="PLN",
        name="Usługi; Osoba",
    )
    assert note is None and len(items) == 1
    # Jedna pozycja „usługa z kosztami”: 1 × suma (jak faktura główna z KEŚU).
    assert (items[0].quantity, items[0].unit_price, items[0].net) == (
        Decimal("1"),
        Decimal("22350.00"),
        Decimal("22350.00"),
    )


def test_regula_wylaczona_albo_inna_waluta_daje_uwage_bez_pozycji() -> None:
    billed = [_extra("travel", "approved", "350", bill=True)]
    off = {"level": "off", "params": {}}
    items, note = client_invoice.with_extras(
        _base(), billed, rule=off, currency="PLN", name="x"
    )
    assert len(items) == 1 and "wyłączona" in note
    on = {"level": "warn", "params": {"item": "Koszty"}}
    items, note = client_invoice.with_extras(
        _base(), billed, rule=on, currency="EUR", name="x"
    )
    assert len(items) == 1 and "EUR" in note
