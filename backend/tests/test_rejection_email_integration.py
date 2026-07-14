"""Integration tests for the rejection-email feature.

Tests the DB-touching paths (scheduler.maybe_schedule + cancel endpoint)
against a live postgres. Uses the `AsyncSessionLocal` pattern from the rest
of the suite so we share connection pools + event loops.

What we test:
  * maybe_schedule creates a row when `cv_sent → rejected` (business rule)
  * maybe_schedule returns None for internal-only rejections (screening →
    rejected) — no email to candidate
  * maybe_schedule returns None when the candidate has no email
  * the "other active processes" query surfaces only non-terminal OTHER jobs
  * POST /api/rejection-emails/{id}/cancel transitions pending → cancelled
  * cancel is idempotent when already cancelled
  * cancel returns 409 for non-pending/non-cancelled statuses

Dispatch (actual Graph send) is left out — requires m365_sender mocking that
adds complexity beyond this pass. The unit-test module covers the render path.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.rejection_email import (
    RejectionEmailStatus,
    ScheduledRejectionEmail,
)
from app.models.user import User, UserRole
from app.services.rejection_email_scheduler import (
    _load_other_active_processes,
    maybe_schedule,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_entities():
    """Create a recruiter, a candidate (with email) and two jobs.

    Uses raw SQL for the jobs insert to keep the fixture focused on the
    columns used by rejection-email scheduling.
    Returns a dict of ids.
    """
    from sqlalchemy import text

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"rec-{suffix}@example.com",
            password_hash=hash_password("P@ss"),
            name="Recruiter Test",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(recruiter)
        await db.flush()

        candidate = Candidate(
            name="Jan",
            lastname=f"Test{suffix}",
            email=f"cand-{suffix}@example.com",
            status=CandidateStatus.active,
        )
        db.add(candidate)
        await db.flush()

        client = Client(name=f"Rejection Client {suffix}")
        db.add(client)
        await db.flush()

        # Raw SQL for jobs — bypasses ORM drift. Only populate required columns.
        job_primary_id = (
            await db.execute(
                text(
                    "INSERT INTO jobs "
                    "(title, status, priority, recruiter_id, "
                    " recruitment_type, remote_policy, client_id) "
                    "VALUES (:title, 'published', 'medium', :rec, "
                    "        'body_leasing', 'hybrid', :client_id) "
                    "RETURNING id"
                ),
                {
                    "title": f"Primary Role {suffix}",
                    "rec": recruiter.id,
                    "client_id": client.id,
                },
            )
        ).scalar_one()
        job_other_id = (
            await db.execute(
                text(
                    "INSERT INTO jobs "
                    "(title, status, priority, recruiter_id, "
                    " recruitment_type, remote_policy, client_id) "
                    "VALUES (:title, 'published', 'medium', :rec, "
                    "        'body_leasing', 'hybrid', :client_id) "
                    "RETURNING id"
                ),
                {
                    "title": f"Other Active Role {suffix}",
                    "rec": recruiter.id,
                    "client_id": client.id,
                },
            )
        ).scalar_one()

        await db.commit()

        ids = {
            "recruiter_id": recruiter.id,
            "candidate_id": candidate.id,
            "job_primary_id": job_primary_id,
            "job_other_id": job_other_id,
            "client_id": client.id,
            "recruiter_email": recruiter.email,
        }

    yield ids

    # Cleanup — delete everything we created so repeated runs stay clean.
    # Order matters because of FKs. `scheduled_rejection_emails` references
    # the other tables, so it goes first; then candidate_stages; then
    # activities/notifications/user_activities that FK on users; then base.
    from sqlalchemy import text

    async with AsyncSessionLocal() as db:
        await db.execute(
            text(
                "DELETE FROM scheduled_rejection_emails WHERE candidate_id = :cid"
            ),
            {"cid": ids["candidate_id"]},
        )
        await db.execute(
            text("DELETE FROM candidate_stages WHERE candidate_id = :cid"),
            {"cid": ids["candidate_id"]},
        )
        # Activities / notifications / user_activities written by the
        # scheduler + cancel endpoint FK to users + candidates. Nuke them
        # so the subsequent user + job + candidate deletes succeed. The
        # column names differ between tables: activities/user_activities
        # use `entity_type/entity_id`, notifications uses `related_entity_*`.
        for table in ("activities", "user_activities"):
            await db.execute(
                text(
                    f"DELETE FROM {table} WHERE user_id = :uid "
                    "OR (entity_type = 'candidate' AND entity_id = :cid)"
                ),
                {"uid": ids["recruiter_id"], "cid": ids["candidate_id"]},
            )
        await db.execute(
            text("DELETE FROM notifications WHERE user_id = :uid"),
            {"uid": ids["recruiter_id"]},
        )
        await db.execute(
            text("DELETE FROM candidates WHERE id = :cid"),
            {"cid": ids["candidate_id"]},
        )
        await db.execute(
            text("DELETE FROM jobs WHERE id = ANY(:ids)"),
            {"ids": [ids["job_primary_id"], ids["job_other_id"]]},
        )
        await db.execute(
            text("DELETE FROM clients WHERE id = :client_id"),
            {"client_id": ids["client_id"]},
        )
        await db.execute(
            text("DELETE FROM users WHERE id = :uid"),
            {"uid": ids["recruiter_id"]},
        )
        await db.commit()


async def _add_stage(
    db, *, candidate_id: int, job_id: int, stage: PipelineStage, moved_by: int
) -> CandidateStage:
    s = CandidateStage(
        candidate_id=candidate_id,
        job_id=job_id,
        stage=stage,
        moved_at=datetime.now(timezone.utc),
        moved_by=moved_by,
    )
    db.add(s)
    await db.flush()
    return s


# ── Tests: maybe_schedule ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedules_when_previous_stage_is_cv_sent(seeded_entities):
    """Core business rule: cv_sent → rejected schedules an email even
    though STAGE_CATEGORY labels cv_sent as internal."""
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        # Previous stage: cv_sent
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=ids["recruiter_id"],
        )
        # Current stage: rejected (the move we're testing)
        rejected_stage = await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.rejected,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])

        scheduled = await maybe_schedule(
            db,
            stage=rejected_stage,
            job=job,
            recruiter_id=ids["recruiter_id"],
        )
        assert scheduled is not None
        assert scheduled.status == RejectionEmailStatus.pending
        assert scheduled.to_email == f"cand-{ids['recruiter_email'].split('-')[1].split('@')[0]}@example.com" or scheduled.to_email.endswith("@example.com")
        assert scheduled.recruiter_id == ids["recruiter_id"]
        # Scheduled 15 minutes out (±1 minute tolerance)
        delta = scheduled.scheduled_at - datetime.now(timezone.utc)
        assert 14 * 60 <= delta.total_seconds() <= 16 * 60
        # Snapshot fields populated
        assert scheduled.subject
        assert "{{candidate_name}}" not in scheduled.body_html  # rendered
        await db.commit()


@pytest.mark.asyncio
async def test_skips_when_previous_stage_is_internal_only(seeded_entities):
    """screening → rejected must NOT schedule (too early, candidate never
    reached client-visible stage)."""
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.screening,
            moved_by=ids["recruiter_id"],
        )
        rejected_stage = await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.rejected,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])

        scheduled = await maybe_schedule(
            db,
            stage=rejected_stage,
            job=job,
            recruiter_id=ids["recruiter_id"],
        )
        assert scheduled is None
        await db.commit()


@pytest.mark.asyncio
async def test_skips_when_candidate_has_no_email(seeded_entities):
    """No candidate.email → no email to send → skip scheduling."""
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, ids["candidate_id"])
        candidate.email = None
        await db.flush()

        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=ids["recruiter_id"],
        )
        rejected_stage = await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.rejected,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])

        scheduled = await maybe_schedule(
            db,
            stage=rejected_stage,
            job=job,
            recruiter_id=ids["recruiter_id"],
        )
        assert scheduled is None
        await db.commit()


@pytest.mark.asyncio
async def test_other_processes_excludes_current_and_terminals(seeded_entities):
    """The "other active processes" query must:
    - exclude the current job (no self-reference)
    - include jobs where candidate is at active stage
    - exclude jobs where candidate is at rejected/withdrawn/hired
    """
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        # Candidate has an ACTIVE stage (screening) on the OTHER job.
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_other_id"],
            stage=PipelineStage.screening,
            moved_by=ids["recruiter_id"],
        )
        # Candidate has a cv_sent on the PRIMARY job (will become current).
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=ids["recruiter_id"],
        )
        await db.commit()

        others = await _load_other_active_processes(
            db,
            candidate_id=ids["candidate_id"],
            current_job_id=ids["job_primary_id"],
        )
        titles = {o["title"] for o in others}
        assert any("Other Active Role" in t for t in titles)
        assert not any("Primary Role" in t for t in titles)

    # Now progress the other job to `hired` — it must disappear from the list.
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_other_id"],
            stage=PipelineStage.hired,
            moved_by=ids["recruiter_id"],
        )
        await db.commit()

        others_after = await _load_other_active_processes(
            db,
            candidate_id=ids["candidate_id"],
            current_job_id=ids["job_primary_id"],
        )
        assert others_after == [] or all(
            "Other Active Role" not in o["title"] for o in others_after
        )


# ── Tests: cancel endpoint ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_endpoint_transitions_pending_to_cancelled(
    app_client, app_auth_headers, seeded_entities
):
    """POST /api/rejection-emails/{id}/cancel flips a pending row to cancelled."""
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=ids["recruiter_id"],
        )
        rejected_stage = await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.rejected,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])
        scheduled = await maybe_schedule(
            db,
            stage=rejected_stage,
            job=job,
            recruiter_id=ids["recruiter_id"],
        )
        await db.commit()
        row_id = scheduled.id

    resp = await app_client.post(
        f"/api/rejection-emails/{row_id}/cancel", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["status"] == "cancelled"
    assert payload["cancelled_at"] is not None

    # Calling cancel again is idempotent — status stays cancelled, still 200.
    resp2 = await app_client.post(
        f"/api/rejection-emails/{row_id}/cancel", headers=app_auth_headers
    )
    assert resp2.status_code == 200
    assert resp2.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_returns_409_for_sent_email(
    app_client, app_auth_headers, seeded_entities
):
    """Trying to cancel an already-sent email → 409 (can't un-send)."""
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=ids["recruiter_id"],
        )
        rejected_stage = await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.rejected,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])
        scheduled = await maybe_schedule(
            db,
            stage=rejected_stage,
            job=job,
            recruiter_id=ids["recruiter_id"],
        )
        # Simulate the dispatcher having sent it.
        scheduled.status = RejectionEmailStatus.sent
        scheduled.sent_at = datetime.now(timezone.utc)
        await db.commit()
        row_id = scheduled.id

    resp = await app_client.post(
        f"/api/rejection-emails/{row_id}/cancel", headers=app_auth_headers
    )
    assert resp.status_code == 409
    assert "pending" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_get_endpoint_returns_snapshot(
    app_client, app_auth_headers, seeded_entities
):
    """GET /api/rejection-emails/{id} returns the full snapshot for preview."""
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.client_interview,
            moved_by=ids["recruiter_id"],
        )
        rejected_stage = await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.rejected,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])
        scheduled = await maybe_schedule(
            db,
            stage=rejected_stage,
            job=job,
            recruiter_id=ids["recruiter_id"],
        )
        await db.commit()
        row_id = scheduled.id

    resp = await app_client.get(
        f"/api/rejection-emails/{row_id}", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == row_id
    assert body["status"] == "pending"
    assert body["subject"]
    assert body["body_html"]
    assert isinstance(body["other_processes"], list)
