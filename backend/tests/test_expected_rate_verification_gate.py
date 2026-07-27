"""M4-P0.4 — editing the candidate rate re-runs the budget approval gate.

The /move gate correctly forced ``verification_status=pending`` when a
``verified`` move carried an over-budget rate. But ``set_recruitment_expected_rate``
(PATCH .../expected-rate) wrote the rate onto the latest stage WITHOUT re-running
the gate. So a recruiter could move within budget (→ active, no approval), then
PATCH an over-budget rate — leaving a ``verified``/``active`` row above budget
with nobody's sign-off. RecruitmentRateEditAccess includes recruiter; approval
needs ApproverPlus — the bypass defeated that separation of duties.

Fix mirrors the /move gate on a ``verified`` stage: over budget (or a
non-comparable rate) → ``pending`` + budget snapshot + approver notification;
within budget → ``active``.

Behavioural against a real Postgres (CI runs migrations first).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.api.candidates import set_recruitment_expected_rate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.user import User, UserRole
from app.schemas.contract import RateUnit
from app.schemas.pipeline import ClientRateUpdate


async def _seed_verified(db, *, salary_max: int) -> tuple[int, int, User, int]:
    u = uuid.uuid4().hex[:8]
    client = Client(name=f"Rate {u}")
    cand = Candidate(name="Rate", lastname=f"Gate-{u}")
    user = User(
        email=f"rate-{u}@example.com", password_hash=hash_password("x"),
        name="R", role=UserRole.recruiter, is_active=True,
    )
    db.add_all([client, cand, user])
    await db.flush()
    # Rekruter musi NALEŻEĆ do oferty, której stawkę edytuje — bramka zakresu
    # zasobu tego wymaga, a produkcja i tak nie zna innego przypadku.
    job = Job(
        title=f"Rate Job {u}",
        client_id=client.id,
        salary_max=salary_max,
        recruiter_id=user.id,
    )
    db.add(job)
    await db.flush()
    stage = CandidateStage(
        candidate_id=cand.id,
        job_id=job.id,
        stage=PipelineStage.verified,
        moved_at=datetime.now(timezone.utc),
        moved_by=user.id,
        verification_status=VerificationStatus.active,
        budget_max_at_move=salary_max,
    )
    db.add(stage)
    await db.commit()
    return cand.id, job.id, user, stage.id


async def _status(db, stage_id: int) -> VerificationStatus:
    row = await db.get(CandidateStage, stage_id)
    return row.verification_status


async def test_over_budget_rate_edit_forces_pending() -> None:
    async with AsyncSessionLocal() as db:
        cid, jid, actor, sid = await _seed_verified(db, salary_max=20000)
        await set_recruitment_expected_rate(
            cid,
            jid,
            ClientRateUpdate(rate_value=Decimal("30000"), rate_unit=RateUnit.monthly),
            current_user=actor,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        assert await _status(db, sid) == VerificationStatus.pending, (
            "over-budget rate edit did not re-trigger approval (M4-P0.4 regressed)"
        )


async def test_within_budget_rate_edit_stays_active() -> None:
    async with AsyncSessionLocal() as db:
        cid, jid, actor, sid = await _seed_verified(db, salary_max=20000)
        await set_recruitment_expected_rate(
            cid,
            jid,
            ClientRateUpdate(rate_value=Decimal("15000"), rate_unit=RateUnit.monthly),
            current_user=actor,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        assert await _status(db, sid) == VerificationStatus.active


async def test_non_pln_rate_is_non_comparable_so_pending() -> None:
    """A currency we can't convert must fail closed to pending, never auto-pass."""
    async with AsyncSessionLocal() as db:
        cid, jid, actor, sid = await _seed_verified(db, salary_max=20000)
        await set_recruitment_expected_rate(
            cid,
            jid,
            ClientRateUpdate(
                rate_value=Decimal("100"), rate_unit=RateUnit.monthly, rate_currency="EUR"
            ),
            current_user=actor,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        assert await _status(db, sid) == VerificationStatus.pending
