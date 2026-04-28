"""Tests dla `candidate_stage_cvs` + `cv_share_tokens` (migracja 0069).

Sprawdzamy schemat:
* UNIQUE constraint na `candidate_stage_id` (1:1 gwarancja)
* CASCADE delete: usuń stage → znika cv_instance → znikają tokeny
* Default `branded_status='none'` i timestampy
* Partial index `WHERE branded_status='finalized'` istnieje w pg_indexes
"""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.cv_share_token import CVShareToken
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


async def _seed_minimal_stage() -> tuple[int, int, int]:
    """Seed candidate + client + job + stage, return (stage_id, candidate_id, job_id)."""
    unique = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Stage",
            lastname=f"CV{unique}",
            email=f"stage-cv-{unique}@example.com",
        )
        cli = Client(name=f"Klient CV {unique}")
        db.add_all([cand, cli])
        await db.flush()
        job = Job(
            title=f"Job CV {unique}",
            client_id=cli.id,
            description="x",
        )
        db.add(job)
        await db.flush()
        stage = CandidateStage(
            candidate_id=cand.id, job_id=job.id, stage=PipelineStage.new
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id, cand.id, job.id


@pytest.mark.asyncio
async def test_default_branded_status_is_none():
    stage_id, cand_id, job_id = await _seed_minimal_stage()
    async with AsyncSessionLocal() as db:
        csv = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=cand_id,
            job_id=job_id,
        )
        db.add(csv)
        await db.commit()
        await db.refresh(csv)
        assert csv.branded_status == "none"
        assert csv.created_at is not None
        assert csv.updated_at is not None


@pytest.mark.asyncio
async def test_unique_constraint_on_candidate_stage_id():
    """Druga próba insert dla tego samego stage → IntegrityError."""
    stage_id, cand_id, job_id = await _seed_minimal_stage()
    async with AsyncSessionLocal() as db:
        first = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=cand_id,
            job_id=job_id,
        )
        db.add(first)
        await db.commit()

    async with AsyncSessionLocal() as db:
        dup = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=cand_id,
            job_id=job_id,
        )
        db.add(dup)
        with pytest.raises(IntegrityError):
            await db.commit()


@pytest.mark.asyncio
async def test_cascade_delete_when_stage_removed():
    """Usunięcie CandidateStage → cv_instance znika (ON DELETE CASCADE)."""
    stage_id, cand_id, job_id = await _seed_minimal_stage()
    async with AsyncSessionLocal() as db:
        csv = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=cand_id,
            job_id=job_id,
        )
        db.add(csv)
        await db.commit()
        await db.refresh(csv)
        csv_id = csv.id

    async with AsyncSessionLocal() as db:
        # Raw SQL bo SQLA cascade wymaga relationship navigation; chcemy
        # zweryfikować ON DELETE CASCADE na poziomie bazy.
        await db.execute(
            text("DELETE FROM candidate_stages WHERE id = :sid"),
            {"sid": stage_id},
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        gone = await db.scalar(
            select(CandidateStageCV).where(CandidateStageCV.id == csv_id)
        )
        assert gone is None


@pytest.mark.asyncio
async def test_partial_index_finalized_exists():
    """Sanity: partial index `ix_csv_branded_finalized` istnieje w pg_indexes."""
    async with AsyncSessionLocal() as db:
        rows = await db.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE tablename='candidate_stage_cvs' "
                "AND indexname='ix_csv_branded_finalized'"
            )
        )
        names = [r[0] for r in rows.all()]
        assert names == ["ix_csv_branded_finalized"], (
            f"Expected partial index ix_csv_branded_finalized, got: {names}"
        )


@pytest.mark.asyncio
async def test_cv_share_token_cascade_on_csv_delete():
    """Usunięcie CandidateStageCV → znikają cv_share_tokens (CASCADE)."""
    stage_id, cand_id, job_id = await _seed_minimal_stage()
    async with AsyncSessionLocal() as db:
        csv = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=cand_id,
            job_id=job_id,
        )
        db.add(csv)
        await db.commit()
        await db.refresh(csv)
        csv_id = csv.id

        token_str = secrets.token_urlsafe(36)
        tok = CVShareToken(
            token=token_str,
            candidate_stage_cv_id=csv_id,
            expires_at=datetime.now(tz=timezone.utc) + timedelta(days=30),
        )
        db.add(tok)
        await db.commit()

    async with AsyncSessionLocal() as db:
        await db.execute(
            text("DELETE FROM candidate_stage_cvs WHERE id = :cid"),
            {"cid": csv_id},
        )
        await db.commit()

    async with AsyncSessionLocal() as db:
        gone = await db.scalar(
            select(CVShareToken).where(CVShareToken.token == token_str)
        )
        assert gone is None


@pytest.mark.asyncio
async def test_cv_share_token_revoked_default_false():
    stage_id, cand_id, job_id = await _seed_minimal_stage()
    async with AsyncSessionLocal() as db:
        csv = CandidateStageCV(
            candidate_stage_id=stage_id,
            candidate_id=cand_id,
            job_id=job_id,
        )
        db.add(csv)
        await db.commit()
        await db.refresh(csv)

        tok = CVShareToken(
            token=secrets.token_urlsafe(36),
            candidate_stage_cv_id=csv.id,
        )
        db.add(tok)
        await db.commit()
        await db.refresh(tok)
        assert tok.revoked is False
        assert tok.created_at is not None
