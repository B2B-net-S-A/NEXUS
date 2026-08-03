"""Integration tests for /api/clients/{id}/team + /tacs CRUD endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.client import Client
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


async def _new_user(role: UserRole, *, is_active: bool = True) -> tuple[int, str, str]:
    """Create user and return (id, email, password) for login."""
    suffix = uuid.uuid4().hex[:8]
    email = f"team-test-{role.value}-{suffix}@example.com"
    password = f"P@ssw0rd_{suffix}"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Team Test {role.value} {suffix}",
            role=role,
            is_active=is_active,
        )
        db.add(u)
        await db.flush()
        await db.commit()
        return u.id, email, password


async def _new_client() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Client(name=f"Team Test Client {suffix}")
        db.add(c)
        await db.flush()
        await db.commit()
        return c.id


async def _login(app_client: AsyncClient, email: str, password: str) -> dict:
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def _cleanup(client_id: int, user_ids: list[int]) -> None:
    """Best-effort cleanup. Detach FK from jobs before deleting users."""
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
async def test_get_client_team_returns_tacs_and_dls(
    app_client: AsyncClient, app_auth_headers: dict
):
    tac_id, _, _ = await _new_user(UserRole.tac)
    dl_id, _, _ = await _new_user(UserRole.delivery_lead)
    client_id = await _new_client()

    try:
        async with AsyncSessionLocal() as db:
            db.add(
                ClientTacAssignment(
                    client_id=client_id, tac_user_id=tac_id, is_primary=True
                )
            )
            db.add(
                DeliveryLeadClientAssignment(
                    client_id=client_id,
                    delivery_lead_user_id=dl_id,
                    is_head=True,
                )
            )
            await db.commit()

        resp = await app_client.get(
            f"/api/clients/{client_id}/team", headers=app_auth_headers
        )
        assert resp.status_code == 200
        body = resp.json()
        assert len(body["tacs"]) == 1
        assert body["tacs"][0]["user_id"] == tac_id
        assert body["tacs"][0]["is_primary"] is True
        assert body["tacs"][0]["is_first_priority_for_tac"] is None
        assert len(body["delivery_leads"]) == 1
        assert body["delivery_leads"][0]["user_id"] == dl_id
        assert body["delivery_leads"][0]["is_head"] is True
    finally:
        await _cleanup(client_id, [tac_id, dl_id])


@pytest.mark.integration
async def test_post_tac_requires_head_of_recruitment_plus(
    app_client: AsyncClient,
):
    """Recruiter (poniżej HeadOfRecruitmentPlus) dostaje 403."""
    recruiter_id, email, password = await _new_user(UserRole.recruiter)
    tac_id, _, _ = await _new_user(UserRole.tac)
    client_id = await _new_client()

    try:
        recr_headers = await _login(app_client, email, password)
        resp = await app_client.post(
            f"/api/clients/{client_id}/tacs",
            headers=recr_headers,
            json={"user_id": tac_id, "is_primary": True},
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _cleanup(client_id, [recruiter_id, tac_id])


@pytest.mark.integration
async def test_post_primary_tac_unsets_previous_primary(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Drugi POST z is_primary=True dla tego samego klienta zdejmuje poprzedniego primary."""
    tac_a, _, _ = await _new_user(UserRole.tac)
    tac_b, _, _ = await _new_user(UserRole.tac)
    client_id = await _new_client()

    try:
        # Make A primary
        r1 = await app_client.post(
            f"/api/clients/{client_id}/tacs",
            headers=app_auth_headers,
            json={"user_id": tac_a, "is_primary": True},
        )
        assert r1.status_code == 201, r1.text
        assert r1.json()["is_first_priority_for_tac"] is True

        # Make B primary
        r2 = await app_client.post(
            f"/api/clients/{client_id}/tacs",
            headers=app_auth_headers,
            json={"user_id": tac_b, "is_primary": True},
        )
        assert r2.status_code == 201, r2.text

        # Verify only B is primary now
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(
                        ClientTacAssignment.tac_user_id,
                        ClientTacAssignment.is_primary,
                    ).where(ClientTacAssignment.client_id == client_id)
                )
            ).all()
        primaries = [r.tac_user_id for r in rows if r.is_primary]
        assert primaries == [tac_b]
    finally:
        await _cleanup(client_id, [tac_a, tac_b])


@pytest.mark.integration
async def test_delete_tac_assignment(app_client: AsyncClient, app_auth_headers: dict):
    tac_id, _, _ = await _new_user(UserRole.tac)
    client_id = await _new_client()

    try:
        await app_client.post(
            f"/api/clients/{client_id}/tacs",
            headers=app_auth_headers,
            json={"user_id": tac_id, "is_primary": False},
        )
        resp = await app_client.delete(
            f"/api/clients/{client_id}/tacs/{tac_id}",
            headers=app_auth_headers,
        )
        assert resp.status_code == 204

        async with AsyncSessionLocal() as db:
            count = (
                (
                    await db.execute(
                        select(ClientTacAssignment).where(
                            ClientTacAssignment.client_id == client_id
                        )
                    )
                )
                .scalars()
                .all()
            )
        assert count == []
    finally:
        await _cleanup(client_id, [tac_id])


@pytest.mark.integration
async def test_toggle_primary_flips(app_client: AsyncClient, app_auth_headers: dict):
    tac_a, _, _ = await _new_user(UserRole.tac)
    tac_b, _, _ = await _new_user(UserRole.tac)
    client_id = await _new_client()

    try:
        await app_client.post(
            f"/api/clients/{client_id}/tacs",
            headers=app_auth_headers,
            json={"user_id": tac_a, "is_primary": True},
        )
        await app_client.post(
            f"/api/clients/{client_id}/tacs",
            headers=app_auth_headers,
            json={"user_id": tac_b, "is_primary": False},
        )
        # Toggle B → True (should demote A)
        resp = await app_client.put(
            f"/api/clients/{client_id}/tacs/{tac_b}/toggle-primary",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_primary"] is True

        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(
                        ClientTacAssignment.tac_user_id,
                        ClientTacAssignment.is_primary,
                    ).where(ClientTacAssignment.client_id == client_id)
                )
            ).all()
        primaries = [r.tac_user_id for r in rows if r.is_primary]
        assert primaries == [tac_b]
    finally:
        await _cleanup(client_id, [tac_a, tac_b])


@pytest.mark.integration
async def test_post_invalid_role_returns_400(
    app_client: AsyncClient, app_auth_headers: dict
):
    """user_id usera z rolą sourcer → 400."""
    sourcer_id, _, _ = await _new_user(UserRole.sourcer)
    client_id = await _new_client()
    try:
        resp = await app_client.post(
            f"/api/clients/{client_id}/tacs",
            headers=app_auth_headers,
            json={"user_id": sourcer_id, "is_primary": False},
        )
        assert resp.status_code == 400, resp.text
    finally:
        await _cleanup(client_id, [sourcer_id])
