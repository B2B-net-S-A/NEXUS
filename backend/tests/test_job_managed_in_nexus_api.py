"""0325: `POST /api/jobs/{id}/manage-in-nexus` — przełącznik „prowadzona w NEXUSIE".

Kontrakt (decyzja Artura 17.09.2026): włączenie = TacPlus (od 23.09.2026 bez
wymogu członkostwa w zespole rekrutacji — „nie musisz być przypisany");
wyłączenie (powrót do Traffita, po którym nocny import znów
nadpisze ruchy) tylko admin / Delivery Lead; każda realna zmiana zostawia wpis
`activities.action='managed_in_nexus_changed'` z poprzednią wartością;
ponowne wywołanie z tą samą wartością nie dopisuje historii. Rekrutacja spoza
Traffita → 409, brak oferty → 404.

In-process `app_client`; baza testowa wspólna i nieczyszczona — asercje tylko
na własnych wierszach (uuid).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal


def _url(job_id: int) -> str:
    return f"/api/jobs/{job_id}/manage-in-nexus"


async def _seed_tac(app_client: AsyncClient) -> tuple[dict[str, str], int]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"managed-nexus-tac-{unique}@example.com"
    password = f"T3st_{unique}!Tac"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Managed NEXUS TAC",
            role=UserRole.tac,
            roles=["tac"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        uid = user.id

    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, uid


async def _seed_job(
    *, tac_id: int | None = None, external_source: str = "traffit"
) -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"ManagedNexusClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"ManagedNexus-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client.id,
            tac_id=tac_id,
            external_source=external_source,
            external_id=uuid.uuid4().hex if external_source == "traffit" else None,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _activity_rows(job_id: int) -> list[dict]:
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text(
                "SELECT details->>'enabled' AS enabled, "
                "details->>'previous' AS previous, user_id "
                "FROM activities WHERE entity_type = 'job' AND entity_id = :jid "
                "AND action = 'managed_in_nexus_changed' ORDER BY id"
            ),
            {"jid": job_id},
        )
        return [dict(r._mapping) for r in rows]


@pytest.mark.asyncio
async def test_admin_enables_switch_and_leaves_audit_row(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    job_id = await _seed_job()

    resp = await app_client.post(
        _url(job_id), json={"enabled": True}, headers=app_auth_headers
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["managed_in_nexus"] is True
    assert body["managed_in_nexus_at"] is not None
    assert body["managed_in_nexus_by"] is not None
    assert body["external_source"] == "traffit"
    rows = await _activity_rows(job_id)
    assert len(rows) == 1
    assert rows[0]["enabled"] == "true"
    assert rows[0]["previous"] == "false"


@pytest.mark.asyncio
async def test_repeated_enable_is_idempotent(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    job_id = await _seed_job()

    first = await app_client.post(
        _url(job_id), json={"enabled": True}, headers=app_auth_headers
    )
    second = await app_client.post(
        _url(job_id), json={"enabled": True}, headers=app_auth_headers
    )

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json()["managed_in_nexus"] is True
    assert second.json()["managed_in_nexus_at"] == first.json()["managed_in_nexus_at"]
    assert len(await _activity_rows(job_id)) == 1


@pytest.mark.asyncio
async def test_tac_outside_the_recruitment_team_can_enable_but_not_revert(
    app_client: AsyncClient,
):
    headers, tac_id = await _seed_tac(app_client)
    job_id = await _seed_job()  # TAC is not on this recruitment's team

    enable = await app_client.post(
        _url(job_id), json={"enabled": True}, headers=headers
    )
    assert enable.status_code == 200, enable.text
    assert enable.json()["managed_in_nexus"] is True
    assert enable.json()["managed_in_nexus_by"] == tac_id
    rows = await _activity_rows(job_id)
    assert len(rows) == 1 and rows[0]["user_id"] == tac_id

    revert = await app_client.post(
        _url(job_id), json={"enabled": False}, headers=headers
    )
    assert revert.status_code == 403, revert.text
    assert len(await _activity_rows(job_id)) == 1


@pytest.mark.asyncio
async def test_tac_member_can_enable_but_not_revert(app_client: AsyncClient):
    headers, tac_id = await _seed_tac(app_client)
    job_id = await _seed_job(tac_id=tac_id)

    enable = await app_client.post(
        _url(job_id), json={"enabled": True}, headers=headers
    )
    assert enable.status_code == 200, enable.text
    assert enable.json()["managed_in_nexus_by"] == tac_id

    revert = await app_client.post(
        _url(job_id), json={"enabled": False}, headers=headers
    )
    assert revert.status_code == 403, revert.text
    assert len(await _activity_rows(job_id)) == 1


@pytest.mark.asyncio
async def test_admin_reverts_to_traffit(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    job_id = await _seed_job()

    await app_client.post(
        _url(job_id), json={"enabled": True}, headers=app_auth_headers
    )
    resp = await app_client.post(
        _url(job_id), json={"enabled": False}, headers=app_auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["managed_in_nexus"] is False
    rows = await _activity_rows(job_id)
    assert [(r["enabled"], r["previous"]) for r in rows] == [
        ("true", "false"),
        ("false", "true"),
    ]


@pytest.mark.asyncio
async def test_manual_recruitment_gets_409(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    job_id = await _seed_job(external_source="manual")

    resp = await app_client.post(
        _url(job_id), json={"enabled": True}, headers=app_auth_headers
    )

    assert resp.status_code == 409, resp.text
    assert await _activity_rows(job_id) == []


@pytest.mark.asyncio
async def test_missing_recruitment_gets_404(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    resp = await app_client.post(
        _url(2_000_000_000), json={"enabled": True}, headers=app_auth_headers
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_missing_recruitment_is_404_also_for_a_tac(app_client: AsyncClient):
    """Członkostwo sprawdzane po odczycie oferty — TAC nie dostaje 403 za brak."""
    headers, _tac_id = await _seed_tac(app_client)
    resp = await app_client.post(
        _url(2_000_000_000), json={"enabled": True}, headers=headers
    )
    assert resp.status_code == 404, resp.text
