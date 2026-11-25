"""Kontrola formalna faktury sprzedaży — karta szkicu, wysyłka z powodem, raport KSeF.

Szkic z datą sprzedaży poza okresem usługi ma uwagi na karcie (``checks``),
wysyłka bez powodu = 409 bez numeru, z powodem idzie do KSeF, a powód zostaje
w historii. Raport ``/form-checks`` sprawdza faktury z KSeF spoza NEXUSA
(kod osoby przy regule ``cl.contractor_person_id``, MD ponad dni robocze,
osoba bez kontraktu, miesiąc w nazwie pozycji). Dane fikcyjne.
"""

# ruff: noqa: F811  (fikstury z test_client_invoice_issue_api)
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api import client_sales_invoices as sales_api
from app.core.database import AsyncSessionLocal
from app.models.client_issued_invoice import ClientIssuedInvoice
from app.models.client_sales_invoice import ClientSalesInvoice
from tests.client_invoicing import helpers as fx
from tests.test_client_invoice_issue_api import (  # noqa: F401  (fikstury)
    BASE,
    _draft,
    _h,
    _settings,
    client,
    rules,
    seed,
)

pytestmark = pytest.mark.asyncio

SALES = "/api/finance/sales-invoices"


@pytest_asyncio.fixture
async def sales_client():
    target = FastAPI()
    target.include_router(sales_api.finance_router, prefix=SALES)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


async def test_sale_date_outside_period_needs_a_reason_to_send(client, seed):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    moved = await client.put(
        f"{BASE}/{invoice_id}", json={"sale_date": "2026-11-14"}, headers=_h(seed)
    )
    assert moved.status_code == 200, moved.text
    [check] = moved.json()["checks"]
    assert "14.11.2026 poza okresem usługi" in check
    assert moved.json()["can_send"] is True

    refused = await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    assert refused.status_code == 409
    assert "Kontrola przed wysyłką" in refused.json()["detail"]
    short = await client.post(
        f"{BASE}/{invoice_id}/send", json={"checks_reason": "ok"}, headers=_h(seed)
    )
    assert short.status_code == 409
    async with AsyncSessionLocal() as db:
        invoice = await db.get(ClientIssuedInvoice, invoice_id)
        assert invoice.status == "draft" and invoice.invoice_number is None

    sent = await client.post(
        f"{BASE}/{invoice_id}/send",
        json={"checks_reason": "Klient prosił o datę z protokołu"},
        headers=_h(seed),
    )
    assert sent.status_code == 200, sent.text
    assert sent.json()["status"] == "accepted"
    async with AsyncSessionLocal() as db:
        invoice = await db.get(ClientIssuedInvoice, invoice_id)
        [note] = [h for h in invoice.history if h["event"] == "checks_overridden"]
        assert note["reason"] == "Klient prosił o datę z protokołu"
        assert note["checks"] == [check]


async def test_clean_draft_has_no_checks_and_sends_without_reason(client, seed):
    await _settings(client, seed)
    invoice_id = await _draft(client, seed, f"g{seed.groups['118']}")
    card = (await client.get(f"{BASE}/{invoice_id}", headers=_h(seed))).json()
    assert card["checks"] == []
    sent = await client.post(f"{BASE}/{invoice_id}/send", headers=_h(seed))
    assert sent.status_code == 200, sent.text


def _ksef_invoice(client_id: int, serial: int, items: list[dict]) -> ClientSalesInvoice:
    issued = date(2026, 10, 31)
    return ClientSalesInvoice(
        ksef_number=f"{fx.COMPANY_NIP}-20261031-FC{serial:0>10}-01",
        xml_sha256="0" * 64,
        client_id=client_id,
        invoice_number=f"{serial}/10/2026",
        issue_date=issued,
        sale_date=issued,
        period_year=2026,
        period_month=10,
        period_source="invoice",
        currency="PLN",
        net_amount=Decimal("100.00"),
        vat_amount=Decimal("0.00"),
        gross_amount=Decimal("100.00"),
        items=items,
        order_refs=[],
        match_status="unmatched",
        fetched_at=datetime.now(timezone.utc),
    )


async def test_report_checks_ksef_invoices_issued_outside_nexus(
    sales_client, seed, rules
):
    await rules({"cl.contractor_person_id": {"level": "warn"}})
    rows = [
        _ksef_invoice(
            seed.client_id,
            9101,
            [
                {
                    "name": "NIDS:1, IT, Contact: Anna Kliencka, "
                    "Contractor Jan Przykładowy ID: Jan Przykładowy",
                    "quantity": "23",
                    "unit": "MD",
                }
            ],
        ),
        _ksef_invoice(
            seed.client_id,
            9102,
            [{"name": "Usługi IT za wrzesień 2026", "quantity": "1", "unit": "szt."}],
        ),
        _ksef_invoice(
            seed.client_id,
            9103,
            [{"name": "Contractor Marek Nieznany ID: Z999999", "quantity": "10"}],
        ),
        _ksef_invoice(
            seed.client_id,
            9104,
            [{"name": "Usługi IT październik 2026", "quantity": "20", "unit": "MD"}],
        ),
    ]
    async with AsyncSessionLocal() as db:
        db.add_all(rows)
        await db.commit()
        ids = [row.id for row in rows]
    try:
        response = await sales_client.get(
            f"{SALES}/form-checks",
            params={"year": 2026, "month": 10},
            headers=_h(seed),
        )
        assert response.status_code == 200, response.text
        found = {
            row["invoice_id"]: row["problems"] for row in response.json()["invoices"]
        }
        assert set(found) == set(ids[:3])
        assert any("w polu ID jest" in p for p in found[ids[0]])
        assert any("23 MD" in p for p in found[ids[0]])
        assert any("wrzesień 2026" in p for p in found[ids[1]])
        assert any("nie ma kontraktu" in p for p in found[ids[2]])
        assert any("nie jest w NEXUSIE numerem" in p for p in found[ids[2]])

        recruiter = await sales_client.get(
            f"{SALES}/form-checks",
            params={"year": 2026, "month": 10},
            headers=_h(seed, "recruiter"),
        )
        assert recruiter.status_code == 403
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSalesInvoice).where(ClientSalesInvoice.id.in_(ids))
            )
            await db.commit()


async def _contract_of(client_id: int, first: str) -> int:
    from sqlalchemy import select

    from app.models.candidate import Candidate
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(Contract.id)
            .join(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.client_id == client_id, Candidate.name == first)
        )


@pytest.mark.parametrize("state", ["rejected", "confirmed"])
async def test_rejected_person_code_does_not_count(sales_client, seed, rules, state):
    from app.models.client_time_report import ClientExternalId

    await rules({"cl.contractor_person_id": {"level": "warn"}})
    contract_id = await _contract_of(seed.client_id, "Jan")
    async with AsyncSessionLocal() as db:
        code = ClientExternalId(
            client_id=seed.client_id,
            contract_id=contract_id,
            kind="client_person_no",
            value="A123456",
            source="manual",
            state=state,
        )
        invoice = _ksef_invoice(
            seed.client_id,
            9201,
            [{"name": "Contractor Jan Przykładowy ID: A123456", "quantity": "1"}],
        )
        db.add_all([code, invoice])
        await db.commit()
        ids = (code.id, invoice.id)
    try:
        response = await sales_client.get(
            f"{SALES}/form-checks",
            params={"year": 2026, "month": 10},
            headers=_h(seed),
        )
        assert response.status_code == 200, response.text
        found = {
            row["invoice_id"]: row["problems"] for row in response.json()["invoices"]
        }
        if state == "rejected":
            assert any("NEXUS nie zna kodu A123456" in p for p in found[ids[1]])
        else:
            assert ids[1] not in found
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ClientSalesInvoice).where(ClientSalesInvoice.id == ids[1])
            )
            await db.execute(
                delete(ClientExternalId).where(ClientExternalId.id == ids[0])
            )
            await db.commit()
