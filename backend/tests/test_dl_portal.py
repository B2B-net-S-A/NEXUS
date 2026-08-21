"""Integration tests dla DL Portal po refactor 2026-05-11 (Order:Contract 1:N).

- Order ZAWSZE pod konkretnym Contract (1:N, no M:N)
- Flow A: POST /orders pod existing Contract (extension)
- Flow B: POST /contract-with-order (atomic Contract + Order)
- Marża auto: (Order.rate_client OR Contract.rate_client) - Contract.rate_candidate

Pattern: in-process app_client / app_auth_headers (no live server).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole

pytestmark = pytest.mark.asyncio


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _new_user(role: UserRole) -> tuple[int, str, str]:
    suffix = uuid.uuid4().hex[:8]
    email = f"dlportal-{role.value}-{suffix}@example.com"
    password = f"T3st_{suffix}!Pass"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"DL portal {role.value} {suffix}",
            role=role,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.flush()
        await db.commit()
        return u.id, email, password


async def _new_client() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Client(name=f"DL Portal Client {suffix}")
        db.add(c)
        await db.flush()
        await db.commit()
        return c.id


async def _new_candidate() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        # `lastname` jest NOT NULL od migracji 0001 — brak tej wartości był
        # powodem, dla którego cały plik lądował na CI-owym --ignore.
        cand = Candidate(name=f"Test Kontraktor {suffix}", lastname=f"Testowy{suffix}")
        db.add(cand)
        await db.flush()
        await db.commit()
        return cand.id


async def _new_contract(
    client_id: int, candidate_id: int, *, rate_candidate: int = 12000
) -> int:
    async with AsyncSessionLocal() as db:
        c = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            start_date=date.today(),
            rate_client=15000,
            rate_candidate=rate_candidate,
            status=ContractStatus.active,
        )
        db.add(c)
        await db.flush()
        await db.commit()
        return c.id


async def _assign_dl(dl_id: int, client_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id,
                client_id=client_id,
                is_head=False,
            )
        )
        await db.commit()


async def _login(app_client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cleanup(
    client_ids: list[int], user_ids: list[int], candidate_ids: list[int] | None = None
) -> None:
    async with AsyncSessionLocal() as db:
        for cid in client_ids:
            await db.execute(
                ClientOrder.__table__.delete().where(ClientOrder.client_id == cid)
            )
            await db.execute(
                ClientFrameworkContract.__table__.delete().where(
                    ClientFrameworkContract.client_id == cid
                )
            )
            await db.execute(
                Contract.__table__.delete().where(Contract.client_id == cid)
            )
            await db.execute(
                DeliveryLeadClientAssignment.__table__.delete().where(
                    DeliveryLeadClientAssignment.client_id == cid
                )
            )
            await db.execute(Client.__table__.delete().where(Client.id == cid))
        if candidate_ids:
            await db.execute(
                Candidate.__table__.delete().where(Candidate.id.in_(candidate_ids))
            )
        if user_ids:
            # Order-create loguje Activity(user_id=...) — bez tego DELETE users
            # wywala FK activities_user_id_fkey.
            await db.execute(
                Activity.__table__.delete().where(Activity.user_id.in_(user_ids))
            )
            await db.execute(User.__table__.delete().where(User.id.in_(user_ids)))
        await db.commit()


# ── Framework contracts (smoke — większy refactor był w innym PR) ──────────


async def test_framework_contract_create_and_list(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client()
    try:
        resp = await app_client.post(
            f"/api/clients/{client_id}/framework-contracts",
            data={
                "name": "MSA 2026",
                "contract_status": "active",
                "effective_date": "2026-01-01",
                "expiry_date": "2026-12-31",
                "signed_via": "upload",
                "currency": "PLN",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        list_resp = await app_client.get(
            f"/api/clients/{client_id}/framework-contracts",
            headers=app_auth_headers,
        )
        assert list_resp.status_code == 200
        assert list_resp.json()["total"] == 1
    finally:
        await _cleanup([client_id], [])


# ── Flow A — Order extension pod existing Contract ─────────────────────────


async def test_order_extension_create_under_existing_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Flow A: POST /orders wymaga contract_id z tego klienta."""
    client_id = await _new_client()
    cand_id = await _new_candidate()
    contract_id = await _new_contract(client_id, cand_id)
    try:
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={
                "contract_id": str(contract_id),
                "title": "Przedłużenie Q3 2026",
                "order_status": "active",
                "start_date": "2026-07-01",
                "end_date": "2026-12-31",
                "rate_client": "17000",  # podwyżka vs Contract.rate_client=15000
                "currency": "PLN",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["contract_id"] == contract_id
        assert body["candidate_id"] == cand_id
        assert Decimal(body["rate_client"]) == Decimal(17000)
        # Marża z Order.rate_client (17000) - Contract.rate_candidate (12000) = 5000
        assert Decimal(body["monthly_margin"]) == Decimal(5000)
    finally:
        await _cleanup([client_id], [], [cand_id])


async def test_order_extension_rejects_cross_client_contract(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Contract z innego klienta → 400."""
    client_a = await _new_client()
    client_b = await _new_client()
    cand_id = await _new_candidate()
    contract_b = await _new_contract(client_b, cand_id)
    try:
        resp = await app_client.post(
            f"/api/clients/{client_a}/orders",
            data={
                "contract_id": str(contract_b),
                "title": "wrong client",
                "order_status": "draft",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 400, resp.text
    finally:
        await _cleanup([client_a, client_b], [], [cand_id])


# ── Flow B — atomic Contract + Order ───────────────────────────────────────


async def test_contract_with_order_atomic_create(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Flow B: POST /contract-with-order tworzy oba w 1 transakcji + marża auto."""
    client_id = await _new_client()
    cand_id = await _new_candidate()
    try:
        resp = await app_client.post(
            f"/api/clients/{client_id}/contract-with-order",
            json={
                "candidate_id": cand_id,
                "title": "Nowy kontraktor — Senior Java Dev",
                "contract_start_date": "2026-07-01",
                "contract_end_date": "2027-06-30",
                "order_start_date": "2026-07-01",
                "order_end_date": "2026-12-31",
                "rate_client": 18000,
                "rate_candidate": 14000,
                "rate_unit": "monthly",
                "currency": "PLN",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["contract_id"] > 0
        assert body["order_id"] > 0
        # 18000 - 14000 = 4000 monthly margin
        assert Decimal(body["monthly_margin"]) == Decimal(4000)
        async with AsyncSessionLocal() as db:
            order = await db.get(ClientOrder, body["order_id"])
            assert order is not None
            assert order.status == ClientOrderStatus.active
            assert order.filled_at is not None
    finally:
        await _cleanup([client_id], [], [cand_id])


async def test_grouped_response_shows_contract_with_orders(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """GET /orders zwraca contractors[] (1 karta = 1 Contract z timeline orderów)."""
    client_id = await _new_client()
    cand_id = await _new_candidate()
    contract_id = await _new_contract(client_id, cand_id)

    try:
        # Add 2 orders pod tym samym Contract
        async with AsyncSessionLocal() as db:
            db.add_all(
                [
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        title="Order Q1",
                        status=ClientOrderStatus.completed,
                        start_date=date(2025, 1, 1),
                        end_date=date(2025, 6, 30),
                        rate_client=15000,
                    ),
                    ClientOrder(
                        client_id=client_id,
                        contract_id=contract_id,
                        title="Order Q2 — extension",
                        status=ClientOrderStatus.active,
                        start_date=date(2025, 7, 1),
                        end_date=date(2025, 12, 31),
                        rate_client=16000,  # podwyżka
                    ),
                ]
            )
            await db.commit()

        resp = await app_client.get(
            f"/api/clients/{client_id}/orders", headers=app_auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total_contractors"] == 1
        contractor = body["contractors"][0]
        assert contractor["contract_id"] == contract_id
        assert contractor["candidate_id"] == cand_id
        assert len(contractor["orders"]) == 2
        # Latest = order najwięcej rate_client (Q2 = 16k)
        assert Decimal(contractor["latest_order_rate_client"]) == Decimal(16000)
        # Jednostka stawek kontraktu — FE etykietuje /h, /dzień, /mc z tego pola.
        assert contractor["rate_unit"] == "monthly"
    finally:
        await _cleanup([client_id], [], [cand_id])


async def test_order_rate_zero_not_masked_by_contract_rate(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Stawka 0 na Orderze jest legalna — nie może po cichu spadać do stawki
    kontraktu (`or` traktował Decimal(0) jak brak; teraz `is not None`)."""
    client_id = await _new_client()
    cand_id = await _new_candidate()
    # Contract: rate_client=15000, rate_candidate=12000 (helper).
    contract_id = await _new_contract(client_id, cand_id)

    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_id,
                    title="Order zero-rate",
                    status=ClientOrderStatus.active,
                    start_date=date(2025, 1, 1),
                    rate_client=0,
                )
            )
            await db.commit()

        resp = await app_client.get(
            f"/api/clients/{client_id}/orders", headers=app_auth_headers
        )
        assert resp.status_code == 200
        contractor = resp.json()["contractors"][0]
        # 0 zostaje 0 — bez fallbacku do 15000 z kontraktu.
        assert Decimal(contractor["latest_order_rate_client"]) == Decimal(0)
        # Marża liczona z 0: 0 - 12000 = -12000 (a nie 15000 - 12000 = 3000).
        assert Decimal(contractor["latest_order_monthly_margin"]) == Decimal(-12000)
    finally:
        await _cleanup([client_id], [], [cand_id])


# ── Permissions ─────────────────────────────────────────────────────────────


async def test_dl_unassigned_cannot_create_order(app_client: AsyncClient):
    client_id = await _new_client()
    cand_id = await _new_candidate()
    contract_id = await _new_contract(client_id, cand_id)
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={
                "contract_id": str(contract_id),
                "title": "should fail",
                "order_status": "draft",
            },
            headers=headers,
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _cleanup([client_id], [dl_id], [cand_id])


async def test_dl_assigned_can_create_order(app_client: AsyncClient):
    client_id = await _new_client()
    cand_id = await _new_candidate()
    contract_id = await _new_contract(client_id, cand_id)
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    await _assign_dl(dl_id, client_id)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={
                "contract_id": str(contract_id),
                "title": "DL assigned should pass",
                "order_status": "draft",
            },
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
    finally:
        await _cleanup([client_id], [dl_id], [cand_id])


async def test_dl_assigned_can_create_flow_b_without_finance(
    app_client: AsyncClient,
):
    client_id = await _new_client()
    cand_id = await _new_candidate()
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    await _assign_dl(dl_id, client_id)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        response = await app_client.post(
            f"/api/clients/{client_id}/contract-with-order",
            json={
                "candidate_id": cand_id,
                "title": "Operacyjny order bez finansów",
            },
            headers=headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["monthly_margin"] is None

        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, body["contract_id"])
            order = await db.get(ClientOrder, body["order_id"])
            assert contract is not None
            assert contract.status == ContractStatus.draft
            assert contract.rate_candidate is None
            assert contract.rate_client is None
            assert order is not None
            assert order.status == ClientOrderStatus.draft
            assert order.filled_at is None
            assert order.rate_client is None
            assert order.total_value is None
            assert order.currency is None
    finally:
        await _cleanup([client_id], [dl_id], [cand_id])


async def test_admin_flow_b_without_activation_fields_stays_draft(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
):
    """Flow B cannot bypass the canonical contract activation lifecycle."""

    client_id = await _new_client()
    cand_id = await _new_candidate()
    try:
        response = await app_client.post(
            f"/api/clients/{client_id}/contract-with-order",
            json={
                "candidate_id": cand_id,
                "title": "Admin order wymagający uzupełnienia",
                "rate_client": "18000",
                "rate_candidate": "14000",
                # Deliberately omit start/end and work_mode. Flow B has no
                # contract_type/work_mode fields and therefore can never prove
                # readiness for activation on create.
            },
            headers=app_auth_headers,
        )
        assert response.status_code == 201, response.text
        body = response.json()
        assert Decimal(body["monthly_margin"]) == Decimal("4000")

        async with AsyncSessionLocal() as db:
            contract = await db.get(Contract, body["contract_id"])
            order = await db.get(ClientOrder, body["order_id"])
            assert contract is not None
            assert contract.status == ContractStatus.draft
            assert contract.start_date is None
            assert contract.end_date is None
            assert contract.work_mode is None
            assert order is not None
            assert order.status == ClientOrderStatus.draft
            assert order.filled_at is None
    finally:
        await _cleanup([client_id], [], [cand_id])


# ── My clients filter (sanity) ─────────────────────────────────────────────


async def test_my_clients_admin_sees_all(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client()
    candidate_id = await _new_candidate()
    contract_id = await _new_contract(client_id, candidate_id)
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientOrder(
                    client_id=client_id,
                    contract_id=contract_id,
                    title="Admin finance visibility",
                    status=ClientOrderStatus.active,
                    start_date=date.today(),
                    total_value=Decimal("25000.00"),
                    currency="PLN",
                )
            )
            await db.commit()

        resp = await app_client.get("/api/my-clients", headers=app_auth_headers)
        assert resp.status_code == 200
        rows = resp.json()
        ids = [r["client_id"] for r in rows]
        assert client_id in ids
        row = next(r for r in rows if r["client_id"] == client_id)
        assert row["total_revenue_all_time"] is not None
        assert row["active_revenue"] is not None

        dashboard = await app_client.get(
            f"/api/my-clients/{client_id}/dashboard",
            headers=app_auth_headers,
        )
        assert dashboard.status_code == 200, dashboard.text
        body = dashboard.json()
        assert body["total_revenue_all_time"] is not None
        assert body["active_revenue"] is not None
        assert body["currency_breakdown"]
        assert body["monthly_margin_total"] is not None
    finally:
        await _cleanup([client_id], [], [candidate_id])


async def test_my_clients_dl_only_assigned(app_client: AsyncClient):
    own = await _new_client()
    other = await _new_client()
    candidate_id = await _new_candidate()
    contract_id = await _new_contract(own, candidate_id)
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    await _assign_dl(dl_id, own)
    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientOrder(
                    client_id=own,
                    contract_id=contract_id,
                    title="DL redaction",
                    status=ClientOrderStatus.active,
                    start_date=date.today(),
                    total_value=Decimal("25000.00"),
                    currency="PLN",
                )
            )
            await db.commit()

        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.get("/api/my-clients", headers=headers)
        assert resp.status_code == 200
        rows = resp.json()
        ids = [r["client_id"] for r in rows]
        assert own in ids
        assert other not in ids
        row = next(r for r in rows if r["client_id"] == own)
        assert row["active_orders_count"] == 1
        assert "total_revenue_all_time" not in row
        assert "active_revenue" not in row

        dashboard = await app_client.get(
            f"/api/my-clients/{own}/dashboard",
            headers=headers,
        )
        assert dashboard.status_code == 200, dashboard.text
        body = dashboard.json()
        assert body["active_consultants"] == 1
        assert body["active_orders_count"] == 1
        for financial_key in (
            "total_revenue_all_time",
            "active_revenue",
            "completed_revenue",
            "currency_breakdown",
            "monthly_margin_total",
            "monthly_margin_pct",
        ):
            assert financial_key not in body
    finally:
        await _cleanup([own, other], [dl_id], [candidate_id])


# ── Admin overview ──────────────────────────────────────────────────────────


async def test_admin_overview_works(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client()
    try:
        resp = await app_client.get(
            "/api/admin/clients-overview", headers=app_auth_headers
        )
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

        by_dl = await app_client.get(
            "/api/admin/clients-overview/by-dl", headers=app_auth_headers
        )
        assert by_dl.status_code == 200
        assert isinstance(by_dl.json(), list)
    finally:
        await _cleanup([client_id], [])


async def test_hired_stage_auto_creates_contract_and_order_draft(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Pipeline hook: kandydat → stage hired auto-tworzy Contract draft + Order draft.

    Po Phase 2 refactorze (pipeline.py:512-) hook tworzy oba w 1 transakcji
    z notification linkującym do tabu Zamówienia.
    """
    from app.models.contract import Contract, ContractStatus
    from app.models.job import Job
    from app.models.recruitment_pipeline import (
        CandidateStage,
        PipelineStage,
    )
    from sqlalchemy import select

    client_id = await _new_client()
    cand_id = await _new_candidate()

    # Setup Job + initial CandidateStage (pre-hired)
    async with AsyncSessionLocal() as db:
        job = Job(
            title="Test Java Dev — auto-hired",
            client_id=client_id,
            status="published",
        )
        db.add(job)
        await db.flush()

        initial_stage = CandidateStage(
            candidate_id=cand_id,
            job_id=job.id,
            stage=PipelineStage.cv_sent,
        )
        db.add(initial_stage)
        await db.flush()
        await db.commit()
        job_id = job.id

    try:
        # Trigger pipeline move → hired
        resp = await app_client.post(
            "/api/pipeline/move",
            json={
                "candidate_id": cand_id,
                "job_id": job_id,
                "stage": "hired",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        # Verify Contract draft auto-created
        async with AsyncSessionLocal() as db:
            contract = await db.scalar(
                select(Contract).where(
                    Contract.candidate_id == cand_id,
                    Contract.client_id == client_id,
                    Contract.job_id == job_id,
                    Contract.status == ContractStatus.draft,
                )
            )
            assert contract is not None, "Contract draft not created"

            # Verify ClientOrder draft auto-created pod Contract
            order = await db.scalar(
                select(ClientOrder).where(
                    ClientOrder.contract_id == contract.id,
                    ClientOrder.status == ClientOrderStatus.draft,
                )
            )
            assert order is not None, "ClientOrder draft not created"
            assert order.client_id == client_id
            assert order.job_id == job_id
            assert order.title.startswith("Test Kontraktor") or "Java" in order.title
    finally:
        # Cleanup: kasuj job + stage + contract + order
        async with AsyncSessionLocal() as db:
            await db.execute(
                ClientOrder.__table__.delete().where(ClientOrder.client_id == client_id)
            )
            await db.execute(
                Contract.__table__.delete().where(Contract.client_id == client_id)
            )
            await db.execute(
                CandidateStage.__table__.delete().where(
                    CandidateStage.candidate_id == cand_id
                )
            )
            await db.execute(Job.__table__.delete().where(Job.id == job_id))
            await db.commit()
        await _cleanup([client_id], [], [cand_id])


async def test_recruiter_forbidden_from_admin_overview(app_client: AsyncClient):
    rec_id, rec_email, rec_pwd = await _new_user(UserRole.recruiter)
    try:
        headers = await _login(app_client, rec_email, rec_pwd)
        resp = await app_client.get("/api/admin/clients-overview", headers=headers)
        assert resp.status_code == 403
    finally:
        await _cleanup([], [rec_id])
