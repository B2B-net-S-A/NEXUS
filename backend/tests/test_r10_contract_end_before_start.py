"""Runda 10 (F27): koniec współpracy przed startem kontraktu jest odrzucany.

Na produkcji „Zakończ współpracę” z domyślną datą „dziś” na kontrakcie
startującym 01.11.2026 zapisał okres „01.11.2026–27.09.2026”, status
„Kończący się” i anulował planowane zamówienie. Teraz 422 po polsku i ZERO
zmian — kontrakt i zamówienia zostają takie, jakie były. Dzień startu jest
poprawnym dniem zakończenia (jednodniowy projekt).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from httpx import AsyncClient

from app.api.contracts import END_BEFORE_START_REASON, _reject_end_before_start
from app.core.scheduling import business_today


def test_end_before_start_is_rejected_with_polish_message():
    with pytest.raises(HTTPException) as exc:
        _reject_end_before_start(date(2026, 11, 1), date(2026, 9, 27), termination=True)
    assert exc.value.status_code == 422
    detail = exc.value.detail
    assert detail["code"] == END_BEFORE_START_REASON
    assert "27.09.2026" in detail["message"]
    assert "1.11.2026" in detail["message"]
    assert "unieważnij" in detail["message"]


@pytest.mark.parametrize(
    "start,end",
    [
        (date(2026, 11, 1), date(2026, 11, 1)),  # dzień startu
        (date(2026, 11, 1), date(2026, 11, 2)),
        (None, date(2026, 9, 27)),
        (date(2026, 11, 1), None),
    ],
)
def test_end_on_or_after_start_passes(start, end):
    _reject_end_before_start(start, end, termination=False)


async def _seed_future_contract() -> tuple[int, int]:
    """Kontrakt startujący za 35 dni, bezterminowy, z planowanym zamówieniem."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.client_order import ClientOrder, ClientOrderStatus
    from app.models.contract import Contract, ContractStatus

    start = business_today() + timedelta(days=35)
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Przyszly",
            lastname=f"Start-{uuid.uuid4().hex[:6]}",
            email=f"r10-f27-{uuid.uuid4().hex[:8]}@example.com",
        )
        client = Client(name=f"R10F27-{uuid.uuid4().hex[:6]}")
        db.add_all([cand, client])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            status=ContractStatus.active,
            start_date=start,
            end_date=None,
            rate_candidate=Decimal("100.000"),
            rate_client=Decimal("150.000"),
        )
        db.add(contract)
        await db.flush()
        order = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"R10-F27-{uuid.uuid4().hex[:6]}",
            status=ClientOrderStatus.active,
            start_date=start,
            end_date=start + timedelta(days=29),
        )
        db.add(order)
        await db.commit()
        return contract.id, order.id


async def _state(contract_id: int, order_id: int) -> tuple:
    from app.core.database import AsyncSessionLocal
    from app.models.client_order import ClientOrder
    from app.models.contract import Contract

    async with AsyncSessionLocal() as db:
        contract = await db.get(Contract, contract_id)
        order = await db.get(ClientOrder, order_id)
        return (
            contract.status,
            contract.start_date,
            contract.end_date,
            contract.terminated_at,
            order.status,
            order.end_date,
        )


async def test_terminate_before_start_is_refused_without_side_effects(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid, oid = await _seed_future_contract()
    before = await _state(cid, oid)
    r = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": business_today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == END_BEFORE_START_REASON
    assert await _state(cid, oid) == before


async def test_bulk_mark_ended_before_start_refuses_whole_batch(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid, oid = await _seed_future_contract()
    before = await _state(cid, oid)
    r = await app_client.post(
        f"/api/contracts/bulk-mark-ended?ids={cid}",
        json={
            "termination_reason": "project_ended",
            "terminated_at": business_today().isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert await _state(cid, oid) == before


async def test_terminate_on_start_day_is_accepted(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid, oid = await _seed_future_contract()
    start = (await _state(cid, oid))[1]
    r = await app_client.post(
        f"/api/contracts/{cid}/terminate",
        json={
            "termination_reason": "project_ended",
            "terminated_at": start.isoformat(),
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["end_date"] == start.isoformat()


async def test_patch_end_date_before_start_is_refused(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid, oid = await _seed_future_contract()
    before = await _state(cid, oid)
    r = await app_client.patch(
        f"/api/contracts/{cid}",
        json={"end_date": business_today().isoformat()},
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == END_BEFORE_START_REASON
    assert await _state(cid, oid) == before
