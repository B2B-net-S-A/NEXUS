"""Runda 10 audytu — obszar PIPE (backend rekrutacji).

Każdy test odtwarza jedno znalezisko z raportów V2/X2 rundy 10. Testy z bazą
(``app_client``) zakładają własne dane i filtrują po nich — baza CI jest
wspólna.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient

from app.core.scheduling import business_today
from app.models.job import Job
from app.models.user import User, UserRole


# ── R10-V2-3: job_scope_clause w widoku osobistym zna przypisania ────────────


def test_personal_scope_clause_counts_live_work_assignments() -> None:
    from app.api.recruitment_access import job_scope_clause

    recruiter = User(id=9101, role=UserRole.recruiter, is_active=True)
    personal = str(
        job_scope_clause(recruiter, Job.id, oversight_bypass=False).compile()
    )
    assert "job_work_assignments" in personal
    # Widok organizacyjny rekrutera nadal nie jest niczym zawężany.
    assert str(job_scope_clause(recruiter, Job.id)) == "true"


# ── R10-V2-2: „Moje następne kroki” — przypisania nie zjadają LIMIT ──────────


async def _seed_user(role: UserRole = UserRole.sourcer) -> tuple[dict, int]:
    from app.core.database import AsyncSessionLocal
    from app.core.security import create_access_token, hash_password

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"r10-pipe-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!Pipe"),
            name=f"R10 Pipe {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    return {"Authorization": f"Bearer {create_access_token(uid, role.value)}"}, uid


async def _seed_next_steps_world(me: int, other: int, *, via: str) -> tuple[set, int]:
    """27 rekrutacji z bliskim terminem „moich” tylko przez ``via`` + jedna
    własna z dalekim terminem."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import JobStatus
    from app.models.job_collaborator import JobCollaborator
    from app.models.job_work_assignment import JobWorkAssignment

    tag = uuid.uuid4().hex[:8]
    today = business_today()
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R10PipeNext-{tag}")
        db.add(client)
        await db.flush()
        near = [
            Job(
                title=f"R10-near-{i}-{tag}",
                status=JobStatus.published,
                client_id=client.id,
                recruiter_id=other,
                deadline=today + timedelta(days=1),
            )
            for i in range(27)
        ]
        own = Job(
            title=f"R10-own-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=me,
            deadline=today + timedelta(days=30),
        )
        db.add_all([*near, own])
        await db.flush()
        if via == "assignment":
            db.add_all(
                JobWorkAssignment(
                    job_id=job.id,
                    user_id=me,
                    role="sourcer",
                    source="manual",
                    state="active",
                )
                for job in near
            )
        else:
            db.add_all(
                JobCollaborator(job_id=job.id, user_id=me, removed_from_auto_cc=True)
                for job in near
            )
        await db.commit()
        return {job.id for job in near}, own.id


@pytest.mark.asyncio
async def test_my_next_steps_accepts_work_assignments(
    app_client: AsyncClient,
) -> None:
    headers, me = await _seed_user(UserRole.sourcer)
    _, other = await _seed_user(UserRole.recruiter)
    near, own = await _seed_next_steps_world(me, other, via="assignment")

    resp = await app_client.get("/api/pipeline/my-next-steps", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {j["job_id"] for j in body["jobs"]}
    # Przed poprawką: 26 przypisanych zajmowało LIMIT i każde było odrzucane
    # przez bramkę tablicy — lista pusta z `truncated=True`.
    assert body["truncated"] is True
    assert len(ids) == 25
    assert ids <= near


@pytest.mark.asyncio
async def test_my_next_steps_filters_removed_collaborators_before_limit(
    app_client: AsyncClient,
) -> None:
    headers, me = await _seed_user(UserRole.recruiter)
    _, other = await _seed_user(UserRole.recruiter)
    near, own = await _seed_next_steps_world(me, other, via="removed_collaborator")

    resp = await app_client.get("/api/pipeline/my-next-steps", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    ids = {j["job_id"] for j in body["jobs"]}
    assert ids == {own}
    assert body["truncated"] is False
