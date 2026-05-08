"""Integration tests dla DL Portal — framework contracts, orders, my-clients, admin overview.

Pattern: in-process AsyncClient (`app_client`/`app_auth_headers`) — żadnego live serwera.
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
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder
from app.models.client_order_contract import ClientOrderContract
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


async def _assign_dl(dl_id: int, client_id: int, *, is_head: bool = False) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id,
                client_id=client_id,
                is_head=is_head,
            )
        )
        await db.commit()


async def _login(app_client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cleanup(client_ids: list[int], user_ids: list[int]) -> None:
    async with AsyncSessionLocal() as db:
        for cid in client_ids:
            await db.execute(
                ClientFrameworkContract.__table__.delete().where(
                    ClientFrameworkContract.client_id == cid
                )
            )
            await db.execute(
                ClientOrder.__table__.delete().where(ClientOrder.client_id == cid)
            )
            await db.execute(
                DeliveryLeadClientAssignment.__table__.delete().where(
                    DeliveryLeadClientAssignment.client_id == cid
                )
            )
            await db.execute(Client.__table__.delete().where(Client.id == cid))
        if user_ids:
            await db.execute(User.__table__.delete().where(User.id.in_(user_ids)))
        await db.commit()


# ── Framework contracts ──────────────────────────────────────────────────────


async def test_framework_contract_create_and_list(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Admin może tworzyć MSA + lista zwraca z poprawnymi agregatami."""
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
        body = resp.json()
        assert body["name"] == "MSA 2026"
        assert body["status"] == "active"
        assert body["amendments_count"] == 0
        fc_id = body["id"]

        list_resp = await app_client.get(
            f"/api/clients/{client_id}/framework-contracts",
            headers=app_auth_headers,
        )
        assert list_resp.status_code == 200
        items = list_resp.json()["items"]
        assert any(fc["id"] == fc_id for fc in items)
    finally:
        await _cleanup([client_id], [])


async def test_framework_contract_dl_unassigned_403(app_client: AsyncClient):
    """DL bez assignmentu dostaje 403 na write."""
    client_id = await _new_client()
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.post(
            f"/api/clients/{client_id}/framework-contracts",
            data={"name": "should fail", "contract_status": "draft"},
            headers=headers,
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _cleanup([client_id], [dl_id])


async def test_framework_contract_dl_assigned_can_create(app_client: AsyncClient):
    """DL z assignmentem może tworzyć MSA."""
    client_id = await _new_client()
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    await _assign_dl(dl_id, client_id, is_head=False)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.post(
            f"/api/clients/{client_id}/framework-contracts",
            data={"name": "MSA support DL", "contract_status": "draft"},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
    finally:
        await _cleanup([client_id], [dl_id])


async def test_framework_contract_pdf_upload_and_download(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Upload PDFa + endpoint /file zwraca treść."""
    client_id = await _new_client()
    try:
        # Minimal valid PDF (header only — wystarczy dla allowlist + storage)
        pdf_bytes = b"%PDF-1.4\n%test\n"
        resp = await app_client.post(
            f"/api/clients/{client_id}/framework-contracts",
            data={"name": "MSA z PDFem", "contract_status": "draft"},
            files={"file": ("msa.pdf", pdf_bytes, "application/pdf")},
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["has_file"] is True
        assert body["filename"] == "msa.pdf"
        fc_id = body["id"]

        download = await app_client.get(
            f"/api/clients/{client_id}/framework-contracts/{fc_id}/file",
            headers=app_auth_headers,
        )
        assert download.status_code == 200
        assert download.content == pdf_bytes
    finally:
        await _cleanup([client_id], [])


# ── Orders + auto-margin ─────────────────────────────────────────────────────


async def _create_msa(client_id: int) -> int:
    async with AsyncSessionLocal() as db:
        fc = ClientFrameworkContract(
            client_id=client_id,
            name="test MSA",
            status=FrameworkContractStatus.active,
        )
        db.add(fc)
        await db.flush()
        await db.commit()
        return fc.id


async def test_order_create_and_list_aggregates(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    client_id = await _new_client()
    fc_id = await _create_msa(client_id)
    try:
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={
                "framework_contract_id": str(fc_id),
                "title": "Java devs Q3",
                "order_status": "active",
                "start_date": "2026-07-01",
                "end_date": "2026-12-31",
                "total_value": "100000",
                "currency": "PLN",
                "positions_count": "5",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["title"] == "Java devs Q3"
        assert body["linked_contracts_count"] == 0
        assert body["filled_positions"] == 0
        assert body["monthly_margin_total"] is None  # brak linkowanych
    finally:
        await _cleanup([client_id], [])


async def test_order_must_use_client_msa(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """framework_contract_id z innego klienta → 400."""
    client_a = await _new_client()
    client_b = await _new_client()
    fc_b = await _create_msa(client_b)
    try:
        resp = await app_client.post(
            f"/api/clients/{client_a}/orders",
            data={
                "framework_contract_id": str(fc_b),
                "title": "wrong msa",
                "order_status": "draft",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 400, resp.text
    finally:
        await _cleanup([client_a, client_b], [])


async def test_order_link_contract_and_margin(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Link kandydackiego Contract → linked_contracts_count + monthly_margin_total."""
    client_id = await _new_client()
    fc_id = await _create_msa(client_id)
    try:
        # Setup candidate + contract for this client
        async with AsyncSessionLocal() as db:
            cand = Candidate(name=f"Test cand {uuid.uuid4().hex[:6]}")
            db.add(cand)
            await db.flush()
            contract = Contract(
                candidate_id=cand.id,
                client_id=client_id,
                start_date=date.today(),
                rate_client=15000,
                rate_candidate=12000,
                status=ContractStatus.active,
            )
            db.add(contract)
            await db.flush()
            await db.commit()
            cand_id = cand.id
            contract_id = contract.id

        # Create order
        resp = await app_client.post(
            f"/api/clients/{client_id}/orders",
            data={
                "framework_contract_id": str(fc_id),
                "title": "linkable",
                "order_status": "active",
            },
            headers=app_auth_headers,
        )
        assert resp.status_code == 201
        order_id = resp.json()["id"]

        # Link
        link_resp = await app_client.post(
            f"/api/clients/{client_id}/orders/{order_id}/contracts",
            json={"contract_id": contract_id},
            headers=app_auth_headers,
        )
        assert link_resp.status_code == 201, link_resp.text
        link_body = link_resp.json()
        assert link_body["contract_id"] == contract_id
        assert link_body["monthly_margin"] == 3000  # 15000 - 12000

        # Re-fetch order — should show aggregates
        get_resp = await app_client.get(
            f"/api/clients/{client_id}/orders/{order_id}",
            headers=app_auth_headers,
        )
        body = get_resp.json()
        assert body["linked_contracts_count"] == 1
        assert body["filled_positions"] == 1
        assert body["monthly_margin_total"] == 3000

        # Duplicate link → 409
        dup = await app_client.post(
            f"/api/clients/{client_id}/orders/{order_id}/contracts",
            json={"contract_id": contract_id},
            headers=app_auth_headers,
        )
        assert dup.status_code == 409
    finally:
        # Detach link before cleanup
        async with AsyncSessionLocal() as db:
            await db.execute(
                ClientOrderContract.__table__.delete().where(
                    ClientOrderContract.contract_id == contract_id
                )
            )
            await db.execute(
                Contract.__table__.delete().where(Contract.id == contract_id)
            )
            await db.execute(
                Candidate.__table__.delete().where(Candidate.id == cand_id)
            )
            await db.commit()
        await _cleanup([client_id], [])


# ── My clients filter ───────────────────────────────────────────────────────


async def test_my_clients_admin_sees_all(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Admin widzi wszystkich klientów."""
    client_id = await _new_client()
    try:
        resp = await app_client.get("/api/my-clients", headers=app_auth_headers)
        assert resp.status_code == 200
        ids = [r["client_id"] for r in resp.json()]
        assert client_id in ids
    finally:
        await _cleanup([client_id], [])


async def test_my_clients_dl_filtered(app_client: AsyncClient):
    """DL widzi tylko swoich klientów (nie wszystkich)."""
    own_client = await _new_client()
    other_client = await _new_client()
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    await _assign_dl(dl_id, own_client, is_head=True)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.get("/api/my-clients", headers=headers)
        assert resp.status_code == 200
        ids = [r["client_id"] for r in resp.json()]
        assert own_client in ids
        assert other_client not in ids
    finally:
        await _cleanup([own_client, other_client], [dl_id])


async def test_dashboard_dl_unassigned_403(app_client: AsyncClient):
    client_id = await _new_client()
    dl_id, dl_email, dl_pwd = await _new_user(UserRole.delivery_lead)
    try:
        headers = await _login(app_client, dl_email, dl_pwd)
        resp = await app_client.get(
            f"/api/my-clients/{client_id}/dashboard", headers=headers
        )
        assert resp.status_code == 403
    finally:
        await _cleanup([client_id], [dl_id])


# ── Admin overview ──────────────────────────────────────────────────────────


async def test_admin_overview_recruiter_403(app_client: AsyncClient):
    """Recruiter (nie admin/HoR) → 403 na admin overview."""
    rec_id, rec_email, rec_pwd = await _new_user(UserRole.recruiter)
    try:
        headers = await _login(app_client, rec_email, rec_pwd)
        resp = await app_client.get(
            "/api/admin/clients-overview", headers=headers
        )
        assert resp.status_code == 403
    finally:
        await _cleanup([], [rec_id])


async def test_admin_overview_works_for_admin(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Admin dostaje listę klientów + by-dl działa."""
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
