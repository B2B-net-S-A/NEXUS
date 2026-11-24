"""„Nowy kontraktor / zamówienie” (Flow B) z blokadą duplikatu kontraktora.

Audyt r5 (25.11.2026): ``POST /api/clients/{id}/contract-with-order`` zakładał
kontrakt bez sprawdzenia, czy ta osoba ma już żywy kontrakt u tego klienta.
Pozostałe wejścia (``POST /api/contracts``, generator B2B) odpowiadają wtedy
409 ``duplicate_contractor`` — Flow B ma tę samą bramkę, przed pierwszym
zapisem, więc odmowa nie zostawia ani kontraktu, ani zamówienia. Po ``ended``
i ``void`` nowa umowa jest dozwolona (powrót po przerwie). Dane fikcyjne.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder
from app.models.contract import Contract, ContractStatus
from tests._contract_parties import pick_parties

pytestmark = pytest.mark.asyncio


async def _seed_existing(status: ContractStatus) -> tuple[int, int, int]:
    """Para kandydat + klient z jednym kontraktem w danym statusie."""
    from app.core.database import AsyncSessionLocal

    candidate_id, client_id = await pick_parties()
    today = business_today()
    async with AsyncSessionLocal() as db:
        contract = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            status=status,
            start_date=today - timedelta(days=200),
            end_date=(
                today - timedelta(days=30)
                if status in (ContractStatus.ended, ContractStatus.void)
                else None
            ),
            rate_candidate=120,
            rate_client=150,
        )
        db.add(contract)
        await db.commit()
        return candidate_id, client_id, contract.id


async def _counts(client_id: int) -> tuple[int, int]:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        contracts = await db.scalar(
            select(func.count()).where(Contract.client_id == client_id)
        )
        orders = await db.scalar(
            select(func.count()).where(ClientOrder.client_id == client_id)
        )
        return int(contracts or 0), int(orders or 0)


def _payload(candidate_id: int) -> dict:
    today = business_today()
    return {
        "candidate_id": candidate_id,
        "title": "ZAM-TEST/1",
        "contract_start_date": today.isoformat(),
        "order_start_date": today.isoformat(),
        "order_end_date": (today + timedelta(days=90)).isoformat(),
        "rate_client": "150",
        "rate_candidate": "120",
        "rate_unit": "hourly",
    }


@pytest.mark.parametrize("status", [ContractStatus.active, ContractStatus.draft])
async def test_live_contract_of_the_person_refuses_flow_b(
    app_client: AsyncClient, app_auth_headers: dict, status: ContractStatus
):
    candidate_id, client_id, existing_id = await _seed_existing(status)

    resp = await app_client.post(
        f"/api/clients/{client_id}/contract-with-order",
        json=_payload(candidate_id),
        headers=app_auth_headers,
    )

    assert resp.status_code == 409, resp.text
    detail = resp.json()["detail"]
    assert detail["code"] == "duplicate_contractor"
    assert detail["existing_contract_id"] == existing_id
    # Zero nowych wierszy: jest tylko kontrakt z seeda, zamówień brak.
    assert await _counts(client_id) == (1, 0)


@pytest.mark.parametrize("status", [ContractStatus.ended, ContractStatus.void])
async def test_ended_or_void_contract_allows_a_new_one(
    app_client: AsyncClient, app_auth_headers: dict, status: ContractStatus
):
    candidate_id, client_id, _ = await _seed_existing(status)

    resp = await app_client.post(
        f"/api/clients/{client_id}/contract-with-order",
        json=_payload(candidate_id),
        headers=app_auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert await _counts(client_id) == (2, 1)
