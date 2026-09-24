"""Historia zamówienia MD/kosztowego nazywa wykonawcę operacji (UAT B50).

Do 09.2026 wpis niósł datę, typ i opis, a autora tylko jako `created_by_user_id`
— front nie miał czego pokazać i nie dało się ustalić, kto zmienił budżet.
Dane syntetyczne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today

pytestmark = pytest.mark.asyncio


async def _seed() -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, RateUnit

    suffix = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Autor-{suffix}")
        db.add(client)
        await db.flush()
        candidate = Candidate(
            name="Halina",
            lastname=f"Autorska{suffix}",
            email=f"aut-{suffix}@example.com",
        )
        db.add(candidate)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=business_today() - timedelta(days=200),
            rate_candidate=Decimal("700.000"),
            rate_unit=RateUnit.daily,
        )
        db.add(contract)
        await db.flush()
        await db.commit()
        return client.id, contract.id


async def test_history_entries_carry_the_author_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id, contract_id = await _seed()
    created = await app_client.post(
        f"/api/clients/{client_id}/order-groups",
        json={
            "order_number": f"SAP 45{uuid.uuid4().int % 10**8:08d}",
            "start_date": (business_today() - timedelta(days=100)).isoformat(),
            "order_type": "cost",
            "is_cost_based": True,
            "budget_amount": 40000,
            "lines": [
                {
                    "contract_id": contract_id,
                    "rate_cost": 700,
                    "rate_revenue": 1280,
                    "start_date": (business_today() - timedelta(days=100)).isoformat(),
                }
            ],
        },
        headers=app_auth_headers,
    )
    assert created.status_code == 201, created.text
    group_id = created.json()["id"]

    me = await app_client.get("/api/auth/me", headers=app_auth_headers)
    assert me.status_code == 200, me.text

    events = await app_client.get(
        f"/api/clients/{client_id}/order-groups/{group_id}/events",
        headers=app_auth_headers,
    )
    assert events.status_code == 200, events.text
    rows = events.json()["events"]
    assert rows, "utworzenie zamówienia musi zostawić wpis w historii"
    for row in rows:
        assert row["created_by_user_id"] == me.json()["id"]
        # Nazwa wykonawcy jedzie OBOK identyfikatora — front nie zgaduje jej
        # z listy użytkowników, do której rola bez uprawnień nie ma dostępu.
        assert row["created_by_name"] == me.json()["name"]
