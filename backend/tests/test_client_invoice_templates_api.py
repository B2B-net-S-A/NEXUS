"""Faktura z ręki, szablony „co miesiąc” i refaktury benefitów (E6, 15.11.2026).

Zakres: tylko „Moduł Finanse”; faktura z ręki do nabywcy spoza kartoteki
klientów przechodzi całą drogę do KSeF (bez ``client_id``); propozycje
szablonów z faktur z KSeF bez zamówienia (zamówione się nie pokazują, adres
z kartoteki kontrahentów, refaktura benefitu rozpoznana po nazwie, drugi
import nie dubluje); szkice z szablonów za miesiąc (miesiąc w nazwie pozycji,
drugie kliknięcie = 409, szablon wyłączony i spoza ważności się nie wystawia);
„Zapisz jako szablon”. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from lxml import etree
from sqlalchemy import delete, or_, select

from app.api import client_issued_invoices as api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from app.models.client_issued_invoice import (
    ClientInvoiceSeries,
    ClientInvoiceTemplate,
    ClientIssuedInvoice,
)
from app.models.client_sales_invoice import ClientSalesInvoice, ClientSalesInvoiceLink
from app.models.finance_ledger import FinanceCounterparty
from app.services.client_invoicing import issue_settings, ksef_send, templates
from app.services.hr.ksef.client import forget_sessions
from tests._ksef_fake import Clock
from tests.client_invoicing import helpers as fx
from tests.client_invoicing.ksef_issue_fake import TOKEN, FakeKsefIssue, factory
from tests.test_client_invoice_issue_api import OCTOBER, SETTINGS, TODAY

pytestmark = pytest.mark.asyncio

BASE = "/api/finance/issued-invoices"
NOVEMBER = {"year": 2026, "month": 11}


@pytest_asyncio.fixture
async def client():
    target = FastAPI()
    target.include_router(api.router, prefix=BASE)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


async def _cleanup(client_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        scope = or_(
            ClientIssuedInvoice.client_id.in_(client_ids),
            ClientIssuedInvoice.client_id.is_(None),
            ClientIssuedInvoice.template_id.is_not(None),
        )
        await db.execute(delete(ClientIssuedInvoice).where(scope))
        await db.execute(delete(ClientInvoiceTemplate))
        await db.execute(
            delete(ClientInvoiceSeries).where(ClientInvoiceSeries.period_year == 2026)
        )
        await db.execute(
            delete(FinanceCounterparty).where(
                FinanceCounterparty.id_value == fx.UNKNOWN_NIP
            )
        )
        await db.execute(
            delete(AppSetting).where(AppSetting.key == issue_settings.SETTING_KEY)
        )
        await db.commit()


@pytest_asyncio.fixture
async def seed(monkeypatch):
    monkeypatch.setattr(api, "business_today", lambda: TODAY)
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", fx.COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_MODE", "test")
    monkeypatch.setattr(settings, "KSEF_SALES_ISSUE_TOKEN", TOKEN)
    forget_sessions()
    fake = FakeKsefIssue(Clock())
    fake.invoice_codes = [200]
    monkeypatch.setattr(ksef_send, "default_client", factory(fake))
    data = await fx.seed_month()
    data.fake = fake  # type: ignore[attr-defined]
    await fx.set_module(True)
    await _cleanup([data.client_id, data.other_client_id])
    yield data
    await _cleanup([data.client_id, data.other_client_id])
    await fx.wipe()
    await fx.set_module(None)
    forget_sessions()


def _h(seed, role: str = "finance") -> dict[str, str]:
    return fx.headers(seed.users[role])


async def _settings(client, seed) -> None:
    response = await client.put(f"{BASE}/settings", json=SETTINGS, headers=_h(seed))
    assert response.status_code == 200, response.text


def _sales(
    seq: int, *, nip: str, name: str, items: list[dict], client_id=None
) -> ClientSalesInvoice:
    net = sum(Decimal(item["net"]) for item in items)
    return ClientSalesInvoice(
        ksef_number=f"{fx.COMPANY_NIP}-20261031-EB10000000{seq:02d}-01",
        xml_sha256="0" * 64,
        buyer_nip=nip,
        buyer_name=name,
        client_id=client_id,
        invoice_number=f"{seq}/10/2026",
        invoice_type="VAT",
        issue_date=date(2026, 10, 31),
        period_year=2026,
        period_month=10,
        period_source="invoice",
        currency="PLN",
        net_amount=net,
        vat_amount=Decimal("0.00"),
        gross_amount=net,
        items=items,
        order_refs=[],
        match_status="unmatched",
        fetched_at=datetime.now(timezone.utc),
    )


SPORT = {
    "name": "Refaktura kosztów pakietu sportowego",
    "unit": "szt.",
    "quantity": "1",
    "vat_rate": "8",
    "unit_price": "65.74",
    "net": "65.74",
}
SUPPORT = {
    "name": "Usługa IT wsparcie on-site 10.2026",
    "unit": "mies.",
    "quantity": "1",
    "vat_rate": "23",
    "unit_price": "12000",
    "net": "12000.00",
}


async def _seed_ebi24_month(seed) -> dict[str, str]:
    """Trzy faktury z października z „eBI24”: refaktura, usługa bez zamówienia, zamówiona."""

    async with AsyncSessionLocal() as db:
        db.add(
            FinanceCounterparty(
                id_type="nip",
                id_value=fx.UNKNOWN_NIP,
                name="Jan Testowy Usługi IT",
                street="ul. Kontraktowa 3",
                postal_code="00-950",
                city="Warszawa",
                country="PL",
            )
        )
        benefit = _sales(
            1, nip=fx.UNKNOWN_NIP, name="Jan Testowy Usługi IT", items=[SPORT]
        )
        service = _sales(
            2,
            nip=fx.CLIENT_NIP,
            name="Klient Testowy",
            items=[SUPPORT],
            client_id=seed.client_id,
        )
        ordered = _sales(
            3,
            nip=fx.CLIENT_NIP,
            name="Klient Testowy",
            items=[SUPPORT],
            client_id=seed.client_id,
        )
        db.add_all([benefit, service, ordered])
        await db.flush()
        db.add(
            ClientSalesInvoiceLink(
                invoice_id=ordered.id,
                order_group_id=seed.groups["118"],
                period_year=2026,
                period_month=10,
            )
        )
        await db.commit()
        return {"benefit": benefit.ksef_number, "service": service.ksef_number}


# ── Dostęp ──────────────────────────────────────────────────────────────────


async def test_only_finance_module_sees_templates(client, seed):
    for role in ("recruiter", "dl"):
        response = await client.get(f"{BASE}/templates", headers=_h(seed, role))
        assert response.status_code == 403, (role, response.text)
    manual = await client.post(f"{BASE}/manual", json={}, headers=_h(seed, "recruiter"))
    assert manual.status_code == 403


# ── Faktura z ręki ──────────────────────────────────────────────────────────


async def test_manual_invoice_without_buyer_is_refused(client, seed):
    response = await client.post(f"{BASE}/manual", json={}, headers=_h(seed))
    assert response.status_code == 422, response.text


async def test_manual_invoice_to_buyer_outside_clients_goes_to_ksef(client, seed):
    await _settings(client, seed)
    created = await client.post(
        f"{BASE}/manual",
        json={
            "buyer": {
                "name": "Firma Spoza Kartoteki",
                "number": fx.UNKNOWN_NIP,
                "address_l1": "ul. Obca 1, 00-003 Warszawa",
            }
        },
        headers=_h(seed),
    )
    assert created.status_code == 201, created.text
    card = created.json()
    assert card["client_id"] is None
    assert card["client_name"] == "Firma Spoza Kartoteki"
    assert card["series_code"] == "PL"
    filled = await client.put(
        f"{BASE}/{card['id']}",
        json={
            "lines": [
                {
                    "name": "Sprzedaż sprzętu",
                    "quantity": "1",
                    "unit": "szt.",
                    "unit_price": "1000",
                    "vat_rate": "23",
                }
            ]
        },
        headers=_h(seed),
    )
    assert filled.status_code == 200, filled.text
    assert filled.json()["net"] == "1000.00"

    sent = await client.post(f"{BASE}/{card['id']}/send", headers=_h(seed))
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "accepted", sent.json()
    (xml,) = seed.fake.received
    root = etree.fromstring(xml)
    assert root.findtext("{*}Podmiot2/{*}DaneIdentyfikacyjne/{*}NIP") == fx.UNKNOWN_NIP
    async with AsyncSessionLocal() as db:
        sales = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == sent.json()["ksef_number"]
            )
        )
        assert sales is not None and sales.client_id is None
    listing = (await client.get(BASE, params={"view": "sent"}, headers=_h(seed))).json()
    assert [row["client_name"] for row in listing["invoices"]] == [
        "Firma Spoza Kartoteki"
    ]


# ── Szablony z faktur z KSeF ────────────────────────────────────────────────


async def test_templates_from_ksef_month_and_drafts_for_next_month(client, seed):
    await _settings(client, seed)
    numbers = await _seed_ebi24_month(seed)

    proposals = (
        await client.get(
            f"{BASE}/templates/suggestions", params=OCTOBER, headers=_h(seed)
        )
    ).json()
    rows = {row["ksef_number"]: row for row in proposals["rows"]}
    # Faktura powiązana z zamówieniem idzie przez „Wystaw za miesiąc”, nie tutaj.
    assert set(rows) == {numbers["benefit"], numbers["service"]}
    assert rows[numbers["benefit"]]["kind"] == "benefit"
    assert rows[numbers["benefit"]]["benefit"] == "sport"
    assert rows[numbers["benefit"]]["address_missing"] is False
    assert rows[numbers["service"]]["kind"] == "service"
    assert rows[numbers["service"]]["client_id"] == seed.client_id
    assert (
        rows[numbers["service"]]["lines"][0]["name"]
        == "Usługa IT wsparcie on-site {mm}.{rrrr}"
    )

    imported = await client.post(
        f"{BASE}/templates/import",
        json={**OCTOBER, "ksef_numbers": list(numbers.values())},
        headers=_h(seed),
    )
    assert imported.status_code == 201, imported.text
    assert len(imported.json()["created"]) == 2
    again = await client.post(
        f"{BASE}/templates/import",
        json={**OCTOBER, "ksef_numbers": list(numbers.values())},
        headers=_h(seed),
    )
    assert again.json()["created"] == []
    marked = (
        await client.get(
            f"{BASE}/templates/suggestions", params=OCTOBER, headers=_h(seed)
        )
    ).json()
    assert all(row["has_template"] for row in marked["rows"])

    benefits = (
        await client.get(
            f"{BASE}/templates",
            params={**NOVEMBER, "kind": "benefit"},
            headers=_h(seed),
        )
    ).json()["templates"]
    assert [(t["benefit"], t["net"], t["selectable"]) for t in benefits] == [
        ("sport", "65.74", True)
    ]
    assert benefits[0]["buyer"]["address_l1"] == "ul. Kontraktowa 3"
    assert benefits[0]["buyer"]["address_l2"] == "00-950 Warszawa"

    ids = imported.json()["created"]
    run = await client.post(
        f"{BASE}/templates/run",
        json={**NOVEMBER, "template_ids": ids},
        headers=_h(seed),
    )
    assert run.status_code == 201, run.text
    drafts = run.json()["created"]
    assert len(drafts) == 2
    cards = [
        (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
        for invoice_id in drafts
    ]
    by_kind = {card["lines"][0]["name"]: card for card in cards}
    service = by_kind["Usługa IT wsparcie on-site 11.2026"]
    assert service["client_id"] == seed.client_id
    assert service["period_from"] == "2026-11-01"
    assert service["period_to"] == "2026-11-30"
    benefit = by_kind["Refaktura kosztów pakietu sportowego"]
    assert benefit["client_id"] is None
    assert benefit["net"] == "65.74"
    assert benefit["template_id"] in ids
    assert benefit["problems"] == [], benefit["problems"]

    twice = await client.post(
        f"{BASE}/templates/run",
        json={**NOVEMBER, "template_ids": ids},
        headers=_h(seed),
    )
    assert twice.status_code == 409, twice.text
    after = (
        await client.get(f"{BASE}/templates", params=NOVEMBER, headers=_h(seed))
    ).json()["templates"]
    assert all(t["issued"] and not t["selectable"] for t in after)


async def test_inactive_and_expired_templates_are_not_issued(client, seed):
    await _settings(client, seed)
    refused = await client.post(
        f"{BASE}/templates",
        json={"kind": "benefit", "name": "Bez benefitu", "lines": [SPORT]},
        headers=_h(seed),
    )
    assert refused.status_code == 422, refused.text

    created = await client.post(
        f"{BASE}/templates",
        json={
            "kind": "benefit",
            "benefit": "medical",
            "buyer": {"name": "Osoba Testowa", "number": fx.UNKNOWN_NIP},
            "lines": [{**SPORT, "name": "Refaktura kosztów opieki medycznej"}],
            "valid_to": "2026-10-31",
        },
        headers=_h(seed),
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["name"] == "Osoba Testowa"
    expired = await client.post(
        f"{BASE}/templates/run",
        json={**NOVEMBER, "template_ids": [template["id"]]},
        headers=_h(seed),
    )
    assert expired.status_code == 409
    assert "nie obowiązuje" in expired.json()["detail"]

    off = await client.put(
        f"{BASE}/templates/{template['id']}",
        json={"valid_to": None, "active": False},
        headers=_h(seed),
    )
    assert off.status_code == 200, off.text
    assert off.json()["selectable"] is False
    inactive = await client.post(
        f"{BASE}/templates/run",
        json={**NOVEMBER, "template_ids": [template["id"]]},
        headers=_h(seed),
    )
    assert inactive.status_code == 409
    assert "wyłączony" in inactive.json()["detail"]

    gone = await client.delete(f"{BASE}/templates/{template['id']}", headers=_h(seed))
    assert gone.status_code == 200
    assert (
        await client.put(
            f"{BASE}/templates/{template['id']}",
            json={"active": True},
            headers=_h(seed),
        )
    ).status_code == 404


async def test_save_invoice_as_template(client, seed):
    await _settings(client, seed)
    response = await client.post(
        f"{BASE}/drafts",
        json={**OCTOBER, "keys": [f"g{seed.groups['118']}"]},
        headers=_h(seed),
    )
    assert response.status_code == 201, response.text
    (invoice_id,) = response.json()["created"]
    saved = await client.post(f"{BASE}/{invoice_id}/template", headers=_h(seed))
    assert saved.status_code == 201, saved.text
    template = saved.json()
    assert template["kind"] == "service"
    assert template["client_id"] == seed.client_id
    assert template["source"] == "invoice"
    assert all(line["order_id"] is None for line in template["lines"])
    assert all("{okres}" in line["name"] for line in template["lines"]), template[
        "lines"
    ]


# ── Nazwy pozycji ───────────────────────────────────────────────────────────


def test_month_in_line_name_round_trips():
    for name in (
        "Usługi za październik 2026",
        "Wsparcie w okresie października 2026",
        "Usługa SD 10.2026",
        "Abonament 10/2026",
    ):
        template = templates.templatize_name(name, 2026, 10)
        assert "2026" not in template, template
        assert templates.render_name(template, 2026, 10) == name
    assert (
        templates.render_name("Usługi za {okres} ({mm}/{rrrr})", 2027, 1)
        == "Usługi za styczeń 2027 (01/2027)"
    )
    # Inna data w nazwie (nie miesiąc faktury) zostaje.
    assert templates.templatize_name("Umowa z dnia 31-10-2025 r.", 2026, 10) == (
        "Umowa z dnia 31-10-2025 r."
    )


def test_benefit_is_recognised_by_line_name():
    assert templates.benefit_of(["Refaktura kosztów pakietu sportowego"]) == "sport"
    assert templates.benefit_of(["Refaktura kosztów opieki medycznej"]) == "medical"
    assert templates.benefit_of(["Refaktura kosztów notarialnych"]) == "other"
    assert templates.benefit_of(["Usługa informatyczna"]) is None
