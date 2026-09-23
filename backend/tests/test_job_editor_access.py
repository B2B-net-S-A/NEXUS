"""Redakcja rekrutacji przez osobę, która ją prowadzi (decyzja Artura 22.09.2026).

Rekrutację zakłada admin / Delivery Lead, a jej TREŚĆ (opis, ogłoszenia,
Champion) redaguje też rekruter prowadzący i współpracownicy. Od 23.09.2026
(decyzja Artura: „wszystko w rekrutacji robi każdy, nie musisz być
przypisany") treść redaguje każda rola wewnętrzna, także rekruter spoza
zespołu i Head of Recruitment; stara rola podglądu `user` dostaje 403. Nikt
poza DL/adminem nie zmienia statusu, klienta, obsady ani widełek
wynagrodzenia. `GET /api/jobs/{id}` niesie `can_edit`/`can_manage` liczone tą
samą regułą co bramka PATCH.

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
    viewer_h, _ = await _seed_user(app_client, "user")
    job_id = await _seed_job(recruiter_id=owner_id, collaborator_id=collab_id)
    return {
        "job_id": job_id,
        "owner": owner_h,
        "collab": collab_h,
        "outsider": outsider_h,
        "hor": hor_h,
        "dl": dl_h,
        "viewer": viewer_h,
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
async def test_recruiter_outside_the_team_and_hor_edit_the_description(
    app_client, world
):
    for who in ("outsider", "hor"):
        resp = await app_client.patch(
            f"/api/jobs/{world['job_id']}",
            headers=world[who],
            json={"description": f"Opis od {who}"},
        )
        assert resp.status_code == 200, (who, resp.text)
        assert resp.json()["description"] == f"Opis od {who}"


@pytest.mark.asyncio
async def test_outsider_cannot_touch_lifecycle_and_viewer_cannot_edit(
    app_client, world
):
    lifecycle = await app_client.patch(
        f"/api/jobs/{world['job_id']}",
        headers=world["outsider"],
        json={"status": "closed"},
    )
    assert lifecycle.status_code == 403, lifecycle.text

    viewer = await app_client.patch(
        f"/api/jobs/{world['job_id']}",
        headers=world["viewer"],
        json={"description": "Podgląd nie redaguje"},
    )
    assert viewer.status_code == 403, viewer.text

    detail = await app_client.get(f"/api/jobs/{world['job_id']}", headers=world["dl"])
    assert detail.json()["status"] == "published"
    assert detail.json()["description"] == "Opis startowy"


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
        "outsider": (True, False),
        "dl": (True, True),
    }
    for who, (can_edit, can_manage) in expected.items():
        resp = await app_client.get(f"/api/jobs/{world['job_id']}", headers=world[who])
        assert resp.status_code == 200, (who, resp.text)
        body = resp.json()
        assert body["can_edit"] is can_edit, who
        assert body["can_manage"] is can_manage, who


@pytest.mark.asyncio
async def test_champion_profile_is_editable_by_every_internal_role(app_client, world):
    ok = await app_client.put(
        f"/api/jobs/{world['job_id']}/champion-profile",
        headers=world["owner"],
        json={"project": {"about": "Nowy projekt w banku."}},
    )
    assert ok.status_code == 200, ok.text

    by_outsider = await app_client.put(
        f"/api/jobs/{world['job_id']}/champion-profile",
        headers=world["outsider"],
        json={"project": {"about": "Projekt poprawiony przez kolegę."}},
    )
    assert by_outsider.status_code == 200, by_outsider.text
    assert (
        by_outsider.json()["champion_profile"]["project"]["about"]
        == "Projekt poprawiony przez kolegę."
    )

    refused = await app_client.put(
        f"/api/jobs/{world['job_id']}/champion-profile",
        headers=world["viewer"],
        json={"project": {"about": "Podgląd nie redaguje."}},
    )
    assert refused.status_code == 403, refused.text
