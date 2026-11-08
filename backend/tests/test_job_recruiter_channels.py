"""Koszyki „Baza” / „LinkedIn” w zespole rekrutacji (0655, decyzja Artura 06.11.2026).

* osoba w zespole ma koszyk ``base`` albo ``linkedin`` (albo żaden), widoczny
  w ``recruiters`` rekrutacji i w ``people`` pulpitu;
* rekruter przestawia siebie, cudzy koszyk i plan — tylko rola przydzielająca;
* rekruter spoza zespołu, który rusza karty, NIE jest blokowany — trafia do
  „pracuje bez przypisania” (ostrzeżenie zamiast bramki, „Kanban bez bramek”).

Baza testowa jest wspólna: każdy test zakłada własne osoby i rekrutacje.
"""

from __future__ import annotations

import os
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from tests.test_audit_r7_jobs import _seed_job as _seed_published_job
from tests.test_jobs_ownership import _drop_jobs, _login
from tests.test_jobs_ownership import _seed_user as _seed_login_user

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"),
]

_SEEDED: list[int] = []


@pytest_asyncio.fixture(autouse=True)
async def _drop_seeded_jobs():
    _SEEDED.clear()
    yield
    if _SEEDED:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.job_id.in_(_SEEDED))
            )
            await db.commit()
        await _drop_jobs(list(_SEEDED))


async def _job() -> int:
    job_id = await _seed_published_job("Channels", work_state="searching")
    _SEEDED.append(job_id)
    return job_id


async def _recruiter(client: AsyncClient) -> tuple[int, dict]:
    user_id, email, password = await _seed_login_user(UserRole.recruiter, "chan")
    return user_id, await _login(client, email, password)


async def _team(client: AsyncClient, headers: dict, job_id: int) -> dict[int, str | None]:
    response = await client.get(f"/api/jobs/{job_id}", headers=headers)
    assert response.status_code == 200, response.text
    return {
        person["user_id"]: person["channel"]
        for person in response.json()["recruiters"]
        if not person["proposed"]
    }


async def _move_card(job_id: int, user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Kanal",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"chan-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=candidate.id,
                job_id=job_id,
                stage=PipelineStage.new,
                moved_by=user_id,
            )
        )
        await db.commit()


async def test_join_with_channel_then_switch_shows_on_job_and_board(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _job()
    person, _ = await _recruiter(app_client)

    added = await app_client.post(
        f"/api/jobs/{job_id}/collaborators",
        json={"user_id": person, "channel": "linkedin"},
        headers=app_auth_headers,
    )
    assert added.status_code == 201, added.text
    assert (await _team(app_client, app_auth_headers, job_id))[person] == "linkedin"

    switched = await app_client.put(
        f"/api/jobs/{job_id}/channels/{person}",
        json={"channel": "base"},
        headers=app_auth_headers,
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["channel"] == "base"

    board = await app_client.get("/api/request-board", headers=app_auth_headers)
    assert board.status_code == 200, board.text
    row = next(r for r in board.json()["requests"] if r["job_id"] == job_id)
    assert {p["user_id"]: p["channel"] for p in row["people"]}[person] == "base"

    cleared = await app_client.put(
        f"/api/jobs/{job_id}/channels/{person}",
        json={"channel": None},
        headers=app_auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert (await _team(app_client, app_auth_headers, job_id))[person] is None


async def test_recruiter_moves_only_self_and_only_inside_the_team(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _job()
    me, my_headers = await _recruiter(app_client)
    other, _ = await _recruiter(app_client)

    outside = await app_client.put(
        f"/api/jobs/{job_id}/channels/{me}",
        json={"channel": "linkedin"},
        headers=my_headers,
    )
    assert outside.status_code == 409, outside.text

    for person in (me, other):
        added = await app_client.post(
            f"/api/jobs/{job_id}/collaborators",
            json={"user_id": person},
            headers=app_auth_headers,
        )
        assert added.status_code == 201, added.text

    own = await app_client.put(
        f"/api/jobs/{job_id}/channels/{me}",
        json={"channel": "linkedin"},
        headers=my_headers,
    )
    assert own.status_code == 200, own.text

    foreign = await app_client.put(
        f"/api/jobs/{job_id}/channels/{other}",
        json={"channel": "linkedin"},
        headers=my_headers,
    )
    assert foreign.status_code == 403, foreign.text
    team = await _team(app_client, app_auth_headers, job_id)
    assert team[me] == "linkedin"
    assert team[other] is None


async def test_plan_is_set_by_the_staffing_role_only(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _job()
    _, my_headers = await _recruiter(app_client)

    refused = await app_client.put(
        f"/api/jobs/{job_id}/channel-plan",
        json={"base": 2, "linkedin": 1},
        headers=my_headers,
    )
    assert refused.status_code == 403, refused.text

    too_many = await app_client.put(
        f"/api/jobs/{job_id}/channel-plan",
        json={"base": 21, "linkedin": 1},
        headers=app_auth_headers,
    )
    assert too_many.status_code == 422, too_many.text

    saved = await app_client.put(
        f"/api/jobs/{job_id}/channel-plan",
        json={"base": 2, "linkedin": 1},
        headers=app_auth_headers,
    )
    assert saved.status_code == 200, saved.text
    job = (await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)).json()
    assert (job["channel_plan_base"], job["channel_plan_linkedin"]) == (2, 1)


async def test_recruiter_moving_cards_outside_the_team_is_flagged_not_blocked(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    job_id = await _job()
    worker, _ = await _recruiter(app_client)
    await _move_card(job_id, worker)

    flagged = await app_client.get(
        f"/api/jobs/{job_id}/unassigned-workers", headers=app_auth_headers
    )
    assert flagged.status_code == 200, flagged.text
    assert [(w["user_id"], w["cards"]) for w in flagged.json()] == [(worker, 1)]

    board = await app_client.get("/api/request-board", headers=app_auth_headers)
    row = next(r for r in board.json()["requests"] if r["job_id"] == job_id)
    assert [w["user_id"] for w in row["unassigned_workers"]] == [worker]

    joined = await app_client.post(
        f"/api/jobs/{job_id}/collaborators",
        json={"user_id": worker, "channel": "base"},
        headers=app_auth_headers,
    )
    assert joined.status_code == 201, joined.text
    after = await app_client.get(
        f"/api/jobs/{job_id}/unassigned-workers", headers=app_auth_headers
    )
    assert after.json() == []
