"""The derivation behind the hiring-manager veto.

`load_manager_rejections` answers one question: has *this job's* hiring manager
already interviewed and turned this candidate down somewhere else? Everything
here pins a rule that, if it broke, would either freeze pipelines or block the
wrong people.

Runs against the real database via ``AsyncSessionLocal`` (same shape as the
DB-backed half of ``test_recommendation_filters.py``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

# Registers every mapper. Importing models piecemeal leaves relationships
# dangling and SQLAlchemy then refuses to configure *any* mapper. `Skill` is
# imported explicitly because app.models.__init__ does not re-export it, yet
# CortexSkillFact points at it by name.
import app.models  # noqa: F401
from app.models.skill import Skill  # noqa: F401

NOW = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)


async def _seed_world(
    *,
    two_managers: bool = False,
) -> dict:
    """Client + hiring manager(s) + two jobs + one candidate + a reason pair."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.contact import Contact
    from app.models.job import Job, JobStatus
    from app.models.pipeline_template import (
        PipelineTemplate,
        RejectionReason,
        TerminalType,
    )

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"VetoClient-{tag}")
        db.add(client)
        await db.commit()
        await db.refresh(client)

        manager = Contact(client_id=client.id, name=f"Anna Veto-{tag}")
        db.add(manager)
        other_manager = Contact(client_id=client.id, name=f"Piotr Other-{tag}")
        db.add(other_manager)
        await db.commit()
        await db.refresh(manager)
        await db.refresh(other_manager)

        source = Job(
            title=f"Source-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            hiring_manager_contact_id=manager.id,
        )
        target = Job(
            title=f"Target-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            hiring_manager_contact_id=(
                other_manager.id if two_managers else manager.id
            ),
        )
        db.add_all([source, target])

        template = PipelineTemplate(name=f"VetoTpl-{tag}")
        db.add(template)
        await db.commit()
        await db.refresh(source)
        await db.refresh(target)
        await db.refresh(template)

        disqualifying = RejectionReason(
            template_id=template.id,
            name=f"Za slaby technicznie-{tag}",
            category=TerminalType.rejected,
            disqualifies_person=True,
        )
        situational = RejectionReason(
            template_id=template.id,
            name=f"Za drogi-{tag}",
            category=TerminalType.rejected,
            disqualifies_person=False,
        )
        candidate = Candidate(
            name="Jan",
            lastname=f"Veto-{tag}",
            email=f"veto-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([disqualifying, situational, candidate])
        await db.commit()
        await db.refresh(disqualifying)
        await db.refresh(situational)
        await db.refresh(candidate)

        return {
            "client_id": client.id,
            "manager_id": manager.id,
            "manager_name": manager.name,
            "source_job_id": source.id,
            "target_job_id": target.id,
            "candidate_id": candidate.id,
            "disqualifying_reason_id": disqualifying.id,
            "situational_reason_id": situational.id,
        }


async def _seed_stage(
    *,
    candidate_id: int,
    job_id: int,
    stage: str,
    moved_at: datetime,
    rejection_reason_id: int | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage(stage),
                moved_at=moved_at,
                rejection_reason_id=rejection_reason_id,
            )
        )
        await db.commit()


async def _load(world: dict, *, job_id_key: str = "target_job_id") -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.hiring_manager_verdicts import load_manager_rejections
    from sqlalchemy import select

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == world[job_id_key]))
        return await load_manager_rejections(
            db, job=job, candidate_ids=[world["candidate_id"]]
        )


async def _reject_after_interview(world: dict, *, reason_key: str) -> None:
    """The canonical story: manager met the candidate, then turned them down."""
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="client_interview",
        moved_at=NOW - timedelta(days=30),
    )
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="rejected",
        moved_at=NOW - timedelta(days=29),
        rejection_reason_id=world[reason_key],
    )


async def test_interview_then_disqualifying_rejection_is_a_verdict():
    world = await _seed_world()
    await _reject_after_interview(world, reason_key="disqualifying_reason_id")

    verdicts = await _load(world)

    assert world["candidate_id"] in verdicts
    verdict = verdicts[world["candidate_id"]]
    assert verdict.source_job_id == world["source_job_id"]
    assert verdict.hiring_manager_contact_id == world["manager_id"]
    # The recruiter has to be told who and why, not just "blocked".
    assert verdict.hiring_manager_name == world["manager_name"]
    assert "slaby" in verdict.rejection_reason_name
    assert world["manager_name"] in verdict.as_polish_detail()


async def test_same_job_never_vetoes_itself():
    """The bug that would freeze every re-opened pipeline.

    ``CandidateStage`` is append-only, so a candidate rejected on job J carries
    that row on J forever. If the veto counted it, every later forward move on J
    would 409 and the recruiter would have no way out.
    """
    world = await _seed_world()
    await _reject_after_interview(world, reason_key="disqualifying_reason_id")

    # Asking about the very job the rejection happened on.
    verdicts = await _load(world, job_id_key="source_job_id")

    assert verdicts == {}


async def test_different_hiring_manager_does_not_veto():
    world = await _seed_world(two_managers=True)
    await _reject_after_interview(world, reason_key="disqualifying_reason_id")

    verdicts = await _load(world)

    assert verdicts == {}


async def test_situational_reason_does_not_veto():
    """"Za drogi" says nothing about the person — it must never block."""
    world = await _seed_world()
    await _reject_after_interview(world, reason_key="situational_reason_id")

    verdicts = await _load(world)

    assert verdicts == {}


async def test_rejection_without_a_reason_does_not_veto():
    """Fail-open: `rejected` rows may carry no reason at all."""
    world = await _seed_world()
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="client_interview",
        moved_at=NOW - timedelta(days=30),
    )
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="rejected",
        moved_at=NOW - timedelta(days=29),
        rejection_reason_id=None,
    )

    verdicts = await _load(world)

    assert verdicts == {}


async def test_cv_rejection_without_an_interview_does_not_veto():
    """Seeing a CV is not meeting the person."""
    world = await _seed_world()
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="cv_sent",
        moved_at=NOW - timedelta(days=30),
    )
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="rejected",
        moved_at=NOW - timedelta(days=29),
        rejection_reason_id=world["disqualifying_reason_id"],
    )

    verdicts = await _load(world)

    assert verdicts == {}


async def test_interview_after_the_rejection_does_not_veto():
    """`rejected → re-opened → client_interview` is the opposite story.

    An aggregate ("was there ever an interview, was there ever a rejection")
    would call this a verdict. The ordering check is what keeps it honest.
    """
    world = await _seed_world()
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="rejected",
        moved_at=NOW - timedelta(days=30),
        rejection_reason_id=world["disqualifying_reason_id"],
    )
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="client_interview",
        moved_at=NOW - timedelta(days=2),
    )

    verdicts = await _load(world)

    assert verdicts == {}


async def test_job_without_a_hiring_manager_returns_empty():
    """The common case today — and it must cost nothing."""
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.hiring_manager_verdicts import load_manager_rejections
    from sqlalchemy import select

    world = await _seed_world()
    await _reject_after_interview(world, reason_key="disqualifying_reason_id")

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == world["target_job_id"]))
        job.hiring_manager_contact_id = None
        verdicts = await load_manager_rejections(
            db, job=job, candidate_ids=[world["candidate_id"]]
        )

    assert verdicts == {}


async def test_acceptance_counts_as_having_met():
    """The manager met them and could still say no — that is a verdict."""
    world = await _seed_world()
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="acceptance",
        moved_at=NOW - timedelta(days=20),
    )
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="rejected",
        moved_at=NOW - timedelta(days=19),
        rejection_reason_id=world["disqualifying_reason_id"],
    )

    verdicts = await _load(world)

    assert world["candidate_id"] in verdicts


async def test_rejection_after_hired_is_not_a_verdict():
    """A contract that ended is not a manager turning someone down.

    Production has 133 such pairs against one genuine post-interview rejection,
    so counting `hired → rejected` would make the veto fire almost exclusively
    on people the client actually hired.
    """
    world = await _seed_world()
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="hired",
        moved_at=NOW - timedelta(days=400),
    )
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["source_job_id"],
        stage="rejected",
        moved_at=NOW - timedelta(days=30),
        rejection_reason_id=world["disqualifying_reason_id"],
    )

    verdicts = await _load(world)

    assert verdicts == {}


async def test_veto_for_candidate_stage_resolves_through_the_row():
    """Powers the outbound gates (CV share link, Champion card)."""
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.services.hiring_manager_verdicts import veto_for_candidate_stage
    from sqlalchemy import select

    world = await _seed_world()
    await _reject_after_interview(world, reason_key="disqualifying_reason_id")
    await _seed_stage(
        candidate_id=world["candidate_id"],
        job_id=world["target_job_id"],
        stage="cv_sent",
        moved_at=NOW - timedelta(days=1),
    )

    async with AsyncSessionLocal() as db:
        stage_id = await db.scalar(
            select(CandidateStage.id).where(
                CandidateStage.candidate_id == world["candidate_id"],
                CandidateStage.job_id == world["target_job_id"],
                CandidateStage.stage == PipelineStage.cv_sent,
            )
        )
        verdict = await veto_for_candidate_stage(db, candidate_stage_id=stage_id)

    assert verdict is not None
    assert verdict.source_job_id == world["source_job_id"]


async def test_veto_for_missing_stage_is_none():
    from app.core.database import AsyncSessionLocal
    from app.services.hiring_manager_verdicts import veto_for_candidate_stage

    async with AsyncSessionLocal() as db:
        assert await veto_for_candidate_stage(db, candidate_stage_id=-1) is None


async def test_met_stages_exclude_cv_sent():
    """Guards the stage set itself, so a future reorder can't widen it."""
    from app.models.recruitment_pipeline import PipelineStage
    from app.services.hiring_manager_verdicts import MANAGER_MET_STAGES

    assert PipelineStage.client_interview in MANAGER_MET_STAGES
    assert PipelineStage.acceptance in MANAGER_MET_STAGES
    assert PipelineStage.negotiation in MANAGER_MET_STAGES
    # Seeing a CV is not meeting the person...
    assert PipelineStage.cv_sent not in MANAGER_MET_STAGES
    assert PipelineStage.screening not in MANAGER_MET_STAGES
    # ...and a rejection past acceptance is an engagement ending, not a verdict.
    assert PipelineStage.hired not in MANAGER_MET_STAGES
    assert PipelineStage.onboarding not in MANAGER_MET_STAGES


async def test_only_client_facing_moves_are_gated():
    """`hired` must never be blocked — the manager just accepted them."""
    from app.models.recruitment_pipeline import PipelineStage
    from app.services.hiring_manager_verdicts import puts_candidate_before_client

    assert puts_candidate_before_client(PipelineStage.cv_sent)
    assert puts_candidate_before_client(PipelineStage.client_interview)
    assert not puts_candidate_before_client(PipelineStage.hired)
    assert not puts_candidate_before_client(PipelineStage.screening)
    assert not puts_candidate_before_client(None)
