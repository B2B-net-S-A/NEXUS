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

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
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
        cand = Candidate(name=f"Test Kontraktor {suffix}")
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
        assert body["rate_client"] == 17000
        # Marża z Order.rate_client (17000) - Contract.rate_candidate (12000) = 5000
        assert body["monthly_margin"] == 5000
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
        assert body["monthly_margin"] == 4000
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
        assert contractor["latest_order_rate_client"] == 16000
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


# ── My clients filter (sanity) ─────────────────────────────────────────────


async def test_my_clients_admin_sees_all(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client()
    try:
        resp = await app_client.get("/api/my-clients", headers=app_auth_headers)
        assert resp.status_code == 200
        ids = [r["client_id"] for r in resp.json()]
        assert client_id in ids
    finally:
        await _cleanup([client_id], [])


async def test_my_clients_dl_only_assigned(app_client: AsyncClient):
    own = await _new_client()
    other = await _new_client()
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    await _assign_dl(dl_id, own)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.get("/api/my-clients", headers=headers)
        assert resp.status_code == 200
        ids = [r["client_id"] for r in resp.json()]
        assert own in ids
        assert other not in ids
    finally:
        await _cleanup([own, other], [dl_id])


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


async def test_recruiter_forbidden_from_admin_overview(app_client: AsyncClient):
    rec_id, rec_email, rec_pwd = await _new_user(UserRole.recruiter)
    try:
        headers = await _login(app_client, rec_email, rec_pwd)
        resp = await app_client.get(
            "/api/admin/clients-overview", headers=headers
        )
        assert resp.status_code == 403
    finally:
        await _cleanup([], [rec_id])
