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
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.rejection_email import (
    RejectionEmailStatus,
    ScheduledRejectionEmail,
)
from app.models.user import User, UserRole
from app.services import rejection_email_text as rejection_text
from app.services.rejection_email_scheduler import (
    _other_processes_for,
    dispatch,
    maybe_schedule,
    preview,
)


# ── Fixtures ───────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def seeded_entities():
    """Create a recruiter, a candidate (with email) and two jobs.

    Uses raw SQL for the jobs insert because the ORM `Job` model has newer
    columns (e.g. `closed_at`) not present on the local dev DB. This is a
    pre-existing schema/model drift — unrelated to rejection-email work.
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

        # Raw SQL for jobs/client — bypasses ORM drift. Only populate required
        # columns. `jobs.client_id` is NOT NULL (migration schema), so we seed
        # a throwaway client first.
        client_id = (
            await db.execute(
                text("INSERT INTO clients (name) VALUES (:name) RETURNING id"),
                {"name": f"Client {suffix}"},
            )
        ).scalar_one()
        job_primary_id = (
            await db.execute(
                text(
                    "INSERT INTO jobs "
                    "(title, status, priority, recruiter_id, client_id, "
                    " recruitment_type, remote_policy) "
                    "VALUES (:title, 'published', 'medium', :rec, :client, "
                    "        'body_leasing', 'hybrid') "
                    "RETURNING id"
                ),
                {
                    "title": f"Primary Role {suffix}",
                    "rec": recruiter.id,
                    "client": client_id,
                },
            )
        ).scalar_one()
        job_other_id = (
            await db.execute(
                text(
                    "INSERT INTO jobs "
                    "(title, status, priority, recruiter_id, client_id, "
                    " recruitment_type, remote_policy) "
                    "VALUES (:title, 'published', 'medium', :rec, :client, "
                    "        'body_leasing', 'hybrid') "
                    "RETURNING id"
                ),
                {
                    "title": f"Other Active Role {suffix}",
                    "rec": recruiter.id,
                    "client": client_id,
                },
            )
        ).scalar_one()

        await db.commit()

        ids = {
            "recruiter_id": recruiter.id,
            "candidate_id": candidate.id,
            "client_id": client_id,
            "job_primary_id": job_primary_id,
            "job_other_id": job_other_id,
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
            text("DELETE FROM scheduled_rejection_emails WHERE candidate_id = :cid"),
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
        assert (
            scheduled.to_email
            == f"cand-{ids['recruiter_email'].split('-')[1].split('@')[0]}@example.com"
            or scheduled.to_email.endswith("@example.com")
        )
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


async def _approve_public_profile(db, job_id: int, public_title: str) -> None:
    """Zatwierdzony opis publiczny rekrutacji (skrót liczony jak w serwisie)."""
    from app.models.job_public_profile import JobPublicProfile
    from app.services.job_public_profile import content_hash, public_titles

    job = await db.get(Job, job_id)
    profile = JobPublicProfile(
        job_id=job_id,
        public_title=public_title,
        subtitle="Projekt dla banku",
        about="Opis roli",
    )
    db.add(profile)
    await db.flush()
    _default, effective = await public_titles(db, job, profile)
    profile.approved_hash = content_hash(
        profile.subtitle, profile.about, profile.sections, effective
    )
    profile.approved_at = datetime.now(timezone.utc)
    await db.flush()


async def _set_job_title(db, job_id: int, title: str) -> None:
    """Nazwa od klienta bez losowego sufiksu fixture (cztery cyfry = kod)."""
    from sqlalchemy import text

    await db.execute(
        text("UPDATE jobs SET title = :title WHERE id = :id"),
        {"title": title, "id": job_id},
    )
    db.expire_all()


@pytest.mark.asyncio
async def test_other_processes_are_jobs_after_verification(seeded_entities):
    """Pozostałe rekrutacje w mailu (17.10.2026, D2 i D5):
    - bez bieżącej rekrutacji,
    - tylko opublikowane, w których osoba jest od „Zweryfikowany” do „Umowa”,
    - nazwa dla kandydata bez numeru zlecenia i klienta, inaczej bez nazwy,
    - zatwierdzony opis na stronę kariery wygrywa,
    - bez rekrutacji zakończonych zatrudnieniem.
    """
    ids = seeded_entities
    cid = ids["candidate_id"]
    rid = ids["recruiter_id"]
    other_id = ids["job_other_id"]

    async def others(db):
        return await _other_processes_for(
            db, candidate_ids=[cid], exclude_job_ids={ids["job_primary_id"]}
        )

    async with AsyncSessionLocal() as db:
        await _set_job_title(db, other_id, "Programista Java")
        # Przed weryfikacją — osoba nie wie jeszcze, że bierze udział.
        await _add_stage(
            db, candidate_id=cid, job_id=other_id, stage=PipelineStage.screening, moved_by=rid
        )
        await _add_stage(
            db,
            candidate_id=cid,
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=rid,
        )
        await db.commit()
        assert await others(db) == {}

        await _add_stage(
            db, candidate_id=cid, job_id=other_id, stage=PipelineStage.verified, moved_by=rid
        )
        await db.commit()
        found = (await others(db))[cid]
        assert [(p.job_id, p.mail_title, p.column) for p in found] == [
            (other_id, "Programista Java", "verified")
        ]

        # Numer zlecenia w nazwie — do kandydata idzie bez nazwy.
        await _set_job_title(db, other_id, "Analityk 123456 danych")
        await db.commit()
        found = (await others(db))[cid]
        assert found[0].mail_title is None
        assert found[0].title == "Analityk 123456 danych"

        # Zatwierdzony opis publiczny wygrywa.
        await _approve_public_profile(db, other_id, "Programista Java")
        await db.commit()
        assert (await others(db))[cid][0].mail_title == "Programista Java"

        # Rekrutacja zamknięta znika z listy.
        other_job = await db.get(Job, other_id)
        other_job.status = JobStatus.closed
        await db.commit()
        assert await others(db) == {}
        other_job.status = JobStatus.published
        await db.commit()

    # Zatrudnienie w innej rekrutacji — ten proces się skończył.
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db, candidate_id=cid, job_id=other_id, stage=PipelineStage.hired, moved_by=rid
        )
        await db.commit()
        assert await others(db) == {}


@pytest.mark.asyncio
async def test_schedules_from_verified_with_the_before_client_text(seeded_entities):
    """D1 i D4 (17.10.2026): po rozmowie z nami mail wychodzi, ale nie mówi,
    że „wybrano innego kandydata” — CV nie trafiło do klienta."""
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _set_job_title(db, ids["job_primary_id"], "Programista Java")
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.verified,
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
            db, stage=rejected_stage, job=job, recruiter_id=ids["recruiter_id"]
        )
        assert scheduled is not None
        assert scheduled.subject == "Informacja zwrotna — Programista Java"
        assert "nie przedstawimy Twojej kandydatury" in scheduled.body_html
        assert "inny kandydat" not in scheduled.body_html
        assert scheduled.body_html.endswith(f"<p>{rejection_text.CLOSING}</p>")
        details = await _scheduled_activity_details(db, scheduled)
        assert details["text_kind"] == "before_client"
        assert details["other_processes_appended"] is False
        await db.commit()


@pytest.mark.asyncio
async def test_other_processes_go_as_a_marker_unless_unchecked(seeded_entities):
    """D2: osoba w innej rekrutacji — zamiast zakończenia znacznik dopisku,
    wypełniany przy wysyłce. Odznaczony dopisek = zwykłe zakończenie."""
    ids = seeded_entities

    async def schedule(db, **kwargs):
        await _set_job_title(db, ids["job_other_id"], "Backend Developer")
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_other_id"],
            stage=PipelineStage.client_interview,
            moved_by=ids["recruiter_id"],
        )
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
        return await maybe_schedule(
            db,
            stage=rejected_stage,
            job=job,
            recruiter_id=ids["recruiter_id"],
            **kwargs,
        )

    async with AsyncSessionLocal() as db:
        scheduled = await schedule(db)
        assert scheduled is not None
        assert scheduled.body_html.endswith(rejection_text.OTHER_PROCESSES_MARKER)
        assert rejection_text.CLOSING not in scheduled.body_html
        assert scheduled.other_processes == [
            {"job_id": ids["job_other_id"], "title": "Backend Developer"}
        ]
        details = await _scheduled_activity_details(db, scheduled)
        assert details["other_processes_appended"] is True
        await db.rollback()

    async with AsyncSessionLocal() as db:
        scheduled = await schedule(db, append_other_processes=False)
        assert scheduled is not None
        assert rejection_text.OTHER_PROCESSES_MARKER not in scheduled.body_html
        assert scheduled.body_html.endswith(f"<p>{rejection_text.CLOSING}</p>")
        await db.rollback()


@pytest.mark.asyncio
async def test_cancel_refuses_a_send_in_progress(
    app_client, app_auth_headers, seeded_entities
):
    """Runda 9 (R9-N10-10): pętla wysyłki zatwierdziła rezerwację i znacznik
    „wysyłka ruszyła” — `/cancel` nie może odpowiedzieć „Anulowano”, bo mail
    wychodzi. Ruch przywracający kandydata też go nie anuluje."""
    from app.services.rejection_email_scheduler import SEND_IN_PROGRESS

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
            db, stage=rejected_stage, job=job, recruiter_id=ids["recruiter_id"]
        )
        scheduled.last_error = SEND_IN_PROGRESS
        await db.commit()
        row_id = scheduled.id

    resp = await app_client.post(
        f"/api/rejection-emails/{row_id}/cancel", headers=app_auth_headers
    )
    assert resp.status_code == 409, resp.text
    assert "trwa" in resp.json()["detail"]
    async with AsyncSessionLocal() as db:
        row = await db.get(ScheduledRejectionEmail, row_id)
        assert row.status == RejectionEmailStatus.pending

    moved = await app_client.post(
        "/api/pipeline/move",
        json={
            "candidate_id": ids["candidate_id"],
            "job_id": ids["job_primary_id"],
            "stage": "screening",
        },
        headers=app_auth_headers,
    )
    assert moved.status_code == 200, moved.text
    async with AsyncSessionLocal() as db:
        row = await db.get(ScheduledRejectionEmail, row_id)
        assert row.status == RejectionEmailStatus.pending


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


# ── Tests: dispatch() restore guard (audyt P1.7) ───────────────────────────


@pytest.mark.asyncio
async def test_dispatch_cancels_when_candidate_restored_off_rejected(seeded_entities):
    """Audyt P1.7 (defense-in-depth): kandydat PRZYWRÓCONY z odrzucenia zanim
    scheduler zdążył wysłać (np. przez `/bulk-move`, który NIE anuluje pending
    maili) — dispatch() musi wykryć, że aktualny etap pary to już nie
    `rejected`, oznaczyć mail jako `cancelled` i NIC nie wysłać."""
    ids = seeded_entities
    # 1) cv_sent -> rejected, zaplanuj mail (pending).
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
        assert scheduled is not None
        assert scheduled.status == RejectionEmailStatus.pending
        await db.commit()
        row_id = scheduled.id

    # 2) Restore: ruch na etap NIEterminalny (jak robi `/bulk-move`, który sam
    #    nie anuluje pending maila).
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.screening,
            moved_by=ids["recruiter_id"],
        )
        await db.commit()

    # 3) Dispatcher odpala — musi anulować, nie wysłać.
    async with AsyncSessionLocal() as db:
        await dispatch(db, row_id)

    async with AsyncSessionLocal() as db:
        row = await db.get(ScheduledRejectionEmail, row_id)
        assert row.status == RejectionEmailStatus.cancelled
        assert row.cancelled_at is not None
        assert row.email_id is None  # nic nie zostało wysłane


@pytest.mark.asyncio
async def test_dispatch_does_not_cancel_when_still_rejected(seeded_entities):
    """Kontrola pozytywna: kandydat NADAL odrzucony → guard nie anuluje.
    Bez podłączonej skrzynki M365 dispatch kończy się `skipped` (nie
    `cancelled`), co dowodzi, że guard nie nad-anulowuje legalnych odrzuceń."""
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

    async with AsyncSessionLocal() as db:
        await dispatch(db, row_id)

    async with AsyncSessionLocal() as db:
        row = await db.get(ScheduledRejectionEmail, row_id)
        # Guard przepuścił (wciąż rejected); brak skrzynki → skipped, nie sent.
        assert row.status == RejectionEmailStatus.skipped
        assert row.status != RejectionEmailStatus.cancelled


@pytest.mark.asyncio
async def test_dispatch_with_unknown_send_outcome_never_sends_twice(
    seeded_entities, monkeypatch
):
    """FIX-03 (audyt 22.09 r2): utracona odpowiedź Graph na ``/send``.

    Dawniej wyjątek ``EmailSendConflict`` wpadał w ogólne ``except``, rollback
    kasował wiersz ``uncertain``, a ponowienie (nowy klucz minutowy) wysyłało
    kandydatowi DRUGI mail odrzucenia. Teraz: wiersz harmonogramu = failed,
    bez ponowienia, wiersz ``Email`` zostaje jako ``uncertain``, rekruter
    dostaje prośbę o sprawdzenie folderu Wysłane.
    """
    from datetime import timedelta

    import httpx
    from sqlalchemy import delete

    from app.models.activity import Activity
    from app.models.m365 import Email, M365Connection
    from app.services import rejection_email_scheduler as sched
    from app.services.m365 import sender as sender_mod

    ids = seeded_entities
    sends: list[str] = []

    class _Graph:
        def __init__(self, connection, db):  # noqa: ANN001
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):  # noqa: ANN002
            return None

        async def get(self, url, params=None):  # noqa: ANN001
            return {"value": []}

        async def post(self, url, json=None, **_kw):  # noqa: ANN001
            if url.endswith("/send"):
                sends.append(url)
                raise httpx.ReadTimeout("lost")
            return {
                "id": f"draft-{uuid.uuid4().hex[:10]}",
                "conversationId": "conv-x",
                "internetMessageId": f"<{uuid.uuid4().hex[:10]}@t>",
            }

    async def _eligible_owner(db, user_id):  # noqa: ANN001
        return await db.get(User, user_id)

    async def _eligible_conn(db, connection):  # noqa: ANN001
        return None

    monkeypatch.setattr(sender_mod, "GraphClient", _Graph)
    monkeypatch.setattr(sender_mod, "require_eligible_connection_owner", _eligible_conn)
    monkeypatch.setattr(sender_mod.settings, "M365_SIGNATURE_INJECTION_ENABLED", False)
    monkeypatch.setattr(sched, "eligible_m365_owner", _eligible_owner)
    monkeypatch.setattr(sched, "_can_send_rejection_email", lambda user: True)

    async with AsyncSessionLocal() as db:
        conn = M365Connection(
            user_id=ids["recruiter_id"],
            tenant_id="tenant",
            mailbox_upn=ids["recruiter_email"],
            access_token_ct="x",
            refresh_token_ct="x",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_active=True,
        )
        db.add(conn)
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
            db, stage=rejected_stage, job=job, recruiter_id=ids["recruiter_id"]
        )
        await db.commit()
        row_id = scheduled.id
        conn_id = conn.id

    try:
        async with AsyncSessionLocal() as db:
            await dispatch(db, row_id)

        async with AsyncSessionLocal() as db:
            row = await db.get(ScheduledRejectionEmail, row_id)
            assert row.status == RejectionEmailStatus.failed
            assert row.last_error == "send_outcome_uncertain"
            assert row.email_id is not None
            email = await db.get(Email, row.email_id)
            assert email is not None and email.send_state == "uncertain"
            actions = (
                await db.scalars(
                    select(Activity.action).where(
                        Activity.entity_type == "candidate",
                        Activity.entity_id == ids["candidate_id"],
                    )
                )
            ).all()
            assert "rejection_email_uncertain" in actions
            # Wiersz nie jest już pending → kolejny bieg nic nie wysyła.
            row.status = RejectionEmailStatus.pending
            await db.commit()

        # Nawet gdyby ktoś przywrócił wiersz do kolejki, stały klucz trafia
        # w istniejący wiersz ``uncertain`` — Graph nie jest wołany ponownie.
        async with AsyncSessionLocal() as db:
            await dispatch(db, row_id)
        assert len(sends) == 1, "drugi mail odrzucenia do kandydata"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ScheduledRejectionEmail).where(
                    ScheduledRejectionEmail.id == row_id
                )
            )
            await db.execute(delete(Email).where(Email.user_id == ids["recruiter_id"]))
            await db.execute(delete(M365Connection).where(M365Connection.id == conn_id))
            await db.commit()


# ── Okno odrzucenia: podgląd i poprawiona treść (13.10.2026) ───────────────


async def _scheduled_activity_details(db, scheduled) -> dict:
    """Wpis historii `rejection_email_scheduled` tego wiersza harmonogramu."""
    from app.models.activity import Activity

    await db.flush()
    rows = (
        await db.scalars(
            select(Activity).where(
                Activity.action == "rejection_email_scheduled",
                Activity.entity_type == "candidate",
                Activity.entity_id == scheduled.candidate_id,
            )
        )
    ).all()
    matching = [
        r.details
        for r in rows
        if (r.details or {}).get("scheduled_rejection_email_id") == scheduled.id
    ]
    assert len(matching) == 1, [r.details for r in rows]
    return matching[0]


@pytest.mark.asyncio
async def test_default_mail_is_the_approved_text(seeded_entities):
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
            db, stage=rejected_stage, job=job, recruiter_id=ids["recruiter_id"]
        )
        assert scheduled is not None
        assert scheduled.body_html.startswith("<p>Cześć Jan,</p>")
        assert "Niestety został wybrany inny kandydat." in scheduled.body_html
        assert "Pozdrawiam" not in scheduled.body_html
        assert scheduled.template_id is None
        details = await _scheduled_activity_details(db, scheduled)
        assert details["edited"] is False
        await db.commit()


@pytest.mark.asyncio
async def test_text_edited_in_the_window_is_sent_escaped(seeded_entities):
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
            edited_subject="Rekrutacja <Senior> & co",
            edited_body="Cześć Jan,\n\nKlient wstrzymał <b>projekt</b>.",
        )
        assert scheduled is not None
        assert scheduled.subject == "Rekrutacja <Senior> & co"
        assert scheduled.body_html == (
            "<p>Cześć Jan,</p>\n<p>Klient wstrzymał &lt;b&gt;projekt&lt;/b&gt;.</p>"
        )
        assert scheduled.template_id is None
        details = await _scheduled_activity_details(db, scheduled)
        assert details["edited"] is True
        await db.commit()


@pytest.mark.asyncio
async def test_preview_says_who_gets_the_mail_and_shows_the_text(
    seeded_entities, monkeypatch
):
    from unittest.mock import AsyncMock

    import app.services.rejection_email_scheduler as scheduler

    monkeypatch.setattr(scheduler, "sender_has_mailbox", AsyncMock(return_value=True))
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.screening,
            moved_by=ids["recruiter_id"],
        )
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])
        other_job = await db.get(Job, ids["job_other_id"])
        sender = await db.get(User, ids["recruiter_id"])

        result = await preview(
            db, job=job, candidate_ids=[ids["candidate_id"]], sender=sender
        )
        assert [(p.candidate_id, p.skip_reason) for p in result.people] == [
            (ids["candidate_id"], None)
        ]
        assert result.people[0].to_email
        assert result.subject == f"Informacja zwrotna — {job.title}"
        assert result.body.startswith("Cześć Jan,\n\ndziękujemy za udział")

        # Osoby nie ma w tej rekrutacji → mail nie wyjdzie, treści brak.
        none_here = await preview(
            db, job=other_job, candidate_ids=[ids["candidate_id"]], sender=sender
        )
        assert none_here.people[0].skip_reason == "not_client_visible"
        assert none_here.people[0].to_email is None  # bez adresu spoza rekrutacji
        assert none_here.subject is None and none_here.body is None

        candidate = await db.get(Candidate, ids["candidate_id"])
        candidate.email = None
        await db.flush()
        no_email = await preview(
            db, job=job, candidate_ids=[ids["candidate_id"]], sender=sender
        )
        assert no_email.people[0].skip_reason == "no_candidate_email"
        await db.rollback()


@pytest.mark.asyncio
async def test_preview_without_mailbox_blocks_everyone(seeded_entities, monkeypatch):
    from unittest.mock import AsyncMock

    import app.services.rejection_email_scheduler as scheduler

    monkeypatch.setattr(scheduler, "sender_has_mailbox", AsyncMock(return_value=False))
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.cv_sent,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])
        sender = await db.get(User, ids["recruiter_id"])
        result = await preview(
            db, job=job, candidate_ids=[ids["candidate_id"]], sender=sender
        )
        assert result.people[0].skip_reason == "no_mailbox"
        assert result.subject is None
        await db.commit()


@pytest.mark.asyncio
async def test_preview_shows_other_processes_and_the_text_kind(
    seeded_entities, monkeypatch
):
    """Okno widzi rodzaj treści, pozostałe rekrutacje osoby i dopisek (D2)."""
    from unittest.mock import AsyncMock

    import app.services.rejection_email_scheduler as scheduler

    monkeypatch.setattr(scheduler, "sender_has_mailbox", AsyncMock(return_value=True))
    ids = seeded_entities
    async with AsyncSessionLocal() as db:
        await _set_job_title(db, ids["job_primary_id"], "Programista Java")
        await _set_job_title(db, ids["job_other_id"], "Backend Developer")
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_other_id"],
            stage=PipelineStage.client_interview,
            moved_by=ids["recruiter_id"],
        )
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_primary_id"],
            stage=PipelineStage.verified,
            moved_by=ids["recruiter_id"],
        )
        job = await db.get(Job, ids["job_primary_id"])
        sender = await db.get(User, ids["recruiter_id"])

        result = await preview(
            db, job=job, candidate_ids=[ids["candidate_id"]], sender=sender
        )
        person = result.people[0]
        assert person.skip_reason is None
        assert person.text_kind == "before_client"
        assert [(o.job_id, o.mail_title, o.column) for o in person.other_processes] == [
            (ids["job_other_id"], "Backend Developer", "client_interview")
        ]
        assert result.text_kind == "before_client"
        assert result.subject == "Informacja zwrotna — Programista Java"
        assert "nie przedstawimy Twojej kandydatury" in result.body
        assert result.closing == rejection_text.CLOSING
        assert "• Backend Developer" in result.other_processes_text
        assert [s.text_kind for s in result.samples] == ["before_client"]
        assert result.title_warning is False

        # Numer zlecenia w nazwie tej rekrutacji — okno ostrzega.
        await _set_job_title(db, ids["job_primary_id"], "Programista Java 123456")
        job = await db.get(Job, ids["job_primary_id"])
        result = await preview(
            db, job=job, candidate_ids=[ids["candidate_id"]], sender=sender
        )
        assert result.title_warning is True
        await db.rollback()


@pytest.mark.asyncio
async def test_dispatch_fills_the_list_as_of_sending(seeded_entities, monkeypatch):
    """D2: lista pozostałych rekrutacji liczona przy wysyłce — osoba odrzucona
    w międzyczasie także w drugiej rekrutacji nie przeczyta, że „nadal bierze
    w niej udział”, tylko zwykłe zakończenie."""
    from datetime import timedelta

    from sqlalchemy import delete

    from app.models.m365 import M365Connection
    from app.services import rejection_email_scheduler as sched
    from app.services.m365 import sender as sender_mod

    ids = seeded_entities
    sent: list[str] = []

    async def _send_new(db, connection, *, body_html, **_kw):  # noqa: ANN001
        sent.append(body_html)
        # Wynik nieznany = wiersz zamknięty bez ponowień; treść zostaje.
        raise sender_mod.EmailSendConflict("uncertain", None)

    async def _eligible_owner(db, user_id):  # noqa: ANN001
        return await db.get(User, user_id)

    monkeypatch.setattr(sender_mod, "send_new", _send_new)
    monkeypatch.setattr(sched, "eligible_m365_owner", _eligible_owner)
    monkeypatch.setattr(sched, "_can_send_rejection_email", lambda user: True)

    async with AsyncSessionLocal() as db:
        conn = M365Connection(
            user_id=ids["recruiter_id"],
            tenant_id="tenant",
            mailbox_upn=ids["recruiter_email"],
            access_token_ct="x",
            refresh_token_ct="x",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            is_active=True,
        )
        db.add(conn)
        await _set_job_title(db, ids["job_other_id"], "Backend Developer")
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_other_id"],
            stage=PipelineStage.verified,
            moved_by=ids["recruiter_id"],
        )
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
            db, stage=rejected_stage, job=job, recruiter_id=ids["recruiter_id"]
        )
        assert scheduled.body_html.endswith(rejection_text.OTHER_PROCESSES_MARKER)
        await db.commit()
        row_id = scheduled.id
        conn_id = conn.id

    # Zanim mail wyszedł, osoba odpadła także z drugiej rekrutacji.
    async with AsyncSessionLocal() as db:
        await _add_stage(
            db,
            candidate_id=ids["candidate_id"],
            job_id=ids["job_other_id"],
            stage=PipelineStage.rejected,
            moved_by=ids["recruiter_id"],
        )
        await db.commit()

    try:
        async with AsyncSessionLocal() as db:
            await dispatch(db, row_id)
        assert len(sent) == 1
        assert "nadal bierzesz udział" not in sent[0]
        assert sent[0].endswith(f"<p>{rejection_text.CLOSING}</p>")
        async with AsyncSessionLocal() as db:
            row = await db.get(ScheduledRejectionEmail, row_id)
            assert row.body_html == sent[0]
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(ScheduledRejectionEmail).where(
                    ScheduledRejectionEmail.id == row_id
                )
            )
            await db.execute(delete(M365Connection).where(M365Connection.id == conn_id))
            await db.commit()
