"""Membership + eligibility gate on pipeline ingress (P1-PIPE-01).

Two contracts, wired into every pipeline stage-writing / reading ingress:

* **Membership** — since 23.09.2026 (decyzja Artura: „wszystko w rekrutacji
  widzi i robi każdy, nie musisz być przypisany") every internal role passes
  the job-membership gate: a recruiter who is NOT on the job's team reads the
  kanban and stage history, moves, bulk-moves, records feedback and screening
  exactly like a member. The legacy viewer role ``user`` is outside that set
  and is refused. Assignment still matters for PERSONAL views, which call the
  gate with ``oversight_bypass=False`` — pinned here at service level.

* **Eligibility** — a hard-blocked candidate (global blacklist; a hiring-manager
  veto is covered in ``test_manager_rejection_gate.py``) is rejected **identically**
  (HTTP 409, Polish reason) at ``/move`` AND ``/bulk-move`` — the same contract
  the assign ingresses already enforce. Eligibility is isolated from membership
  by acting as admin (who bypasses membership), so the 409 is unambiguously the
  eligibility block. Terminal *removal* moves stay allowed (a blacklisted
  candidate can be rejected/withdrawn out of a pipeline). Since 17.09.2026 an
  active client blacklist / NDA / competitor conflict is a WARNING and moves
  the candidate like anyone else.

* **Carry-over scope** — when Priority Work is active, owning an OPEN
  ``RecruitmentProcess`` widens job scope for the membership path
  (``oversight_bypass=False`` or the legacy ``user`` role). Ownership alone is
  self-grantable, so it only counts when the process was opened in compliance
  with a published plan.

Uses the in-process ``app_client`` / ``app_auth_headers`` fixtures (real
postgres in CI). ``app_auth_headers`` logs in an admin, so it is used both as
the oversight-bypass caller and for the eligibility tests.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal

MOVE = "/api/pipeline/move"
BULK_MOVE = "/api/pipeline/bulk-move"
FEEDBACK = "/api/interview-feedback"
SCREENING = "/api/pipeline/stages/{stage_id}/screening"


# ── seed helpers ─────────────────────────────────────────────────────────────


async def _seed_recruiter(
    app_client: AsyncClient, role: str = "recruiter"
) -> tuple[dict[str, str], int]:
    """Seed a user (recruiter by default) and return (auth headers, user id)."""
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
            role=UserRole(role),
            roles=[role],
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


async def _seed_stage(candidate_id: int, job_id: int, stage_value: str) -> int:
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        row = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=datetime.now(timezone.utc),
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


async def _seed_open_process(
    candidate_id: int,
    job_id: int,
    owner_id: int,
    *,
    compliant: bool | None,
) -> None:
    """An OPEN process owned by ``owner_id`` with a frozen compliance verdict.

    Mirrors what ``_create_process`` writes: a shadow-mode self-open records
    ``priority_compliant_at_open=False``, an assignment-backed open records
    ``True``, and legacy/backfilled rows keep ``NULL``.
    """
    from app.models.recruitment_process import ProcessStatus, RecruitmentProcess

    async with AsyncSessionLocal() as db:
        db.add(
            RecruitmentProcess(
                candidate_id=candidate_id,
                job_id=job_id,
                status=ProcessStatus.open,
                owner_user_id=owner_id,
                priority_compliant_at_open=compliant,
                opened_at=datetime.now(timezone.utc),
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


# ── membership: a recruiter outside the team works like a member (23.09.2026) ─


async def test_non_member_recruiter_reads_the_kanban(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    # Job owned by nobody → the recruiter is not a member.
    job_id, _client_id = await _seed_job(owner_id=None)
    cand = await _seed_candidate()
    await _seed_stage(cand, job_id, "new")

    r = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["job_id"] == job_id
    on_board = {
        item["candidate_id"] for col in body["columns"] for item in col["items"]
    }
    assert cand in on_board


async def test_non_member_recruiter_reads_the_history(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)
    stage_id = await _seed_stage(cand, job_id, "new")

    r = await app_client.get(f"/api/pipeline/history/{cand}/{job_id}", headers=headers)
    assert r.status_code == 200, r.text
    assert [row["id"] for row in r.json()] == [stage_id]


async def test_non_member_recruiter_moves(app_client: AsyncClient):
    headers, uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.post(MOVE, json=_move_body(cand, job_id), headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["stage"] == "screening"
    assert r.json()["moved_by"] == uid


async def test_non_member_recruiter_bulk_moves(app_client: AsyncClient):
    headers, _uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.post(
        BULK_MOVE,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "screening"},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["moved"] == 1


async def test_non_member_recruiter_passes_the_gate_on_feedback(
    app_client: AsyncClient,
):
    headers, _uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    r = await app_client.post(
        FEEDBACK, json=_feedback_body(cand, job_id), headers=headers
    )
    # Past the membership gate: the bogus calendar event is what refuses it.
    assert r.status_code == 404, r.text
    assert r.json()["detail"] == "Nie znaleziono eventu"


async def test_legacy_viewer_role_is_still_refused(app_client: AsyncClient):
    """Rola podglądu ``user`` nie jest rolą wewnętrzną — tablica i ruch 403."""
    headers, _uid = await _seed_recruiter(app_client, role="user")
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)

    kanban = await app_client.get(f"/api/pipeline/kanban/{job_id}", headers=headers)
    assert kanban.status_code == 403, kanban.text
    move = await app_client.post(MOVE, json=_move_body(cand, job_id), headers=headers)
    assert move.status_code == 403, move.text


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


# ── carry-over scope: ownership alone must not grant it ──────────────────────
# Since 23.09.2026 internal roles bypass membership on the shared surfaces, so
# the carry-over path only matters where assignment is still counted: personal
# views (``oversight_bypass=False``) and the legacy ``user`` role. It is pinned
# at service level. A recruiter can make themselves the owner of an OPEN
# process on any job (`POST /api/candidates/from-linkedin` runs no membership
# check, and in shadow mode the policy records the violation as
# `priority_compliant_at_open=False`) — ownership alone must not count.


async def _personal_scope_status(user_id: int, job_id: int) -> int:
    """HTTP status ``ensure_job_membership(oversight_bypass=False)`` answers with."""
    from fastapi import HTTPException

    from app.api.recruitment_access import ensure_job_membership
    from app.models.user import User

    async with AsyncSessionLocal() as db:
        user = await db.get(User, user_id)
        try:
            await ensure_job_membership(db, user, job_id, oversight_bypass=False)
        except HTTPException as exc:
            return exc.status_code
    return 200


@pytest.mark.parametrize("compliant", [False, None])
async def test_self_opened_carry_over_does_not_grant_personal_job_scope(
    app_client: AsyncClient, monkeypatch, compliant: bool | None
):
    """False = shadow-mode violation, NULL = legacy/backfill. Both fail closed."""
    from app.core.config import settings
    from app.models.recruitment_priority import PriorityMode

    monkeypatch.setattr(
        settings, "RECRUITMENT_PRIORITY_MODE", PriorityMode.shadow.value
    )
    _headers, uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)  # recruiter is no member
    await _seed_open_process(cand, job_id, uid, compliant=compliant)

    assert await _personal_scope_status(uid, job_id) == 403


async def test_compliant_carry_over_still_grants_personal_job_scope(
    app_client: AsyncClient, monkeypatch
):
    """The capability itself stays intact for a plan-backed open.

    ``priority_compliant_at_open`` is frozen at open time and untouched by
    ``handoff_process``, so a HoR handoff keeps conferring scope on the new
    owner exactly as it does here.
    """
    from app.core.config import settings
    from app.models.recruitment_priority import PriorityMode

    monkeypatch.setattr(
        settings, "RECRUITMENT_PRIORITY_MODE", PriorityMode.shadow.value
    )
    _headers, uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)
    await _seed_open_process(cand, job_id, uid, compliant=True)

    assert await _personal_scope_status(uid, job_id) == 200


async def test_carry_over_scope_is_inert_when_priority_mode_is_off(
    app_client: AsyncClient, monkeypatch
):
    """With the module off, no process grants job scope."""
    from app.core.config import settings
    from app.models.recruitment_priority import PriorityMode

    monkeypatch.setattr(settings, "RECRUITMENT_PRIORITY_MODE", PriorityMode.off.value)
    _headers, uid = await _seed_recruiter(app_client)
    cand = await _seed_candidate()
    job_id, _client_id = await _seed_job(owner_id=None)
    await _seed_open_process(cand, job_id, uid, compliant=True)

    assert await _personal_scope_status(uid, job_id) == 403


async def test_personal_scope_counts_ownership(app_client: AsyncClient):
    """Widok osobisty liczy przypisanie: właściciel przechodzi, nieistniejąca
    rekrutacja to 404."""
    _headers, uid = await _seed_recruiter(app_client)
    job_id, _client_id = await _seed_job(owner_id=uid)

    assert await _personal_scope_status(uid, job_id) == 200
    assert await _personal_scope_status(uid, 2_000_000_000) == 404


# ── eligibility: hard-blocked candidate rejected identically at every ingress ─
# Acting as admin isolates the eligibility 409 from the membership 403.


async def test_blacklisted_candidate_warns_on_move_and_blocks_bulk(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.services.candidate_job_eligibility import (
        _REASON_LABELS_PL,
        EligibilityReason,
    )

    cand = await _seed_candidate(status="blacklisted")
    job_id, _client_id = await _seed_job(owner_id=None)
    expected = _REASON_LABELS_PL[EligibilityReason.blacklisted]

    # Pojedynczy /move (17.09.2026): ostrzeżenie do potwierdzenia, nie blokada.
    move = await app_client.post(
        MOVE, json=_move_body(cand, job_id), headers=app_auth_headers
    )
    assert move.status_code == 409, move.text
    assert move.json()["detail"]["code"] == "ELIGIBILITY_WARNING"
    assert move.json()["detail"]["reason"] == expected
    acknowledged = await app_client.post(
        MOVE,
        json={**_move_body(cand, job_id), "acknowledge_eligibility": True},
        headers=app_auth_headers,
    )
    assert acknowledged.status_code == 200, acknowledged.text

    bulk = await app_client.post(
        BULK_MOVE,
        json={"candidate_ids": [cand], "job_id": job_id, "stage": "screening"},
        headers=app_auth_headers,
    )
    assert bulk.status_code == 409, bulk.text
    assert expected in bulk.json()["detail"]


async def test_active_client_nda_does_not_block_move_or_bulk(
    app_client: AsyncClient, app_auth_headers: dict
):
    """17.09.2026: an NDA with the job's client is a warning, never a 409."""
    cand = await _seed_candidate()
    job_id, client_id = await _seed_job(owner_id=None)
    await _seed_conflict(cand, client_id, "nda")

    move = await app_client.post(
        MOVE, json=_move_body(cand, job_id), headers=app_auth_headers
    )
    assert move.status_code == 200, move.text

    bulk = await app_client.post(
        BULK_MOVE,
        json={
            "candidate_ids": [cand],
            "job_id": job_id,
            "stage": "cv_sent",
            "client_rate_value": "150",
        },
        headers=app_auth_headers,
    )
    assert bulk.status_code == 200, bulk.text


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


# ── membership: screening answers follow the job's pipeline scope ────────────


async def test_non_member_recruiter_reads_and_writes_screening(
    app_client: AsyncClient,
):
    """Od 23.09.2026 screening cudzej rekrutacji czyta i zapisuje każdy
    rekruter — do tej daty rekruter spoza zespołu dostawał 403."""
    headers, _uid = await _seed_recruiter(app_client)
    job_id, _client_id = await _seed_job(owner_id=None)
    cand_id = await _seed_candidate()
    stage_id = await _seed_stage(cand_id, job_id, "screening")

    r = await app_client.get(SCREENING.format(stage_id=stage_id), headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["stage_id"] == stage_id

    r = await app_client.post(
        SCREENING.format(stage_id=stage_id),
        headers=headers,
        json={"overall_fit": "fit"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stage_id"] == stage_id


async def test_member_recruiter_allowed_on_screening(app_client: AsyncClient):
    headers, uid = await _seed_recruiter(app_client)
    job_id, _client_id = await _seed_job(owner_id=uid)
    cand_id = await _seed_candidate()
    stage_id = await _seed_stage(cand_id, job_id, "screening")

    r = await app_client.get(SCREENING.format(stage_id=stage_id), headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["stage_id"] == stage_id

    r = await app_client.post(
        SCREENING.format(stage_id=stage_id),
        headers=headers,
        json={"overall_fit": "fit"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["stage_id"] == stage_id
