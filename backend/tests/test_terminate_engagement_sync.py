"""Zakończenie projektu synchronizuje kontrakt i jego zamówienia (ticket #5).

Contract.end_date i ClientOrder.end_date to osobne kolumny skanowane przez dwa
niezależne demony — POST /contracts/{id}/terminate ustawia teraz JEDNĄ datę
w obu modelach:
- zamówienie startujące po dacie końca → cancelled,
- otwarte zamówienia → end_date = data zakończenia; completed dopiero gdy data
  nadeszła (przyszłą materializuje dzienny skaner — semantyka P0.7 kontraktu),
- identyczny replay → bez drugiej Activity (idempotencja double-submitu).
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus

pytestmark = pytest.mark.asyncio


async def _seed_with_orders():
    suffix = uuid.uuid4().hex[:8]
    today = date.today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Term Sync Client {suffix}")
        cand = Candidate(name=f"Term {suffix}", lastname=f"Sync{suffix}")
        db.add_all([client, cand])
        await db.flush()
        contract = Contract(
            candidate_id=cand.id,
            client_id=client.id,
            start_date=today - timedelta(days=90),
            end_date=today + timedelta(days=90),
            rate_client=15000,
            rate_candidate=12000,
            status=ContractStatus.active,
        )
        db.add(contract)
        await db.flush()
        db.add_all(
            [
                # Bieżące aktywne zamówienie.
                ClientOrder(
                    client_id=client.id,
                    contract_id=contract.id,
                    title="biezace",
                    status=ClientOrderStatus.active,
                    start_date=today - timedelta(days=30),
                    end_date=today + timedelta(days=90),
                ),
                # Przyszłe przedłużenie — startuje PO dacie zakończenia.
                ClientOrder(
                    client_id=client.id,
                    contract_id=contract.id,
                    title="przyszle",
                    status=ClientOrderStatus.active,
                    start_date=today + timedelta(days=60),
                ),
                # Draft bez daty startu.
                ClientOrder(
                    client_id=client.id,
                    contract_id=contract.id,
                    title="draft",
                    status=ClientOrderStatus.draft,
                ),
                # Już zakończone — sync nie może go ruszyć.
                ClientOrder(
                    client_id=client.id,
                    contract_id=contract.id,
                    title="zakonczone",
                    status=ClientOrderStatus.completed,
                    start_date=today - timedelta(days=400),
                    end_date=today - timedelta(days=300),
                ),
            ]
        )
        ids = (client.id, cand.id, contract.id)
        await db.commit()
        return ids


async def _orders_by_title(client_id: int) -> dict[str, ClientOrder]:
    async with AsyncSessionLocal() as db:
        rows = (
            (
                await db.execute(
                    select(ClientOrder).where(ClientOrder.client_id == client_id)
                )
            )
            .scalars()
            .all()
        )
        return {o.title: o for o in rows}


async def _cleanup(client_id: int, cand_id: int, contract_id: int) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            Activity.__table__.delete().where(
                Activity.entity_type == "contract",
                Activity.entity_id == contract_id,
            )
        )
        await db.execute(
            ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
        )
        await db.execute(
            Contract.__table__.delete().where(Contract.client_id == client_id)
        )
        await db.execute(Client.__table__.delete().where(Client.id == client_id))
        await db.execute(Candidate.__table__.delete().where(Candidate.id == cand_id))
        await db.commit()


async def _terminated_activity_count(contract_id: int) -> int:
    async with AsyncSessionLocal() as db:
        return (
            await db.scalar(
                select(func.count())
                .select_from(Activity)
                .where(
                    Activity.entity_type == "contract",
                    Activity.entity_id == contract_id,
                    Activity.action == "terminated",
                )
            )
        ) or 0


async def test_terminate_today_syncs_orders(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id, cand_id, contract_id = await _seed_with_orders()
    today = date.today()
    try:
        resp = await app_client.post(
            f"/api/contracts/{contract_id}/terminate",
            json={
                "termination_reason": "project_ended",
                "terminated_at": today.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        orders = await _orders_by_title(client_id)
        # Bieżące: JEDNA data w obu modelach + completed (data nadeszła).
        assert orders["biezace"].status == ClientOrderStatus.completed
        assert orders["biezace"].end_date == today
        # Przyszłe przedłużenie nigdy nie ruszy → cancelled.
        assert orders["przyszle"].status == ClientOrderStatus.cancelled
        # Draft (bez startu) domyka się tą samą datą.
        assert orders["draft"].status == ClientOrderStatus.completed
        assert orders["draft"].end_date == today
        # Historyczne nietknięte.
        assert orders["zakonczone"].end_date == today - timedelta(days=300)

        async with AsyncSessionLocal() as db:
            contract = await db.scalar(
                select(Contract).where(Contract.id == contract_id)
            )
            assert contract is not None
            assert contract.end_date == today
            assert contract.status == ContractStatus.ended

        # Idempotentny replay: identyczna dyspozycja bez drugiej Activity.
        assert await _terminated_activity_count(contract_id) == 1
        replay = await app_client.post(
            f"/api/contracts/{contract_id}/terminate",
            json={
                "termination_reason": "project_ended",
                "terminated_at": today.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert replay.status_code == 200
        assert await _terminated_activity_count(contract_id) == 1
    finally:
        await _cleanup(client_id, cand_id, contract_id)


async def test_future_dated_terminate_keeps_order_running_until_date(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id, cand_id, contract_id = await _seed_with_orders()
    when = date.today() + timedelta(days=14)
    try:
        resp = await app_client.post(
            f"/api/contracts/{contract_id}/terminate",
            json={
                "termination_reason": "project_ended",
                "terminated_at": when.isoformat(),
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        orders = await _orders_by_title(client_id)
        # Data przyszła: koniec ZAPISANY, ale zamówienie biegnie do tej daty
        # (konsultant nie znika z Obecnych) — completed zmaterializuje skaner.
        assert orders["biezace"].status == ClientOrderStatus.active
        assert orders["biezace"].end_date == when
        # Przedłużenie startujące PO dacie końca → cancelled już teraz.
        assert orders["przyszle"].status == ClientOrderStatus.cancelled

        async with AsyncSessionLocal() as db:
            contract = await db.scalar(
                select(Contract).where(Contract.id == contract_id)
            )
            assert contract is not None
            # Lustrzana semantyka P0.7 — kontrakt nie flipuje na ended dziś.
            assert contract.status != ContractStatus.ended
            assert contract.end_date == when
    finally:
        await _cleanup(client_id, cand_id, contract_id)
