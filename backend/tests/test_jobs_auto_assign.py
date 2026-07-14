"""Integration tests for auto-assign TAC + Delivery Lead in POST /jobs.

Uses the in-process `app_client` fixture (no running server required).
Each test seeds its own client + assignments to stay isolated from prod
data.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


async def _new_user(role: UserRole, *, is_active: bool = True) -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        u = User(
            email=f"jobs-test-{role.value}-{suffix}@example.com",
            password_hash=hash_password("P@ssw0rd"),
            name=f"JobsAuto {role.value} {suffix}",
            role=role,
            is_active=is_active,
        )
        db.add(u)
        await db.flush()
        await db.commit()
        return u.id


async def _new_client() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Client(name=f"JobsAuto Client {suffix}")
        db.add(c)
        await db.flush()
        await db.commit()
        return c.id


async def _assign_primary_tac(client_id: int, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            ClientTacAssignment(
                client_id=client_id, tac_user_id=user_id, is_primary=True
            )
        )
        await db.commit()


async def _assign_head_dl(client_id: int, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                client_id=client_id,
                delivery_lead_user_id=user_id,
                is_head=True,
            )
        )
        await db.commit()


async def _cleanup(client_id: int, user_ids: list[int]) -> None:
    """Best-effort cleanup. Detach FK from jobs (NULL out) before deleting
    users so we never trip `jobs_delivery_lead_id_fkey` etc. when other
    background tasks (snapshot, marketplace scan) hold references."""
    async with AsyncSessionLocal() as db:
        from app.models.job import Job

        await db.execute(
            ClientTacAssignment.__table__.delete().where(
                ClientTacAssignment.client_id == client_id
            )
        )
        await db.execute(
            DeliveryLeadClientAssignment.__table__.delete().where(
                DeliveryLeadClientAssignment.client_id == client_id
            )
        )
        if user_ids:
            await db.execute(
                Job.__table__.update()
                .where(Job.tac_id.in_(user_ids))
                .values(tac_id=None)
            )
            await db.execute(
                Job.__table__.update()
                .where(Job.delivery_lead_id.in_(user_ids))
                .values(delivery_lead_id=None)
            )
            await db.execute(
                Job.__table__.update()
                .where(Job.recruiter_id.in_(user_ids))
                .values(recruiter_id=None)
            )
        client = await db.get(Client, client_id) if client_id else None
        if client is not None:
            await db.delete(client)
        for uid in user_ids:
            user = await db.get(User, uid)
            if user is not None:
                await db.delete(user)
        await db.commit()


@pytest.mark.integration
async def test_create_job_auto_assigns_from_client(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Klient z primary TAC + head DL → POST /jobs auto-fill obu."""
    tac_id = await _new_user(UserRole.tac)
    dl_id = await _new_user(UserRole.delivery_lead)
    client_id = await _new_client()
    await _assign_primary_tac(client_id, tac_id)
    await _assign_head_dl(client_id, dl_id)

    try:
        resp = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={
                "title": "Auto-assign smoke",
                "client_id": client_id,
                "auto_suggest_cc": False,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tac_id"] == tac_id
        assert body["delivery_lead_id"] == dl_id
        assert body["client_id"] == client_id

        # Cleanup the job we just created
        async with AsyncSessionLocal() as db:
            from app.models.job import Job

            job = await db.get(Job, body["id"])
            if job is not None:
                await db.delete(job)
                await db.commit()
    finally:
        await _cleanup(client_id, [tac_id, dl_id])


@pytest.mark.integration
async def test_create_job_explicit_override_wins(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Jawny tac_id w POST wygrywa nad primary TAC klienta."""
    primary_tac = await _new_user(UserRole.tac)
    other_tac = await _new_user(UserRole.tac)
    client_id = await _new_client()
    await _assign_primary_tac(client_id, primary_tac)

    try:
        resp = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={
                "title": "Override smoke",
                "client_id": client_id,
                "tac_id": other_tac,
                "auto_suggest_cc": False,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tac_id"] == other_tac
        assert body["tac_id"] != primary_tac

        async with AsyncSessionLocal() as db:
            from app.models.job import Job

            job = await db.get(Job, body["id"])
            if job is not None:
                await db.delete(job)
                await db.commit()
    finally:
        await _cleanup(client_id, [primary_tac, other_tac])


@pytest.mark.integration
async def test_create_job_no_client_team_leaves_null(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Klient bez przypisań → tac_id i delivery_lead_id pozostają NULL."""
    client_id = await _new_client()
    try:
        resp = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={
                "title": "No team fallback",
                "client_id": client_id,
                "auto_suggest_cc": False,
            },
        )
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["tac_id"] is None
        assert body["delivery_lead_id"] is None

        async with AsyncSessionLocal() as db:
            from app.models.job import Job

            job = await db.get(Job, body["id"])
            if job is not None:
                await db.delete(job)
                await db.commit()
    finally:
        await _cleanup(client_id, [])


@pytest.mark.integration
async def test_create_job_invalid_tac_role_returns_400(
    app_client: AsyncClient, app_auth_headers: dict
):
    """tac_id wskazujący na sourcera (poza dopuszczalnymi rolami) → 400."""
    sourcer_id = await _new_user(UserRole.sourcer)
    client_id = await _new_client()
    try:
        resp = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={
                "title": "Invalid role",
                "client_id": client_id,
                "tac_id": sourcer_id,
                "auto_suggest_cc": False,
            },
        )
        assert resp.status_code == 400, resp.text
        assert "tac_id" in resp.text
    finally:
        await _cleanup(client_id, [sourcer_id])


@pytest.mark.integration
async def test_patch_job_updates_tac_id(
    app_client: AsyncClient, app_auth_headers: dict
):
    """PATCH /jobs/{id} z `tac_id` przepisuje pole."""
    tac_id = await _new_user(UserRole.tac)
    other_tac = await _new_user(UserRole.tac)
    client_id = await _new_client()

    try:
        # Create job with tac_id=tac_id (explicit)
        create = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={
                "title": "Patch target",
                "client_id": client_id,
                "tac_id": tac_id,
                "auto_suggest_cc": False,
            },
        )
        assert create.status_code == 201, create.text
        job_id = create.json()["id"]
        assert create.json()["tac_id"] == tac_id

        # PATCH to other_tac
        patch = await app_client.patch(
            f"/api/jobs/{job_id}",
            headers=app_auth_headers,
            json={"tac_id": other_tac},
        )
        assert patch.status_code == 200, patch.text

        # Verify via GET
        get = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
        assert get.status_code == 200
        assert get.json()["tac_id"] == other_tac

        # Cleanup job
        async with AsyncSessionLocal() as db:
            from app.models.job import Job

            job = await db.get(Job, job_id)
            if job is not None:
                await db.delete(job)
                await db.commit()
    finally:
        await _cleanup(client_id, [tac_id, other_tac])
