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
    collab_h, collab_id = await _seed_user(app_client, "recruiter")
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
        # Runda 9 (R9-N15-6): termin, budżet i reszta ustawień Delivery.
        ("deadline", "2027-01-31"),
        ("rate_budget_hourly", 150),
        ("headcount", 3),
        ("priority", "high"),
        ("needs_sourcing", True),
        ("pipeline_template_id", None),
        ("competence_category_id", None),
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
async def test_head_of_recruitment_sets_priority_and_nothing_else_locked(
    app_client, world
):
    """Decyzja 02.10.2026: priorytet (P1 / P2 / „Przyjmujemy kandydatów”) ustawia
    też Head of Recruitment — prowadzi kolejkę pracy zespołu. Pełnej redakcji
    nie dostaje: termin i obsada przez PATCH zostają przy Delivery Leadzie."""
    url = f"/api/jobs/{world['job_id']}"
    for value, level in (("urgent", "p1"), ("low", "accepting"), ("medium", "p2")):
        resp = await app_client.patch(
            url, headers=world["hor"], json={"priority": value}
        )
        assert resp.status_code == 200, (value, resp.text)
        assert resp.json()["priority"] == value
        assert resp.json()["priority_level"] == level

    for locked in (
        {"deadline": "2027-01-31"},
        {"recruiter_id": None},
        # Priorytet nie przemyca reszty: jedno zablokowane pole = odmowa całości.
        {"priority": "urgent", "deadline": "2027-01-31"},
    ):
        resp = await app_client.patch(url, headers=world["hor"], json=locked)
        assert resp.status_code == 403, (locked, resp.text)

    detail = await app_client.get(url, headers=world["hor"])
    assert detail.status_code == 200, detail.text
    assert detail.json()["priority"] == "medium"
    assert detail.json()["deadline"] is None


@pytest.mark.asyncio
async def test_delivery_lead_keeps_full_edit(app_client, world):
    resp = await app_client.patch(
        f"/api/jobs/{world['job_id']}",
        headers=world["dl"],
        json={"description": "Opis od DL", "status": "closed"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "closed"


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
async def test_job_detail_reports_can_staff_and_can_set_priority(app_client, world):
    """`can_staff` = bramka `/owner`, `can_set_priority` = wyjątek w PATCH.

    Head of Recruitment ma oba bez pełnej redakcji (`can_manage` zostaje
    fałszem). Rekruter nie ma żadnego — do 0411 priorytet ustawiała jeszcze
    rola TAC, wycofana razem ze swoimi dodatkami. Podgląd (`user`) nie ma
    zapisu sekcji, więc też nie ma żadnego.
    """
    expected = {
        "owner": (False, False),
        "collab": (False, False),
        "outsider": (False, False),
        "hor": (True, True),
        "dl": (True, True),
        "viewer": (False, False),
    }
    for who, (can_staff, can_set_priority) in expected.items():
        resp = await app_client.get(f"/api/jobs/{world['job_id']}", headers=world[who])
        assert resp.status_code == 200, (who, resp.text)
        body = resp.json()
        assert body["can_staff"] is can_staff, who
        assert body["can_set_priority"] is can_set_priority, who
    hor = await app_client.get(f"/api/jobs/{world['job_id']}", headers=world["hor"])
    assert hor.json()["can_manage"] is False


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


# ── Bez bazy: kto przydziela rekruterów i kto ustawia priorytet ──────────────
# Role bez zakresu (wszystkie poza Delivery Leadem) rozstrzygają się bez bazy,
# a Delivery Lead ma w rekrutacjach zakres całej organizacji — też bez zapytań.


def _person(*roles: str):
    from app.models.user import User, UserRole

    return User(id=7, role=UserRole(roles[0]), roles=list(roles), is_active=True)


def _job():
    from app.models.job import Job

    return Job(id=5, client_id=1)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roles", "can_staff", "can_set_priority"),
    [
        (("admin",), True, True),
        (("delivery_lead",), True, True),
        (("head_of_recruitment",), True, True),
        # Rola dodatkowa liczy się jak główna.
        (("recruiter", "head_of_recruitment"), True, True),
        # Rekruter nie przydziela ludzi i nie ustawia priorytetu (do 0411
        # priorytet ustawiała rola TAC — dodatek zniknął razem z rolą).
        (("recruiter",), False, False),
        (("talent_community_manager",), False, False),
        (("finance",), False, False),
        (("user",), False, False),
    ],
)
async def test_staffing_and_priority_rights_per_role(
    roles: tuple[str, ...], can_staff: bool, can_set_priority: bool
):
    """Lustro capability `job.recruiter.assign` i `job.priority.update`."""
    from app.api.recruitment_access import (
        user_can_set_job_priority,
        user_can_staff_job,
    )

    user = _person(*roles)
    assert await user_can_staff_job(None, user, _job()) is can_staff
    assert await user_can_set_job_priority(None, user, _job()) is can_set_priority


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("roles", "fields", "allowed"),
    [
        (("head_of_recruitment",), {"priority"}, True),
        (("head_of_recruitment",), {"priority", "description"}, True),
        # Priorytet nie przemyca reszty zablokowanych pól.
        (("head_of_recruitment",), {"priority", "deadline"}, False),
        (("head_of_recruitment",), {"recruiter_id"}, False),
        (("head_of_recruitment",), {"status"}, False),
        (("recruiter", "head_of_recruitment"), {"priority"}, True),
        (("recruiter",), {"priority"}, False),
        # Do 0411 rola TAC była pełnym redaktorem; rekruter nim nie jest.
        (("recruiter",), {"priority", "deadline"}, False),
        (("recruiter",), {"description"}, True),
        # Pełni redaktorzy bez zmian.
        (("delivery_lead",), {"priority", "status"}, True),
        (("admin",), {"status"}, True),
    ],
)
async def test_priority_is_the_only_locked_field_open_to_head_of_recruitment(
    roles: tuple[str, ...], fields: set[str], allowed: bool
):
    from fastapi import HTTPException

    from app.api.recruitment_access import ensure_job_editor

    user = _person(*roles)
    if allowed:
        await ensure_job_editor(None, user, _job(), fields=fields)
        return
    with pytest.raises(HTTPException) as refused:
        await ensure_job_editor(None, user, _job(), fields=fields)
    assert refused.value.status_code == 403
    # Odmowa nazywa uprawnienie i mówi o wyjątku dla priorytetu.
    detail = refused.value.detail
    assert detail["code"] == "permission_denied"
    assert detail["permission"] == "recruitment_manage"
    assert "Head of Recruitment" in detail["message"]
