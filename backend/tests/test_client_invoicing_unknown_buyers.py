"""Finanse → „Nieznani nabywcy” i ramka faktur w formularzu klienta (C5). Dane fikcyjne."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

from app.api import client_sales_invoices as api
from app.api import clients as clients_api
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.client_sales_invoice import ClientSalesInvoice
from app.models.critical_event import CriticalEvent
from app.services.client_invoicing import sync
from tests.client_invoicing import helpers as fx

pytestmark = pytest.mark.asyncio

FINANCE = "/api/finance/sales-invoices"
CLIENTS = "/api/clients"
BUYERS = f"{FINANCE}/unknown-buyers"
NIP = fx.UNKNOWN_NIP


@pytest_asyncio.fixture
async def client():
    target = FastAPI()
    target.include_router(api.finance_router, prefix=FINANCE)
    target.include_router(api.router, prefix=CLIENTS)
    async with AsyncClient(
        transport=ASGITransport(app=target), base_url="http://testserver"
    ) as http:
        yield http


@pytest_asyncio.fixture
async def seed(monkeypatch):
    monkeypatch.setattr(settings, "KSEF_MODE", "simulate")
    monkeypatch.setattr(settings, "KSEF_CONTEXT_NIP", fx.COMPANY_NIP)
    monkeypatch.setattr(settings, "KSEF_SIMULATE_DIR", str(fx.DATA_DIR.parent))
    data = await fx.seed_month()
    await fx.set_module(True)
    async with AsyncSessionLocal() as db:
        await sync.run_once(db, now=datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc))
    yield data
    await fx.wipe()
    await fx.set_module(None)


async def _sibling(*, issue_date: date, net: str, currency: str = "PLN") -> int:
    async with AsyncSessionLocal() as db:
        source = await db.scalar(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.ksef_number == fx.KSEF_UNKNOWN
            )
        )
        values = {
            column.name: getattr(source, column.name)
            for column in ClientSalesInvoice.__table__.columns
            if column.name not in {"id", "created_at", "updated_at"}
        }
        values.update(
            ksef_number=f"{fx.COMPANY_NIP}-20261105-{uuid.uuid4().hex[:12].upper()}-AA",
            invoice_number=f"FS {uuid.uuid4().hex[:6]}",
            issue_date=issue_date,
            net_amount=Decimal(net),
            currency=currency,
            match_status="unmatched",
            match_reason="unknown_buyer",
            client_id=None,
        )
        sibling = ClientSalesInvoice(**values)
        db.add(sibling)
        await db.commit()
        return sibling.id


async def _new_client(legal_name: str | None = None, nip: str | None = None) -> int:
    async with AsyncSessionLocal() as db:
        client_id = await fx.client(db, "Nabywca Spółka", nip)
        (await db.get(Client, client_id)).legal_name = legal_name
        await db.commit()
    return client_id


async def _unique_buyer_name() -> str:
    """Nazwa nabywcy jedyna w bazie: inaczej trafia w klientów z wcześniejszych biegów."""

    name = f"Nabywca {uuid.uuid4().hex[:10]} S.A."
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ClientSalesInvoice)
            .where(ClientSalesInvoice.ksef_number == fx.KSEF_UNKNOWN)
            .values(buyer_name=name)
        )
        await db.commit()
    return name


async def _buyers(client, seed, *, user: str = "finance") -> dict:
    response = await client.get(BUYERS, headers=fx.headers(seed.users[user]))
    assert response.status_code == 200, response.text
    return response.json()


def _row(payload: dict, number: str = NIP) -> dict:
    return next(row for row in payload["buyers"] if row["number"] == number)


async def test_groups_all_months_by_number_with_totals(client, seed):
    await _sibling(issue_date=date(2026, 8, 3), net="100.00")
    await _sibling(issue_date=date(2026, 9, 3), net="50.00", currency="EUR")

    payload = await _buyers(client, seed, user="admin")

    row = _row(payload)
    assert row["invoices"] == 3
    assert row["first_date"] == "2026-08-03"
    assert row["kind"] == "nip"
    assert {total["currency"] for total in row["totals"]} == {"PLN", "EUR"}
    assert payload["summary"]["invoices"] >= 3


async def test_suggestion_only_when_one_client_has_that_name(client, seed):
    name = await _unique_buyer_name()
    await _new_client(legal_name=name)
    assert _row(await _buyers(client, seed))["suggestion"]["state"] == "add"

    await _new_client(legal_name=name)
    assert _row(await _buyers(client, seed))["suggestion"] is None


async def test_assign_saves_number_and_links_every_invoice(client, seed):
    await _sibling(issue_date=date(2026, 9, 3), net="100.00")
    client_id = await _new_client()

    response = await client.post(
        f"{BUYERS}/assign",
        json={"number": NIP, "client_id": client_id},
        headers=fx.headers(seed.users["finance"]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["buyer_number"]["saved"] is True
    async with AsyncSessionLocal() as db:
        assert (await db.get(Client, client_id)).nip == NIP
        waiting = await db.scalars(
            select(ClientSalesInvoice).where(
                ClientSalesInvoice.buyer_nip == NIP,
                ClientSalesInvoice.client_id.is_(None),
            )
        )
        assert list(waiting) == []
        events = await db.scalars(
            select(CriticalEvent).where(CriticalEvent.client_id == client_id)
        )
        assert len(list(events)) == 1


async def test_assign_refuses_client_with_another_number(client, seed):
    client_id = await _new_client(nip=fx.OTHER_CLIENT_NIP)

    response = await client.post(
        f"{BUYERS}/assign",
        json={"number": NIP, "client_id": client_id},
        headers=fx.headers(seed.users["finance"]),
    )

    assert response.status_code == 409
    assert "inny numer" in response.json()["detail"]


async def test_skip_ignores_every_waiting_invoice_with_reason(client, seed):
    await _sibling(issue_date=date(2026, 9, 3), net="100.00")

    response = await client.post(
        f"{BUYERS}/skip",
        json={"number": NIP, "reason": "Sprzedaż sprzętu"},
        headers=fx.headers(seed.users["finance"]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["skipped"] == 2
    assert all(row["number"] != NIP for row in (await _buyers(client, seed))["buyers"])


async def test_skip_needs_a_reason(client, seed):
    response = await client.post(
        f"{BUYERS}/skip",
        json={"number": NIP, "reason": "x"},
        headers=fx.headers(seed.users["finance"]),
    )
    assert response.status_code == 422


async def test_assign_and_skip_unknown_number_are_404(client, seed):
    client_id = await _new_client()
    response = await client.post(
        f"{BUYERS}/assign",
        json={"number": "9999999999", "client_id": client_id},
        headers=fx.headers(seed.users["finance"]),
    )
    assert response.status_code == 404


async def test_totals_hidden_without_company_results(client, seed):
    summary = (await _buyers(client, seed))["summary"]
    assert summary["totals"] == []
    assert summary["totals_hidden"] is True


@pytest.mark.parametrize("user", ["recruiter", "dl", "tcm"])
async def test_refused_outside_finance_module(client, seed, user):
    headers = fx.headers(seed.users[user])

    assert (await client.get(BUYERS, headers=headers)).status_code == 403
    assert (
        await client.post(
            f"{BUYERS}/skip", json={"number": NIP, "reason": "abc"}, headers=headers
        )
    ).status_code == 403


async def test_module_off_hides_the_queue_from_finance(client, seed):
    await fx.set_module(False)
    response = await client.get(BUYERS, headers=fx.headers(seed.users["finance"]))
    assert response.status_code == 404


async def test_frame_counts_invoices_waiting_for_the_number(client, seed):
    await _sibling(issue_date=date(2026, 9, 3), net="100.00")

    response = await client.get(
        f"{CLIENTS}/{seed.client_id}/invoicing/waiting-for-number",
        params={"number": "333-333-33-33"},
        headers=fx.headers(seed.users["finance"]),
    )

    assert response.status_code == 200, response.text
    assert response.json()["number"] == NIP
    assert response.json()["invoices"] == 2


async def test_frame_is_finance_only_even_for_dl_of_this_client(client, seed):
    """Numer nie jest związany z klientem: DL czytałby nim faktury cudzych firm."""

    url = f"{CLIENTS}/{seed.client_id}/invoicing/waiting-for-number"
    for user in ("dl", "other_dl", "recruiter"):
        response = await client.get(
            url, params={"number": NIP}, headers=fx.headers(seed.users[user])
        )
        assert response.status_code == 403, user


async def test_taken_nip_is_refused_and_own_number_passes(seed):
    async with AsyncSessionLocal() as db:
        client = await db.get(Client, await _new_client())
        with pytest.raises(HTTPException) as refused:
            await clients_api._refuse_taken_nip(db, client, {"nip": fx.CLIENT_NIP})
        assert refused.value.status_code == 409
        assert await clients_api._refuse_taken_nip(db, client, {"nip": NIP}) is True
        assert await clients_api._refuse_taken_nip(db, client, {"nip": None}) is False
        assert await clients_api._refuse_taken_nip(db, client, {}) is False


async def test_new_nip_links_waiting_invoices_at_once(seed):
    client_id = await _new_client()
    async with AsyncSessionLocal() as db:
        await db.execute(update(Client).where(Client.id == client_id).values(nip=NIP))
        await db.flush()
        await clients_api._match_invoices_waiting_for_nip(db, NIP)
        await db.commit()
    assert (await fx.invoice(fx.KSEF_UNKNOWN)).client_id == client_id


async def test_module_off_leaves_invoices_alone_on_nip_change(seed):
    await fx.set_module(False)
    client_id = await _new_client()
    async with AsyncSessionLocal() as db:
        await db.execute(update(Client).where(Client.id == client_id).values(nip=NIP))
        await db.flush()
        await clients_api._match_invoices_waiting_for_nip(db, NIP)
        await db.commit()
    assert (await fx.invoice(fx.KSEF_UNKNOWN)).client_id is None
