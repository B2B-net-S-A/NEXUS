"""Trasy automatu przydziału (0371): porządek w requestach, panel kategorii, pulpit.

Baza testowa jest wspólna i nieczyszczona — każdy test zakłada własne
rekrutacje i osoby i asertuje wyłącznie po nich.
"""

from __future__ import annotations

import os
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"),
]


async def _seed_job(*, work_state: str = "to_review", champion: bool = False) -> int:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.competence_category import CompetenceCategory
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"rb-client-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        qa = await db.scalar(
            select(CompetenceCategory.id).where(
                CompetenceCategory.slug == "security_quality"
            )
        )
        job = Job(
            title=f"Tester RB {uuid.uuid4().hex[:6]}",
            client_id=client.id,
            status=JobStatus.published,
            work_state=work_state,
            competence_category_id=qa,
            champion_found_at=datetime.now(timezone.utc) if champion else None,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _seed_recruiter() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        marker = uuid.uuid4().hex[:10]
        user = User(
            email=f"rb-{marker}@example.com",
            name=f"Rekruter RB {marker}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
        )
        db.add(user)
        await db.commit()
        return user.id


async def test_review_tab_lists_the_job_and_patch_moves_it_to_searching(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _seed_job()
    resp = await app_client.get(
        "/api/request-work-states",
        params={"tab": "to_review"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200
    assert job_id in {row["job_id"] for row in resp.json()["rows"]}

    patch = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "searching"}]},
        headers=app_auth_headers,
    )
    assert patch.status_code == 200
    assert patch.json()["changed"] == [job_id]

    again = await app_client.get(
        "/api/request-work-states",
        params={"tab": "searching"},
        headers=app_auth_headers,
    )
    assert job_id in {row["job_id"] for row in again.json()["rows"]}


async def test_unknown_state_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _seed_job()
    resp = await app_client.patch(
        "/api/request-work-states",
        json={"changes": [{"job_id": job_id, "state": "champion"}]},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422


async def test_board_shows_manual_person_and_champion_is_not_load(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    searching = await _seed_job(work_state="searching")
    champion = await _seed_job(work_state="searching")
    person = await _seed_recruiter()
    for job_id in (searching, champion):
        added = await app_client.post(
            f"/api/request-board/jobs/{job_id}/people",
            json={"user_id": person, "role": "recruiter"},
            headers=app_auth_headers,
        )
        assert added.status_code == 200, added.text
    # Champion pojawia się po przypisaniu — osoba zostaje, ale to nie obłożenie.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, champion)
        job.champion_found_at = datetime.now(timezone.utc)
        await db.commit()

    board = (
        await app_client.get("/api/request-board", headers=app_auth_headers)
    ).json()
    rows = {r["job_id"]: r for r in board["requests"]}
    assert rows[searching]["champion"] is False
    assert rows[champion]["champion"] is True
    assert [p["user_id"] for p in rows[searching]["people"]] == [person]
    load = {p["user_id"]: p for p in board["load"]}
    assert load[person]["count"] == 1
    assert [r["job_id"] for r in load[person]["requests"]] == [searching]

    removed = await app_client.delete(
        f"/api/request-board/jobs/{searching}/people/{person}",
        headers=app_auth_headers,
    )
    assert removed.json() == {"removed": True}


async def test_competence_team_assign_and_exclude(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person = await _seed_recruiter()
    team = (
        await app_client.get("/api/competence-team", headers=app_auth_headers)
    ).json()
    qa = next(c for c in team["categories"] if c["slug"] == "security_quality")
    assert person in {p["user_id"] for p in team["unassigned"]}

    put = await app_client.put(
        "/api/competence-team/assignments",
        json={"user_id": person, "competence_category_id": qa["id"], "priority": 1},
        headers=app_auth_headers,
    )
    assert put.status_code == 200, put.text
    team = (
        await app_client.get("/api/competence-team", headers=app_auth_headers)
    ).json()
    qa = next(c for c in team["categories"] if c["slug"] == "security_quality")
    assert person in {p["user_id"] for p in qa["first"]}

    excluded = await app_client.patch(
        f"/api/competence-team/people/{person}/allocation",
        json={"excluded": True},
        headers=app_auth_headers,
    )
    assert excluded.json()["allocation_excluded"] is True
    team = (
        await app_client.get("/api/competence-team", headers=app_auth_headers)
    ).json()
    assert person in {p["user_id"] for p in team["excluded"]}


async def test_rules_validation_is_polish_and_strict(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    bad = await app_client.put(
        "/api/competence-team/rules",
        json={"sourcer_threshold": 0, "review_time": "8:30"},
        headers=app_auth_headers,
    )
    assert bad.status_code == 422
    good = await app_client.put(
        "/api/competence-team/rules",
        json={"sourcer_threshold": 15, "review_time": "08:30"},
        headers=app_auth_headers,
    )
    assert good.json() == {"sourcer_threshold": 15, "review_time": "08:30"}


async def test_manual_add_needs_a_request_in_work(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    person = await _seed_recruiter()
    for job_id in (
        await _seed_job(work_state="to_review"),
        await _seed_job(work_state="searching", champion=True),
    ):
        resp = await app_client.post(
            f"/api/request-board/jobs/{job_id}/people",
            json={"user_id": person, "role": "recruiter"},
            headers=app_auth_headers,
        )
        assert resp.status_code == 409


async def test_lead_recruiter_is_adopted_and_manual_removal_sticks() -> None:
    from datetime import datetime, timezone

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment
    from app.services.request_allocation import (
        _adopt_owners,
        _blocked,
        manual_remove,
    )

    job_id = await _seed_job(work_state="searching")
    owner = await _seed_recruiter()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.recruiter_id = owner
        await db.commit()

    async def live_rows() -> list[tuple[int, str]]:
        async with AsyncSessionLocal() as db:
            return [
                (row.user_id, row.source)
                for row in (
                    await db.scalars(
                        select(JobWorkAssignment).where(
                            JobWorkAssignment.job_id == job_id,
                            JobWorkAssignment.state != "released",
                        )
                    )
                ).all()
            ]

    async with AsyncSessionLocal() as db:
        now = datetime.now(timezone.utc)
        await _adopt_owners(db, blocked=await _blocked(db), now=now)
        await db.commit()
    assert await live_rows() == [(owner, "owner")]

    async with AsyncSessionLocal() as db:
        assert await manual_remove(db, job_id=job_id, user_id=owner)
        await db.commit()
    async with AsyncSessionLocal() as db:
        blocked = await _blocked(db)
        assert (job_id, owner) in blocked
        await _adopt_owners(db, blocked=blocked, now=datetime.now(timezone.utc))
        await db.commit()
    assert await live_rows() == []


async def test_reopened_job_goes_back_to_review(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Zamknięcie → „Zakończony”, ponowne otwarcie → „Do przejrzenia”.

    Audyt 24.09.2026: PATCH ``closed → published`` zostawiał ``finished``,
    więc opublikowana rekrutacja wypadała z puli przydziału, pulpitu
    „Requesty” i nocnego przeglądu bazy, bez żadnego sygnału.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    job_id = await _seed_job(work_state="searching")

    closed = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "closed"}, headers=app_auth_headers
    )
    assert closed.status_code == 200, closed.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).work_state == "finished"

    reopened = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "published"}, headers=app_auth_headers
    )
    assert reopened.status_code == 200, reopened.text
    async with AsyncSessionLocal() as db:
        assert (await db.get(Job, job_id)).work_state == "to_review"
