"""Redakcja rekrutacji przez osobę, która ją prowadzi (decyzja Artura 22.09.2026).

Rekrutację zakłada admin / Delivery Lead, a jej TREŚĆ (opis, ogłoszenia,
Champion) redaguje też rekruter prowadzący i współpracownicy. Rekruter spoza
zespołu dostaje 403, a członek zespołu nie zmienia statusu, klienta, obsady ani
widełek wynagrodzenia. `GET /api/jobs/{id}` niesie `can_edit`/`can_manage`
liczone tą samą regułą co bramka PATCH.

In-process `app_client`; baza testowa wspólna i nieczyszczona — asercje tylko
na własnych wierszach (uuid).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed_user(app_client: AsyncClient, *roles: str) -> tuple[dict, int]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"job-editor-{roles[0]}-{unique}@example.com"
    password = f"T3st_{unique}!Edit"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Job editor {roles[0]}",
            role=UserRole(roles[0]),
            roles=list(roles),
            is_active=True,
            profile_completed=True,
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


async def _seed_job(*, recruiter_id: int | None, collaborator_id: int | None) -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.job_collaborator import JobCollaborator

    async with AsyncSessionLocal() as db:
        client = Client(name=f"JobEditorClient-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"JobEditor-{uuid.uuid4().hex[:6]}",
            description="Opis startowy",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter_id,
        )
        db.add(job)
        await db.flush()
        if collaborator_id is not None:
            db.add(JobCollaborator(job_id=job.id, user_id=collaborator_id))
        await db.commit()
        return job.id


@pytest.fixture
async def world(app_client: AsyncClient):
    owner_h, owner_id = await _seed_user(app_client, "recruiter")
    collab_h, collab_id = await _seed_user(app_client, "sourcer")
    outsider_h, _ = await _seed_user(app_client, "recruiter")
    hor_h, _ = await _seed_user(app_client, "head_of_recruitment")
    dl_h, _ = await _seed_user(app_client, "delivery_lead")
    job_id = await _seed_job(recruiter_id=owner_id, collaborator_id=collab_id)
    return {
        "job_id": job_id,
        "owner": owner_h,
        "collab": collab_h,
        "outsider": outsider_h,
        "hor": hor_h,
        "dl": dl_h,
    }


@pytest.mark.asyncio
async def test_owner_and_collaborator_edit_the_description(app_client, world):
    for who in ("owner", "collab"):
        resp = await app_client.patch(
            f"/api/jobs/{world['job_id']}",
            headers=world[who],
            json={"description": f"Opis od {who}"},
        )
        assert resp.status_code == 200, (who, resp.text)
        assert resp.json()["description"] == f"Opis od {who}"


@pytest.mark.asyncio
async def test_recruiter_outside_the_team_is_refused(app_client, world):
    for who in ("outsider", "hor"):
        resp = await app_client.patch(
            f"/api/jobs/{world['job_id']}",
            headers=world[who],
            json={"description": "Nie moja rekrutacja"},
        )
        assert resp.status_code == 403, (who, resp.text)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "closed"),
        ("recruiter_id", None),
        ("salary_max", 30000),
    ],
)
async def test_team_member_cannot_touch_lifecycle_or_budget(
    app_client, world, field, value
):
    resp = await app_client.patch(
        f"/api/jobs/{world['job_id']}",
        headers=world["owner"],
        json={field: value},
    )
    assert resp.status_code == 403, resp.text


@pytest.mark.asyncio
async def test_delivery_lead_keeps_full_edit(app_client, world):
    resp = await app_client.patch(
        f"/api/jobs/{world['job_id']}",
        headers=world["dl"],
        json={"description": "Opis od DL", "status": "draft"},
    )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_job_detail_reports_can_edit_and_can_manage(app_client, world):
    expected = {
        "owner": (True, False),
        "collab": (True, False),
        "outsider": (False, False),
        "dl": (True, True),
    }
    for who, (can_edit, can_manage) in expected.items():
        resp = await app_client.get(f"/api/jobs/{world['job_id']}", headers=world[who])
        assert resp.status_code == 200, (who, resp.text)
        body = resp.json()
        assert body["can_edit"] is can_edit, who
        assert body["can_manage"] is can_manage, who


@pytest.mark.asyncio
async def test_postings_follow_the_same_rule(app_client, world):
    created = await app_client.post(
        f"/api/jobs/{world['job_id']}/postings",
        headers=world["owner"],
        json={"portal": "pracuj_pl", "expires_days": 30},
    )
    assert created.status_code == 201, created.text
    posting_id = created.json()["id"]

    refused = await app_client.post(
        f"/api/jobs/{world['job_id']}/postings",
        headers=world["outsider"],
        json={"portal": "justjoinit", "expires_days": 30},
    )
    assert refused.status_code == 403, refused.text
    refused_delete = await app_client.delete(
        f"/api/postings/{posting_id}", headers=world["outsider"]
    )
    assert refused_delete.status_code == 403, refused_delete.text

    deleted = await app_client.delete(
        f"/api/postings/{posting_id}", headers=world["collab"]
    )
    assert deleted.status_code == 204, deleted.text


@pytest.mark.asyncio
async def test_champion_profile_is_editable_by_the_team_only(app_client, world):
    payload = {"project": {"about": "Nowy projekt w banku."}}
    ok = await app_client.put(
        f"/api/jobs/{world['job_id']}/champion-profile",
        headers=world["owner"],
        json=payload,
    )
    assert ok.status_code == 200, ok.text

    refused = await app_client.put(
        f"/api/jobs/{world['job_id']}/champion-profile",
        headers=world["outsider"],
        json=payload,
    )
    assert refused.status_code == 403, refused.text
