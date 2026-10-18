"""M7-P0.8 — only an ACCEPTED verification counts / anchors credit.

A move to ``verified`` with a rate above budget writes the row immediately as
``verification_status='pending'`` (migration 0056); a rejection leaves that row
on ``verified`` and only flips the status to ``rejected``. Before the fix the
canonical view ``analytics_first_milestones`` counted every ``verified`` row
regardless of status, so a pending/rejected attempt:

  * inflated ``first_verifications`` (KPI), and
  * anchored downstream credit — ``kpi_panel.VERIFIER_ANCHORED_CTE`` reads the
    view and makes the first ``verified`` mover the ``credit_user`` for every
    later milestone, so a rejected verifier stole the hire/cv_sent credit.

The view now filters ``verified`` to ``verification_status='active'``. These
tests seed directly (real Postgres in CI: ``alembic upgrade heads`` runs first)
and assert both halves.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

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
from app.models.recruitment_priority import PriorityOriginKind
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess

# Bez tego importu rejestr mapperów nie zna `Skill` i CAŁY plik wywala się na
# `CortexSkillFact` — plik przechodził tylko dlatego, że inny moduł suity
# zaimportował go pierwszy.
from app.models.skill import Skill as _Skill  # noqa: F401
from app.models.user import User, UserRole
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

# Po 12.10.2026: wcześniej statystyki liczą tylko DynaReportera (migracje 0454,
# 0467), a test sprawdza ruchy Tablicy.
T0 = datetime(2027, 7, 1, 9, 0, tzinfo=timezone.utc)


async def _seed(db, *, verified_status: VerificationStatus, second_user_cv_sent: bool):
    """One candidate×job: verified(user_a, given status) [+ cv_sent(user_b)]."""
    u = uuid.uuid4().hex[:8]
    user_a = User(
        email=f"kpi-a-{u}@example.com",
        password_hash=hash_password("x"),
        name="Verifier A",
        role=UserRole.recruiter,
        is_active=True,
    )
    user_b = User(
        email=f"kpi-b-{u}@example.com",
        password_hash=hash_password("x"),
        name="Mover B",
        role=UserRole.recruiter,
        is_active=True,
    )
    client = Client(name=f"KPI Client {u}")
    db.add_all([user_a, user_b, client])
    await db.flush()
    job = Job(title=f"KPI Job {u}", client_id=client.id)
    cand = Candidate(name="Kacper", lastname=f"PI-{u}")
    db.add_all([job, cand])
    await db.flush()

    db.add(
        CandidateStage(
            candidate_id=cand.id,
            job_id=job.id,
            stage=PipelineStage.verified,
            moved_at=T0 + timedelta(days=1),
            moved_by=user_a.id,
            verification_status=verified_status,
        )
    )
    if second_user_cv_sent:
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.cv_sent,
                moved_at=T0 + timedelta(days=2),
                moved_by=user_b.id,
            )
        )
    await db.commit()
    return {
        "candidate_id": cand.id,
        "job_id": job.id,
        "user_a_id": user_a.id,
        "user_b_id": user_b.id,
    }


@pytest.mark.parametrize(
    "status,should_count",
    [
        (VerificationStatus.active, True),
        (VerificationStatus.pending, False),
        (VerificationStatus.rejected, False),
    ],
)
async def test_verified_counts_only_when_accepted(status, should_count):
    async with AsyncSessionLocal() as db:
        ids = await _seed(db, verified_status=status, second_user_cv_sent=False)
        row = (
            await db.execute(
                text(
                    "SELECT COUNT(*) AS n FROM analytics_first_milestones "
                    "WHERE candidate_id = :cid AND job_id = :jid AND stage = 'verified'"
                ),
                {"cid": ids["candidate_id"], "jid": ids["job_id"]},
            )
        ).one()
    assert (row.n == 1) is should_count, (
        f"verified with status={status.value}: expected "
        f"{'counted' if should_count else 'excluded'}, got n={row.n}"
    )


async def test_rejected_verifier_does_not_anchor_credit():
    """A rejected verifier must NOT steal credit for a later milestone."""
    async with AsyncSessionLocal() as db:
        ids = await _seed(
            db, verified_status=VerificationStatus.rejected, second_user_cv_sent=True
        )
        rows = (
            await db.execute(
                text(
                    VERIFIER_ANCHORED_CTE + "SELECT stage, credit_user FROM credited "
                    "WHERE candidate_id = :cid AND job_id = :jid"
                ),
                {"cid": ids["candidate_id"], "jid": ids["job_id"]},
            )
        ).all()
    by_stage = {r.stage: r.credit_user for r in rows}

    # The rejected `verified` row is gone from the view entirely.
    assert "verified" not in by_stage, "rejected verification still in the view"
    # cv_sent credit falls back to its own mover (user_b), not the rejected
    # verifier (user_a) — no anchor to steal it.
    assert by_stage.get("cv_sent") == ids["user_b_id"], (
        "cv_sent credit was anchored to the rejected verifier (M7-P0.8 regressed)"
    )


async def _seed_classified(db, *, with_accepted_verified: bool):
    """One candidate×job behind a CLASSIFIED (non-legacy) recruitment process.

    ``credit_user_id`` is only ever written when an accepted ``verified``
    happens, so ``with_accepted_verified=False`` reproduces the shape that used
    to fall through every branch of the CTE: a process opened after the Priority
    Work rollout whose recruiter went cv_sent → client_interview → hired.
    """
    u = uuid.uuid4().hex[:8]
    user_a = User(
        email=f"kpi-cls-a-{u}@example.com",
        password_hash=hash_password("x"),
        name="Mover A",
        role=UserRole.recruiter,
        is_active=True,
    )
    user_b = User(
        email=f"kpi-cls-b-{u}@example.com",
        password_hash=hash_password("x"),
        name="Mover B",
        role=UserRole.recruiter,
        is_active=True,
    )
    client = Client(name=f"KPI Cls Client {u}")
    db.add_all([user_a, user_b, client])
    await db.flush()
    job = Job(title=f"KPI Cls Job {u}", client_id=client.id)
    cand = Candidate(name="Klara", lastname=f"CLS-{u}")
    db.add_all([job, cand])
    await db.flush()

    if with_accepted_verified:
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.verified,
                moved_at=T0 + timedelta(days=1),
                moved_by=user_a.id,
                verification_status=VerificationStatus.active,
            )
        )
    db.add_all(
        [
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.cv_sent,
                moved_at=T0 + timedelta(days=2),
                moved_by=user_a.id,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.client_interview,
                moved_at=T0 + timedelta(days=3),
                moved_by=user_b.id,
            ),
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.hired,
                moved_at=T0 + timedelta(days=4),
                moved_by=user_b.id,
            ),
        ]
    )
    db.add(
        RecruitmentProcess(
            candidate_id=cand.id,
            job_id=job.id,
            client_id=client.id,
            attempt_no=1,
            status=ProcessStatus.open,
            origin_kind=PriorityOriginKind.assigned,
            opened_at=T0,
            kpi_eligible=True,
            credit_user_id=user_a.id if with_accepted_verified else None,
        )
    )
    await db.commit()
    return {
        "candidate_id": cand.id,
        "job_id": job.id,
        "user_a_id": user_a.id,
        "user_b_id": user_b.id,
    }


async def _credited(db, ids) -> list[tuple[str, int]]:
    rows = (
        await db.execute(
            text(
                VERIFIER_ANCHORED_CTE + "SELECT stage, credit_user FROM credited "
                "WHERE candidate_id = :cid AND job_id = :jid "
                "ORDER BY stage"
            ),
            {"cid": ids["candidate_id"], "jid": ids["job_id"]},
        )
    ).all()
    return [(r.stage, r.credit_user) for r in rows]


async def test_second_hired_in_a_later_attempt_is_not_a_second_placement():
    """Para zatrudniona w próbie 1 i jeszcze raz w próbie 2 — jeden placement.

    Produkcja 15.10.2026: „Zatrudniony” wpisany ręcznie w NEXUSIE, a dzień
    później ten sam z importu Traffita, który otwierał nową próbę procesu
    chwilą zatrudnienia. Każda próba dawała placement, więc cztery pary
    liczyły się dwa razy (październik 19 zamiast 16). Weryfikacja nowej
    próby nadal się liczy — to jest praca, nie powtórzony wynik.
    """
    async with AsyncSessionLocal() as db:
        u = uuid.uuid4().hex[:8]
        user = User(
            email=f"kpi-rehire-{u}@example.com",
            password_hash=hash_password("x"),
            name="Mover R",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"KPI Rehire Client {u}")
        db.add_all([user, client])
        await db.flush()
        job = Job(title=f"KPI Rehire Job {u}", client_id=client.id)
        cand = Candidate(name="Romek", lastname=f"RH-{u}")
        db.add_all([job, cand])
        await db.flush()
        second_attempt_at = T0 + timedelta(days=6)
        db.add_all(
            [
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=T0 + timedelta(days=5),
                    moved_by=user.id,
                ),
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.verified,
                    moved_at=second_attempt_at + timedelta(hours=1),
                    moved_by=user.id,
                    verification_status=VerificationStatus.active,
                ),
                CandidateStage(
                    candidate_id=cand.id,
                    job_id=job.id,
                    stage=PipelineStage.hired,
                    moved_at=second_attempt_at + timedelta(hours=2),
                    moved_by=user.id,
                ),
                RecruitmentProcess(
                    candidate_id=cand.id,
                    job_id=job.id,
                    client_id=client.id,
                    attempt_no=1,
                    status=ProcessStatus.closed,
                    origin_kind=PriorityOriginKind.external_observed,
                    opened_at=T0,
                    closed_at=T0 + timedelta(days=5),
                    kpi_eligible=False,
                ),
                RecruitmentProcess(
                    candidate_id=cand.id,
                    job_id=job.id,
                    client_id=client.id,
                    attempt_no=2,
                    status=ProcessStatus.closed,
                    origin_kind=PriorityOriginKind.external_observed,
                    opened_at=second_attempt_at,
                    closed_at=second_attempt_at + timedelta(hours=2),
                    kpi_eligible=False,
                ),
            ]
        )
        await db.commit()
        credited = await _credited(db, {"candidate_id": cand.id, "job_id": job.id})

    assert sorted(credited) == [("hired", user.id), ("verified", user.id)], (
        f"the same pair was placed twice across process attempts: {credited}"
    )


async def test_classified_process_without_verifier_still_credits_the_mover():
    """No accepted `verified` must not delete the milestones from KPI.

    Before the fallback the anchored branch required both `credit_user_id` and
    a `verified` row, and the legacy branch only covers history predating the
    first classified process — so this whole process was credited to nobody and
    silently vanished from "Moje KPI", reports, top_recruiters and hall of fame.
    """
    async with AsyncSessionLocal() as db:
        ids = await _seed_classified(db, with_accepted_verified=False)
        credited = await _credited(db, ids)

    assert sorted(credited) == sorted(
        [
            ("cv_sent", ids["user_a_id"]),
            ("client_interview", ids["user_b_id"]),
            ("hired", ids["user_b_id"]),
        ]
    ), f"milestones lost or misattributed without a verifier anchor: {credited}"


async def test_verifier_anchor_still_wins_and_never_double_counts():
    """With an anchor the verifier keeps every later milestone — exactly once."""
    async with AsyncSessionLocal() as db:
        ids = await _seed_classified(db, with_accepted_verified=True)
        credited = await _credited(db, ids)

    stages = [stage for stage, _ in credited]
    assert len(stages) == len(set(stages)), (
        f"a milestone was counted by both the anchor and the fallback: {credited}"
    )
    assert sorted(credited) == sorted(
        [
            ("verified", ids["user_a_id"]),
            ("cv_sent", ids["user_a_id"]),
            ("client_interview", ids["user_a_id"]),
            ("hired", ids["user_a_id"]),
        ]
    ), f"anchored attribution regressed: {credited}"
