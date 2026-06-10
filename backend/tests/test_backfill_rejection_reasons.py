"""Tests for the Traffit rejection backfills.

Covers backfill_rejection_notes_from_activities (reason → rejection_note):
  - Reason is copied onto the rejected stage when (candidate_id, moved_at)
    matches the Traffit "Zmiana etapu" activity exactly.
  - Idempotent / additive: a stage that already has a rejection_note is never
    overwritten (recruiter-entered reasons are preserved).
  - Dry-run (rollback) writes nothing.
  - A rejected stage with no matching activity timestamp stays NULL.

And backfill_rejection_descriptions_from_activities (content.description → notes):
  - Recruiter's free-text comment lands in notes on an exact match.
  - Never overwrites an existing recruiter note.
  - Punctuation-only descriptions (e.g. ".") are skipped.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.services.traffit.rejection_backfill import (
    backfill_rejection_descriptions_from_activities,
    backfill_rejection_notes_from_activities,
)

pytestmark = pytest.mark.asyncio

# A fixed instant shared between the seeded rejected stage (moved_at) and the
# seeded activity (activity_date) — the backfill matches on this exact value.
_REJECTED_AT = datetime(2026, 5, 26, 9, 44, 39, tzinfo=timezone.utc)
_REJECTED_AT_STR = "2026-05-26 09:44:39"


async def _seed_candidate() -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="RejBackfill",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"rej-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_job() -> tuple[int, int]:
    """Returns (job_id, client_id) — candidate_stages.job_id is NOT NULL."""
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"RejBF-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(title=f"RejBF Job {uuid.uuid4().hex[:6]}", client_id=cli.id)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id, cli.id


async def _seed_rejected_stage(
    candidate_id: int,
    job_id: int,
    *,
    moved_at: datetime,
    rejection_note: str | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        cs = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage.rejected,
            moved_at=moved_at,
            rejection_note=rejection_note,
        )
        db.add(cs)
        await db.commit()
        await db.refresh(cs)
        return cs.id


async def _seed_rejection_activity(
    candidate_id: int, reason: str, *, description: str | None = None
) -> int:
    """Mirror the real Traffit shape: details.content is a JSON-encoded string."""
    content_obj = {
        "from_state": {"id": 23, "name": "Screening"},
        "to_state": {"id": 21, "name": "Odrzucony"},
        "rejection": {"id": 34, "name": reason},
    }
    if description is not None:
        content_obj["description"] = description
    content = json.dumps(content_obj)
    async with AsyncSessionLocal() as db:
        act = Activity(
            entity_type="candidate",
            entity_id=candidate_id,
            action="traffit:Zmiana etapu",
            details={"content": content, "activity_date": _REJECTED_AT_STR},
            external_source="traffit",
            external_id=f"test-{uuid.uuid4().hex[:10]}",
        )
        db.add(act)
        await db.commit()
        await db.refresh(act)
        return act.id


async def _get_rejection_note(stage_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        cs = await db.get(CandidateStage, stage_id)
        return cs.rejection_note if cs else None


async def _get_stage_notes(stage_id: int) -> str | None:
    async with AsyncSessionLocal() as db:
        cs = await db.get(CandidateStage, stage_id)
        return cs.notes if cs else None


async def _cleanup(candidate_id: int, job_id: int, client_id: int) -> None:
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStage).where(CandidateStage.candidate_id == candidate_id)
        )
        await db.execute(
            delete(Activity).where(
                Activity.entity_type == "candidate",
                Activity.entity_id == candidate_id,
            )
        )
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


async def test_backfill_populates_reason_on_exact_match() -> None:
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    stage_id = await _seed_rejected_stage(candidate_id, job_id, moved_at=_REJECTED_AT)
    await _seed_rejection_activity(candidate_id, "Po Interview")
    try:
        async with AsyncSessionLocal() as db:
            updated = await backfill_rejection_notes_from_activities(db)
            await db.commit()
        assert updated >= 1
        assert await _get_rejection_note(stage_id) == "Po Interview"
    finally:
        await _cleanup(candidate_id, job_id, client_id)


async def test_backfill_does_not_overwrite_existing_note() -> None:
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    stage_id = await _seed_rejected_stage(
        candidate_id, job_id, moved_at=_REJECTED_AT, rejection_note="Recruiter reason"
    )
    await _seed_rejection_activity(candidate_id, "Po Interview")
    try:
        async with AsyncSessionLocal() as db:
            await backfill_rejection_notes_from_activities(db)
            await db.commit()
        # Existing note preserved — backfill only fills empty rejection_note.
        assert await _get_rejection_note(stage_id) == "Recruiter reason"
    finally:
        await _cleanup(candidate_id, job_id, client_id)


async def test_backfill_dry_run_writes_nothing() -> None:
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    stage_id = await _seed_rejected_stage(candidate_id, job_id, moved_at=_REJECTED_AT)
    await _seed_rejection_activity(candidate_id, "Po Interview")
    try:
        async with AsyncSessionLocal() as db:
            updated = await backfill_rejection_notes_from_activities(db)
            await db.rollback()  # dry-run
        assert updated >= 1  # rowcount reflects what *would* change
        assert await _get_rejection_note(stage_id) is None  # but nothing persisted
    finally:
        await _cleanup(candidate_id, job_id, client_id)


async def test_backfill_skips_stage_without_matching_activity() -> None:
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    # Rejected stage at a DIFFERENT instant than the activity → no match.
    other_instant = datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
    stage_id = await _seed_rejected_stage(candidate_id, job_id, moved_at=other_instant)
    await _seed_rejection_activity(candidate_id, "Po Interview")  # at _REJECTED_AT
    try:
        async with AsyncSessionLocal() as db:
            await backfill_rejection_notes_from_activities(db)
            await db.commit()
        assert await _get_rejection_note(stage_id) is None
    finally:
        await _cleanup(candidate_id, job_id, client_id)


async def test_description_backfill_populates_notes_on_exact_match() -> None:
    """The recruiter's free-text comment (content.description) lands in
    candidate_stages.notes on an exact (candidate_id, moved_at) match."""
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    stage_id = await _seed_rejected_stage(candidate_id, job_id, moved_at=_REJECTED_AT)
    await _seed_rejection_activity(
        candidate_id, "Po CV", description="niezainteresowany"
    )
    try:
        async with AsyncSessionLocal() as db:
            updated = await backfill_rejection_descriptions_from_activities(db)
            await db.commit()
        assert updated >= 1
        assert await _get_stage_notes(stage_id) == "niezainteresowany"
    finally:
        await _cleanup(candidate_id, job_id, client_id)


async def test_description_backfill_does_not_overwrite_existing_notes() -> None:
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    async with AsyncSessionLocal() as db:
        cs = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage.rejected,
            moved_at=_REJECTED_AT,
            notes="Notatka rekrutera w NEXUS",
        )
        db.add(cs)
        await db.commit()
        await db.refresh(cs)
        stage_id = cs.id
    await _seed_rejection_activity(
        candidate_id, "Po CV", description="niezainteresowany"
    )
    try:
        async with AsyncSessionLocal() as db:
            await backfill_rejection_descriptions_from_activities(db)
            await db.commit()
        # Existing recruiter note preserved — backfill only fills empty notes.
        assert await _get_stage_notes(stage_id) == "Notatka rekrutera w NEXUS"
    finally:
        await _cleanup(candidate_id, job_id, client_id)


async def test_description_backfill_skips_punctuation_only() -> None:
    """A description of just "." carries no signal — it must NOT be copied."""
    candidate_id = await _seed_candidate()
    job_id, client_id = await _seed_job()
    stage_id = await _seed_rejected_stage(candidate_id, job_id, moved_at=_REJECTED_AT)
    await _seed_rejection_activity(candidate_id, "Po CV", description=".")
    try:
        async with AsyncSessionLocal() as db:
            await backfill_rejection_descriptions_from_activities(db)
            await db.commit()
        assert await _get_stage_notes(stage_id) is None
    finally:
        await _cleanup(candidate_id, job_id, client_id)
