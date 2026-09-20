"""``GET /api/pipeline/my-next-steps`` — boards of the caller's open recruitments.

Feeds the dashboard section "Następne kroki w moich rekrutacjach" (17.09.2026).
Scope is "mine" (owner or collaborator), without closed recruitments, and every
board passes the same read guard as ``/kanban/{job_id}`` — a collaborator removed
from the team is still matched by ``jobs_mine_clause`` and must be skipped.
The board is the SAME view as the kanban endpoint (one extraction, two routes).
"""

from __future__ import annotations

import uuid

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole

URL = "/api/pipeline/my-next-steps"


async def _seed_user(role: UserRole = UserRole.recruiter) -> tuple[dict, int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"next-steps-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Steps"),
            name=f"Next Steps {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role.value)}"}, uid


async def _seed_world(me: int, other: int) -> dict:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"NextStepsClient-{tag}")
        candidate = Candidate(
            name="Next", lastname=f"Steps-{tag}", email=f"ns-{tag}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()

        def job(label: str, owner: int, status=JobStatus.published) -> Job:
            return Job(
                title=f"NS-{label}-{tag}",
                status=status,
                client_id=client.id,
                recruiter_id=owner,
            )

        mine = job("mine", me)
        closed = job("closed", me, JobStatus.closed)
        foreign = job("foreign", other)
        collab = job("collab", other)
        removed = job("removed", other)
        db.add_all([mine, closed, foreign, collab, removed])
        await db.flush()
        db.add_all(
            [
                JobCollaborator(job_id=collab.id, user_id=me),
                JobCollaborator(
                    job_id=removed.id, user_id=me, removed_from_auto_cc=True
                ),
            ]
        )
        await db.commit()
        return {
            "client_name": client.name,
            "candidate_id": candidate.id,
            "mine": mine.id,
            "closed": closed.id,
            "foreign": foreign.id,
            "collab": collab.id,
            "removed": removed.id,
        }


@pytest.mark.asyncio
async def test_only_open_recruitments_of_the_caller_with_their_boards(
    app_client: AsyncClient, app_auth_headers: dict
):
    headers, me = await _seed_user()
    _, other = await _seed_user()
    world = await _seed_world(me, other)
    move = await app_client.post(
        "/api/pipeline/move",
        headers=app_auth_headers,
        json={
            "candidate_id": world["candidate_id"],
            "job_id": world["mine"],
            "stage": "screening",
        },
    )
    assert move.status_code == 200, move.text

    resp = await app_client.get(URL, headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["truncated"] is False
    by_id = {j["job_id"]: j for j in body["jobs"]}
    assert set(by_id) == {world["mine"], world["collab"]}
    assert by_id[world["mine"]]["client_name"] == world["client_name"]

    board = await app_client.get(
        f"/api/pipeline/kanban/{world['mine']}", headers=headers
    )
    assert board.status_code == 200, board.text
    assert by_id[world["mine"]]["view"] == board.json()
    cards = [
        item["candidate_id"]
        for column in by_id[world["mine"]]["view"]["columns"]
        for item in column["items"]
    ]
    assert cards == [world["candidate_id"]]


@pytest.mark.asyncio
async def test_requires_candidate_read(app_client: AsyncClient):
    assert (await app_client.get(URL)).status_code == 401
