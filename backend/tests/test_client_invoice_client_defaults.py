"""Adres i termin szkicu z historii klienta (28.11.2026).

Pomiar na kopii produkcji: 24 z 28 klientów z kontraktem nie miało adresu na
karcie, więc XML FA(3) ich faktur nie powstawał, a termin 14 dni różnił się od
faktur Finansów u 19 z 27. Firmy, NIP-y i adresy zmyślone.
"""

from __future__ import annotations

import random
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.finance_ledger import FinanceCounterparty
from app.services.client_invoicing import (
    client_defaults,
    issue,
    issue_settings,
    numbering,
)

TODAY = date(2026, 12, 3)
SETTINGS = issue_settings.normalize({})
SERIES_PATTERNS = dict(SETTINGS["series"])


def _client(address: str = "") -> Client:
    return Client(id=1, name="Bank Testowy", nip="1111111111", address=address)


def _history(**kw) -> client_defaults.ClientDefaults:
    base = {
        "address_l1": "ul. Testowa 1",
        "address_l2": "00-001 Warszawa",
        "payment_days": 30,
    }
    return client_defaults.ClientDefaults(**{**base, **kw})


def test_usual_term_picks_most_common_and_newer_on_tie():
    d = date(2026, 10, 1)
    pairs = [(d, d + timedelta(days=30))] * 3 + [(d, d + timedelta(days=14))]
    assert client_defaults.usual_term(pairs) == 30
    tie = [
        (date(2026, 9, 1), date(2026, 9, 22)),
        (date(2026, 10, 1), date(2026, 10, 31)),
    ]
    assert client_defaults.usual_term(tie) == 30
    # Termin przed datą wystawienia albo absurdalny to błąd danych.
    assert client_defaults.usual_term([(d, d), (d, d + timedelta(days=400))]) is None


def test_nip_key_ignores_pl_prefix_and_separators():
    assert client_defaults.nip_key("PL 111-111-11-11") == "1111111111"
    assert client_defaults.nip_key("DE811128135") == "DE811128135"
    assert client_defaults.nip_key(None) == ""


def test_empty_card_takes_address_and_term_from_history():
    out = issue._defaults(_client(), SETTINGS, TODAY, history=_history())  # noqa: SLF001
    assert out.buyer["address_l1"] == "ul. Testowa 1"
    assert out.buyer["address_l2"] == "00-001 Warszawa"
    assert out.due_date == TODAY + timedelta(days=30)


def test_card_and_client_setting_win_over_history():
    settings = {**SETTINGS, "clients": {"1": {"payment_days": 21}}}
    assert SETTINGS["payment_days"] == 14
    out = issue._defaults(  # noqa: SLF001
        _client("ul. Z Karty 5"), settings, TODAY, history=_history()
    )
    assert out.buyer["address_l1"] == "ul. Z Karty 5"
    assert out.due_date == TODAY + timedelta(days=21)


def test_without_history_default_term_stays():
    out = issue._defaults(_client(), SETTINGS, TODAY)  # noqa: SLF001
    assert out.due_date == TODAY + timedelta(days=14)
    assert out.buyer["address_l1"] == ""


def test_buyer_from_list_ignores_client_history_term():
    """Nabywca z listy klienta (np. spółka zagraniczna) ma własne warunki."""

    buyer = {"name": "Testowa GmbH", "number": "DE123456789", "address_l1": "Str. 1"}
    out = issue._defaults(  # noqa: SLF001
        _client(), SETTINGS, TODAY, buyer, history=_history()
    )
    assert out.buyer["address_l1"] == "Str. 1"
    assert out.due_date == TODAY + timedelta(days=14)


def _nip() -> str:
    return "9" + "".join(random.choice("0123456789") for _ in range(9))


def _sale(
    client_id: int, buyer: str, issued: date, days: int, **kw
) -> ClientSalesInvoice:
    tag = uuid.uuid4().hex[:12].upper()
    return ClientSalesInvoice(
        ksef_number=f"9876543210-{issued:%Y%m%d}-{tag}-01",
        xml_sha256="0" * 64,
        client_id=client_id,
        invoice_number=f"{tag}/{issued.month}/{issued.year}",
        invoice_kind="original",
        buyer_nip=buyer,
        issue_date=issued,
        due_date=issued + timedelta(days=days),
        currency="PLN",
        net_amount=Decimal("100.00"),
        vat_amount=Decimal("23.00"),
        gross_amount=Decimal("123.00"),
        items=[],
        order_refs=[],
        fetched_at=datetime.now(timezone.utc),
        **kw,
    )


@pytest.mark.asyncio
async def test_for_client_reads_own_nip_invoices_and_counterparty():
    nip, other = _nip(), _nip()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Testowy {uuid.uuid4().hex[:6]}", nip=nip)
        db.add(client)
        await db.flush()
        for month in (9, 10, 11):
            db.add(
                _sale(
                    client.id,
                    nip,
                    date(2026, month, 10),
                    30,
                    buyer_address_line1=f"ul. Faktury {month}",
                    buyer_address_line2="00-002 Warszawa",
                    buyer_country="PL",
                )
            )
        # Drugi nabywca klienta (inny NIP): ani jego termin, ani adres.
        for month in (9, 10, 11, 12):
            db.add(
                _sale(
                    client.id,
                    other,
                    date(2026, month, 1),
                    60,
                    buyer_address_line1="ul. Obca 9",
                )
            )
        # Faktura sprzed 12 miesięcy nie liczy się do terminu.
        db.add(_sale(client.id, nip, date(2025, 1, 5), 7))
        await db.flush()

        got = await client_defaults.for_client(db, client, today=TODAY)
        assert got.payment_days == 30
        assert got.address_l1 == "ul. Faktury 11"
        assert got.address_l2 == "00-002 Warszawa"

        db.add(
            FinanceCounterparty(
                id_type="nip",
                id_value=f"PL{nip}",
                name="Bank Testowy S.A.",
                street="ul. Kartoteki 2",
                postal_code="00-003",
                city="Warszawa",
                country="PL",
            )
        )
        await db.flush()
        got = await client_defaults.for_client(db, client, today=TODAY)
        assert got.address_l1 == "ul. Kartoteki 2"
        assert got.address_l2 == "00-003 Warszawa"
        await db.rollback()


@pytest.mark.asyncio
async def test_for_client_without_nip_returns_nothing():
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bez NIP {uuid.uuid4().hex[:6]}", nip=None)
        db.add(client)
        await db.flush()
        assert await client_defaults.for_client(db, client, today=TODAY) == (
            client_defaults.ClientDefaults()
        )
        await db.rollback()


def test_number_regex_matches_only_this_series_and_month():
    rx = numbering.number_regex("{n}/{m}/{yyyy}", 2031, 11)
    assert re.match(rx, "323/11/2031").group(1) == "323"
    assert re.match(rx, "12/11/2031/UE") is None
    assert re.match(rx, "5/10/2031") is None
    ue = numbering.number_regex("{n}/{mm}/{yyyy}/UE", 2031, 1)
    assert re.match(ue, "7/01/2031/UE").group(1) == "7"


@pytest.mark.asyncio
async def test_numbering_continues_after_ebi24_numbers_in_ksef():
    """Równolegle z eBI24: pierwsza faktura z NEXUSA nie może dostać numeru,
    który eBI24 już wydał (KSeF 440 i przypięcie cudzego numeru KSeF)."""

    pattern = "{n}/{m}/{yyyy}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Bank Testowy {uuid.uuid4().hex[:6]}", nip=_nip())
        db.add(client)
        await db.flush()
        db.add(_sale(client.id, client.nip, date(2031, 11, 3), 30))
        await db.flush()
        ebi = (
            await db.scalars(
                select(ClientSalesInvoice).where(
                    ClientSalesInvoice.client_id == client.id
                )
            )
        ).one()
        ebi.invoice_number = "323/11/2031"
        db.add(_sale(client.id, client.nip, date(2031, 11, 4), 30))
        await db.flush()

        view = await numbering.series_view(
            db, year=2031, month=11, patterns={**SERIES_PATTERNS, "PL": pattern}
        )
        assert next(row for row in view if row["code"] == "PL")["next_number"] == 324
        with pytest.raises(numbering.NumberingError):
            await numbering.set_next(
                db,
                code="PL",
                year=2031,
                month=11,
                next_number=300,
                actor_id=1,
                pattern=pattern,
            )
        invoice = ClientIssuedInvoice(series_code="PL", issue_date=date(2031, 11, 5))
        assert await numbering.assign(db, invoice, pattern=pattern) == "324/11/2031"
        await db.rollback()
