"""Tests for `GET /api/admin/clients-overview` Head DL fallback (PR5).

Bug context: QA 2026-05-27 — Insights "Klienci & Delivery" pokazywał
"Head DL = brak" dla niemal wszystkich klientów (DB: tylko 2/158 mają
poprawny assignment z is_head=true). Endpoint poprawiony żeby fallback
na dowolnego DL przypisanego do klienta gdy brak Head.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed_dl(suffix: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"head-fallback-{suffix}@inframinds.eu",
            password_hash=hash_password("Test_HeadFallback!Pass123"),
            name=f"Head Fallback DL {suffix}",
            role=UserRole.delivery_lead,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_client(name: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=name)
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _assign(dl_id: int, client_id: int, is_head: bool) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.team_structure import DeliveryLeadClientAssignment

    async with AsyncSessionLocal() as db:
        db.add(
            DeliveryLeadClientAssignment(
                delivery_lead_user_id=dl_id,
                client_id=client_id,
                is_head=is_head,
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_head_dl_prefers_is_head_true(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Gdy jest is_head=True assignment, to on wygrywa nad innymi."""
    suffix = uuid.uuid4().hex[:6]
    dl_head = await _seed_dl(f"{suffix}-head")
    dl_other = await _seed_dl(f"{suffix}-other")
    client_id = await _seed_client(f"HeadPriorityClient-{suffix}")

    # other DL first (lower id), head DL second (higher id)
    await _assign(dl_other, client_id, is_head=False)
    await _assign(dl_head, client_id, is_head=True)

    resp = await app_client.get("/api/admin/clients-overview", headers=app_auth_headers)
    assert resp.status_code == 200
    matching = [r for r in resp.json() if r["client_id"] == client_id]
    assert len(matching) == 1
    assert matching[0]["head_dl_id"] == dl_head, (
        "is_head=True powinien wygrać nawet z niższym user.id"
    )


@pytest.mark.asyncio
async def test_head_dl_fallback_to_any_assigned_dl(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Gdy brak is_head=True, fallback do dowolnego przypisanego DL."""
    suffix = uuid.uuid4().hex[:6]
    dl_id = await _seed_dl(suffix)
    client_id = await _seed_client(f"FallbackClient-{suffix}")
    await _assign(dl_id, client_id, is_head=False)

    resp = await app_client.get("/api/admin/clients-overview", headers=app_auth_headers)
    assert resp.status_code == 200
    matching = [r for r in resp.json() if r["client_id"] == client_id]
    assert len(matching) == 1
    assert matching[0]["head_dl_id"] == dl_id, (
        "fallback do non-head DL powinien być widoczny"
    )
    assert matching[0]["head_dl_name"] is not None


@pytest.mark.asyncio
async def test_head_dl_none_when_no_assignment(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Klient bez żadnego assignment nadal pokazuje brak."""
    suffix = uuid.uuid4().hex[:6]
    client_id = await _seed_client(f"NoDLClient-{suffix}")

    resp = await app_client.get("/api/admin/clients-overview", headers=app_auth_headers)
    assert resp.status_code == 200
    matching = [r for r in resp.json() if r["client_id"] == client_id]
    assert len(matching) == 1
    assert matching[0]["head_dl_id"] is None
    assert matching[0]["head_dl_name"] is None
