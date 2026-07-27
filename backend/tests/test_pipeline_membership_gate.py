"""Membership + eligibility gate on pipeline ingress (P1-PIPE-01).

Two contracts, wired into every pipeline stage-writing / reading ingress:

* **Membership** — a recruiter who is NOT a member of a job (owner /
  delivery_lead / TAC / active collaborator) may not read or mutate that job's
  pipeline. Non-members get a **uniform 403** on kanban read, stage history,
  ``/move``, ``/bulk-move`` and job-scoped interview feedback. Members (here:
  the job owner) and oversight roles (admin) are not blocked. The gate is
  multi-role aware via ``has_any_role`` (delegated to
  ``services.job_membership.is_member_of_job``).

* **Eligibility** — a hard-blocked candidate (global blacklist, or an active
  client blacklist / NDA / competitor conflict) is rejected **identically**
  (HTTP 409, Polish reason) at ``/move`` AND ``/bulk-move`` — the same contract
  the assign ingresses already enforce. Eligibility is isolated from membership
  by acting as admin (who bypasses membership), so the 409 is unambiguously the
  eligibility block. Terminal *removal* moves stay allowed (a blacklisted
  candidate can be rejected/withdrawn out of a pipeline).

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures (real
postgres in CI). ``app_auth_headers`` logs in an admin, so it is used both as
the oversight-bypass caller and for the eligibility tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal

MOVE = "/api/pipeline/move"
BULK_MOVE = "/api/pipeline/bulk-move"
FEEDBACK = "/api/interview-feedback"


# ── seed helpers ─────────────────────────────────────────────────────────────


async def _seed_recruiter(app_client: AsyncClient) -> tuple[dict[str, str], int]:
    """Seed a recruiter and return (auth headers, user id)."""
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"pipe-gate-{unique}@example.com"
    password = f"T3st_{unique}!Pipe"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Pipe Gate Recruiter",
            role=UserRole.recruiter,
            roles=["recruiter"],
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


async def _seed_job(owner_id: int | None = None) -> tuple[int, int]:
    """Seed a job (+ client). ``owner_id`` → ``recruiter_id`` (job member)."""
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"PipeGateClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"PipeGate-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
            recruiter_id=owner_id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, cli.id


async def _seed_candidate(status: str = "active") -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Pipe",
            lastname=f"Gate-{uuid.uuid4().hex[:6]}",
            email=f"pipe-cand-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus(status),
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_stage(candidate_id: int, job_id: int, stage_value: str) -> None:
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage(stage_value),
                moved_at=datetime.now(timezone.utc),
            )
        )
        await db.commit()


async def _seed_conflict(candidate_id: int, client_id: int, type_: str) -> None:
    from app.models.candidate_conflict import CandidateConflict, ConflictType

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateConflict(
                candidate_id=candidate_id,
                client_id=client_id,
                type=ConflictType(type_),
                active=True,
            )
        )
        await db.commit()


def _move_body(candidate_id: int, job_id: int, stage: str = "screening") -> dict:
    return {"candidate_id": candidate_id, "job_id": job_id, "stage": stage}


def _feedback_body(candidate_id: int, job_id: int) -> dict:
    return {
        "calendar_event_id": 999999,
        "candidate_id": candidate_id,
        "job_id": job_id,
        "feedback_source": "candidate_side",
    }


# ── membership: non-member recruiter gets a uniform 403 ──────────────────────


async def test_non_member_recruiter_blocked_on_kanban_read(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    # Job owned by someone else → the recruiter is not a member.
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert r.status_code == 403, r.text


async def test_non_member_recruiter_blocked_on_history_read(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.get(f"/api/pipeline/history/{cand}/{job_id}", headers=headers)
    assert r.status_code == 403, r.text


async def test_non_member_recruiter_blocked_on_move(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.post(MOVE, json=_move_body(cand, job_id), headers=headers)
    assert r.status_code == 403, r.text


async def test_non_member_recruiter_blocked_on_bulk_move(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.post(
        BULK_MOVE,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "screening"},
        headers=headers,
    )
    assert r.status_code == 403, r.text


async def test_non_member_recruiter_blocked_on_feedback(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.post(
        FEEDBACK, json=_feedback_body(cand, job_id), headers=headers
    )
    assert r.status_code == 403, r.text


# ── membership: member (job owner) and admin are NOT blocked ─────────────────


async def test_member_recruiter_allowed_on_move_and_kanban(app_client: AsyncClient):
    headers, uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=uid)  # recruiter owns → member
    await _seed_stage(cand, job_id, "new")

    kanban = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert kanban.status_code == 200, kanban.text

    move = await app_client.post(MOVE, json=_move_body(cand, job_id), headers=headers)
    assert move.status_code == 200, move.text


async def test_member_recruiter_allowed_on_bulk_and_feedback(app_client: AsyncClient):
    headers, uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=uid)

    bulk = await app_client.post(
        BULK_MOVE,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "screening"},
        headers=headers,
    )
    assert bulk.status_code == 200, bulk.text

    # Membership passes → the 404 (bogus calendar event) proves we got past the
    # gate rather than being blocked at it.
    fb = await app_client.post(
        FEEDBACK, json=_feedback_body(cand, job_id), headers=headers
    )
    assert fb.status_code != 403, fb.text


async def test_admin_bypasses_membership_on_move(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)  # admin not a member

    r = await app_client.post(
        MOVE, json=_move_body(cand, job_id), headers=app_auth_headers
    )
    assert r.status_code == 200, r.text


# ── eligibility: hard-blocked candidate rejected identically at every ingress ─
# Acting as admin isolates the eligibility 409 from the membership 403.


async def test_blacklisted_candidate_blocked_on_move_and_bulk(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.services.candidate_job_eligibility import (
        _REASON_LABELS_PL,
        EligibilityReason,
    )

    cand = await _seed_candidate(status="blacklisted")
    job_id, _client_id = await _seed_job(owner_id=None)
    expected = _REASON_LABELS_PL[EligibilityReason.blacklisted]

    move = await app_client.post(
        MOVE, json=_move_body(cand, job_id), headers=app_auth_headers
    )
    assert move.status_code == 409, move.text
    assert move.json()["detail"] == expected

    bulk = await app_client.post(
        BULK_MOVE,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert bulk.status_code == 409, bulk.text
    assert expected in bulk.json()["detail"]


async def test_active_client_nda_blocked_on_move_and_bulk(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.services.candidate_job_eligibility import (
        _REASON_LABELS_PL,
        EligibilityReason,
    )

    cand = await _seed_candidate()
    job_id, client_id = await _seed_job(owner_id=None)
    await _seed_conflict(cand, client_id, "nda")
    expected = _REASON_LABELS_PL[EligibilityReason.client_nda]

    move = await app_client.post(
        MOVE, json=_move_body(cand, job_id), headers=app_auth_headers
    )
    assert move.status_code == 409, move.text
    assert move.json()["detail"] == expected

    bulk = await app_client.post(
        BULK_MOVE,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert bulk.status_code == 409, bulk.text
    assert expected in bulk.json()["detail"]


async def test_blacklisted_candidate_can_still_be_withdrawn(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Terminal REMOVAL stays allowed — the eligibility gate must not trap a
    blacklisted candidate inside a pipeline."""
    cand = await _seed_candidate(status="blacklisted")
    job_id, _client_id = await _seed_job(owner_id=None)
    await _seed_stage(cand, job_id, "screening")

    r = await app_client.post(
        MOVE,
        json={
            "candidate_id": cand,
            "job_id": job_id,
            "stage": "withdrawn",
            "rejection_reason": "candidate blacklisted",
        },
        headers=app_auth_headers,
    )
    # Not a 409 eligibility block (withdrawn is a removal). A withdrawn move
    # needs a dictionary reason → 422, never the eligibility 409.
    assert r.status_code != 409, r.text


async def test_clean_candidate_not_blocked_by_eligibility(
    app_client: AsyncClient, app_auth_headers: dict
):
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.post(
        MOVE, json=_move_body(cand, job_id), headers=app_auth_headers
    )
    assert r.status_code == 200, r.text
