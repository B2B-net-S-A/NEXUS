"""Runda 10 (F15): przedłużenie nie może nakładać się na zamówienie tej osoby.

Produkcja (fikcyjne dane Codexa): kontrakt ma zamówienie 01.10–31.12.2026,
„Dodaj przedłużenie” 01.12.2026–31.03.2027 z innym numerem zapisało się bez
słowa — grudzień był w dwóch zamówieniach. Teraz 409 ``overlapping_order``
po polsku; przedłużenie od następnego dnia przechodzi, a PATCH dat nie może
zrobić z dwóch zamówień równoległych.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, ContractType, RateUnit

pytestmark = pytest.mark.asyncio


async def _seed() -> tuple[int, int, date, date]:
    """Kontrakt z aktywnym zamówieniem [dziś − 30, dziś + 60]."""
    suffix = uuid.uuid4().hex[:8]
    today = business_today()
    start, end = today - timedelta(days=30), today + timedelta(days=60)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R10 F15 {suffix}")
        candidate = Candidate(name=f"Ola{suffix}", lastname=f"Test{suffix}")
        db.add_all([client, candidate])
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=today - timedelta(days=100),
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
            rate_unit=RateUnit.hourly,
            currency="PLN",
            rate_candidate_currency="PLN",
        )
        db.add(contract)
        await db.flush()
        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                title=f"R10-BIEZACE-{suffix}",
                order_type="periodic",
                status=ClientOrderStatus.active,
                start_date=start,
                end_date=end,
                rate_client=Decimal("150.000"),
            )
        )
        await db.commit()
        return client.id, contract.id, start, end


def _form(contract_id: int, start: date, end: date) -> dict[str, str]:
    return {
        "contract_id": str(contract_id),
        "title": f"R10-PRZEDL-{uuid.uuid4().hex[:6]}",
        "order_type": "periodic",
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "rate_client": "165.50",
    }


async def _count_orders(contract_id: int) -> int:
    from sqlalchemy import func, select

    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(func.count(ClientOrder.id)).where(
                ClientOrder.contract_id == contract_id
            )
        )


async def test_overlapping_extension_is_refused_in_polish(app_client, app_auth_headers):
    client_id, contract_id, _start, end = await _seed()
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(contract_id, end - timedelta(days=30), end + timedelta(days=90)),
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "overlapping_order"
    assert "równoległych" in detail["message"]
    assert (end + timedelta(days=1)).strftime("%d.%m.%Y") in detail["message"]
    assert await _count_orders(contract_id) == 1


async def test_extension_from_the_next_day_is_accepted(app_client, app_auth_headers):
    client_id, contract_id, _start, end = await _seed()
    resp = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(contract_id, end + timedelta(days=1), end + timedelta(days=90)),
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert await _count_orders(contract_id) == 2


async def test_patch_that_makes_orders_overlap_is_refused(app_client, app_auth_headers):
    client_id, contract_id, _start, end = await _seed()
    created = await app_client.post(
        f"/api/clients/{client_id}/orders",
        data=_form(contract_id, end + timedelta(days=1), end + timedelta(days=90)),
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    resp = await app_client.patch(
        f"/api/clients/{client_id}/orders/{created.json()['id']}",
        json={"start_date": (end - timedelta(days=5)).isoformat()},
        headers=app_auth_headers,
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["detail"]["code"] == "overlapping_order"
