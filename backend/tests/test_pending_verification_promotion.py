"""Jednorazowe zaliczenie starych weryfikacji „Pending" (17.09.2026).

Bramka akceptacji została usunięta razem z całym swoim kodem — karty zapisane
wcześniej jako `pending` mają dostać to, co dałaby ręczna akceptacja: status
`active` i zaliczenie pierwszego weryfikatora (KPI).

Na produkcji blok wykonano 17.09.2026, ale zostaje: jest idempotentny (marker
w `app_settings` + advisory lock) i musi zadziałać przy świeżej instalacji oraz
przy odtworzeniu bazy z kopii sprzed tej daty.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.recruitment_process import RecruitmentProcess
from app.models.user import User, UserRole
from app.services.pending_verification_promotion import (
    run_pending_verification_promotion,
)


async def _seed_pending_stage() -> tuple[int, int, int, int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        recruiter = User(
            email=f"pvp-{tag}@example.com",
            password_hash=hash_password(f"Pvp_{tag}!pw"),
            name=f"PVP {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        client = Client(name=f"PVP Client {tag}")
        candidate = Candidate(
            name="Pvp", lastname=f"Test{tag}", email=f"pvp-cand-{tag}@example.com"
        )
        db.add_all([recruiter, client, candidate])
        await db.flush()
        job = Job(
            title=f"PVP Job {tag}",
            status=JobStatus.published,
            salary_max=10000,
            client_id=client.id,
            recruiter_id=recruiter.id,
        )
        db.add(job)
        await db.flush()
        stage = CandidateStage(
            candidate_id=candidate.id,
            job_id=job.id,
            stage=PipelineStage.verified,
            moved_by=recruiter.id,
            verification_status=VerificationStatus.pending,
            expected_rate_value=30000,
            budget_max_at_move=10000,
        )
        db.add(stage)
        await db.commit()
        return stage.id, recruiter.id, candidate.id, job.id


@pytest.mark.asyncio
async def test_promotes_pending_like_a_manual_acceptance() -> None:
    stage_id, recruiter_id, candidate_id, job_id = await _seed_pending_stage()

    async with AsyncSessionLocal() as db:
        summary = await run_pending_verification_promotion(
            db, only_stage_ids={stage_id}
        )
        await db.commit()
    assert summary is not None
    assert summary["promoted"] == 1 and summary["credited"] == 1
    assert summary["failed"] == 0

    async with AsyncSessionLocal() as db:
        stage = await db.get(CandidateStage, stage_id)
        process = await db.scalar(
            select(RecruitmentProcess)
            .where(
                RecruitmentProcess.candidate_id == candidate_id,
                RecruitmentProcess.job_id == job_id,
            )
            .order_by(RecruitmentProcess.id.desc())
            .limit(1)
        )
    assert stage is not None
    assert stage.verification_status == VerificationStatus.active
    assert stage.approved_at is not None
    # Nikt nie podjął tej decyzji — podjęła ją zmiana polityki.
    assert stage.approved_by is None
    assert process is not None and process.credit_user_id == recruiter_id

    # Drugi przebieg nie dotyka już zaliczonej karty.
    async with AsyncSessionLocal() as db:
        again = await run_pending_verification_promotion(db, only_stage_ids={stage_id})
        await db.commit()
    assert again is not None and again["found"] == 0
