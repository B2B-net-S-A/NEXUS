"""Finanse zmieniają kwoty kontraktów i zamówień (decyzja Artura 22.09.2026).

Trasy mieszane (PATCH kontraktu, PATCH zamówienia) wpuszczają osobę z samym
``MANAGE_FINANCE`` wyłącznie po to, żeby zmieniła KWOTY. Pozostałe pola
(status, daty, tytuł) zostają przy rolach operacyjnych trasy.

In-process `app_client`; baza testowa wspólna i nieczyszczona — asercje tylko
na własnych wierszach.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _finance_headers(app_client: AsyncClient) -> dict:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"finance-amounts-{unique}@example.com"
    password = f"T3st_{unique}!Fin"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Finance amounts",
                role=UserRole.finance,
                roles=["finance"],
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _seed_contract_with_order() -> tuple[int, int, int]:
    from app.models.client import Client
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract, ContractStatus, ContractType

    async with AsyncSessionLocal() as db:
        client = Client(name=f"FinanceAmounts-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        contract = Contract(
            client_id=client.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.draft,
            rate_candidate=Decimal("100"),
            rate_client=Decimal("150"),
            start_date=date(2026, 10, 1),
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"FIN-{uuid.uuid4().hex[:6]}",
            rate_client=Decimal("150"),
            rate_candidate=Decimal("100"),
        )
        db.add(order)
        await db.commit()
        return client.id, contract.id, order.id


@pytest.mark.asyncio
async def test_finance_changes_contract_and_order_amounts_but_nothing_else(
    app_client: AsyncClient,
):
    headers = await _finance_headers(app_client)
    client_id, contract_id, order_id = await _seed_contract_with_order()

    contract = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers,
        json={"rate_client": 175},
    )
    assert contract.status_code == 200, contract.text
    assert float(contract.json()["rate_client"]) == 175.0

    contract_other = await app_client.patch(
        f"/api/contracts/{contract_id}",
        headers=headers,
        json={"end_date": "2026-12-31"},
    )
    assert contract_other.status_code == 403, contract_other.text
    assert contract_other.json()["detail"]["code"] == "finance_amounts_only"

    order = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        headers=headers,
        json={"rate_client": 180},
    )
    assert order.status_code == 200, order.text

    order_other = await app_client.patch(
        f"/api/clients/{client_id}/orders/{order_id}",
        headers=headers,
        json={"title": "Zmieniony tytuł"},
    )
    assert order_other.status_code == 403, order_other.text
    assert order_other.json()["detail"]["code"] == "finance_amounts_only"
