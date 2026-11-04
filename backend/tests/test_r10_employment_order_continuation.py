"""Runda 10 (F24): bieżące zamówienie + przyszłe przedłużenie to nie duplikat.

Produkcja (fikcyjne dane Codexa): „Zatrudniony” ostrzegał „Nie założono szkicu
kontraktu — więcej niż jedno otwarte zamówienie, zamknij duplikaty”, choć
kontrakt miał bieżące 01.10–31.12.2026 i przyszłe 01.01–31.03.2027 — okresy
rozłączne. Hook zamówienia rozpoznaje teraz kontynuację (zwraca bieżące
zamówienie), a 409 zostaje wyłącznie dla nachodzących okresów.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.services.b2b_contract_automation import (
    _current_of_chain,
    _overlapping_open_orders,
)


def _order(order_id: int, start: date | None, end: date | None) -> ClientOrder:
    order = ClientOrder(
        title=f"Z-{order_id}",
        status=ClientOrderStatus.active,
        start_date=start,
        end_date=end,
    )
    order.id = order_id
    return order


def test_disjoint_chain_is_not_a_duplicate_and_current_wins():
    today = business_today()
    current = _order(733, today - timedelta(days=10), today + timedelta(days=20))
    future = _order(734, today + timedelta(days=21), today + timedelta(days=110))
    assert _overlapping_open_orders([future, current]) == []
    assert _current_of_chain([future, current]) is current


def test_future_only_chain_returns_the_nearest_start():
    today = business_today()
    near = _order(1, today + timedelta(days=5), today + timedelta(days=30))
    far = _order(2, today + timedelta(days=31), today + timedelta(days=60))
    assert _current_of_chain([far, near]) is near


def test_overlapping_orders_are_duplicates():
    today = business_today()
    a = _order(1, today, today + timedelta(days=60))
    b = _order(2, today + timedelta(days=30), today + timedelta(days=90))
    undated = _order(3, None, None)
    assert {o.id for o in _overlapping_open_orders([a, b])} == {1, 2}
    assert {o.id for o in _overlapping_open_orders([a, undated])} == {1, 3}


@pytest.mark.asyncio
async def test_ensure_open_order_accepts_current_plus_future_extension():
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus, ContractType
    from app.models.job import Job, JobStatus
    from app.services.b2b_contract_automation import _ensure_open_order

    suffix = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R10 F24 {suffix}")
        candidate = Candidate(name=f"Ala{suffix}", lastname=f"Test{suffix}")
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"R10 F24 {suffix}", client_id=client.id, status=JobStatus.published
        )
        db.add(job)
        await db.flush()
        contract = Contract(
            candidate_id=candidate.id,
            client_id=client.id,
            job_id=job.id,
            contract_type=ContractType.b2b,
            status=ContractStatus.active,
            start_date=today - timedelta(days=30),
            rate_candidate=Decimal("100.000"),
        )
        db.add(contract)
        await db.flush()
        current = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            job_id=job.id,
            title=f"R10-733-{suffix}",
            status=ClientOrderStatus.active,
            start_date=today - timedelta(days=30),
            end_date=today + timedelta(days=30),
        )
        future = ClientOrder(
            client_id=client.id,
            contract_id=contract.id,
            title=f"R10-734-{suffix}",
            status=ClientOrderStatus.active,
            start_date=today + timedelta(days=31),
            end_date=today + timedelta(days=120),
        )
        db.add_all([current, future])
        await db.flush()

        order, created, skipped = await _ensure_open_order(
            db,
            contract=contract,
            candidate=candidate,
            job=job,
            actor_id=None,
            source="pipeline_hired",
        )
        assert (order.id, created, skipped) == (current.id, False, None)
        # Przedłużenie bez rekrutacji dostaje tę samą rekrutację.
        assert future.job_id == job.id

        # Nachodzące zamówienie = prawdziwy duplikat → 409 jak dotąd.
        db.add(
            ClientOrder(
                client_id=client.id,
                contract_id=contract.id,
                title=f"R10-DUP-{suffix}",
                status=ClientOrderStatus.active,
                start_date=today,
                end_date=today + timedelta(days=10),
            )
        )
        await db.flush()
        with pytest.raises(HTTPException) as exc:
            await _ensure_open_order(
                db,
                contract=contract,
                candidate=candidate,
                job=job,
                actor_id=None,
                source="pipeline_hired",
            )
        assert exc.value.status_code == 409
        await db.rollback()
