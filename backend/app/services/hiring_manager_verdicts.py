"""Which candidates has *this job's* hiring manager already rejected?

A manager on the client side who interviewed a candidate and turned them down
must not be handed the same person again on the next recruitment. They remember,
and being asked twice reads as us not paying attention.

The verdict is derived, never hand-entered. A candidate is vetoed for job *T*
when some **other** recruitment *S* has all of:

1. a ``rejected`` stage row whose ``RejectionReason.disqualifies_person`` is set
   — so "za wysokie oczekiwania finansowe" or "zatrudniony gdzie indziej" never
   veto anyone; they say nothing about the person;
2. an earlier row on the same pair at a stage where the manager actually *met*
   the candidate (``client_interview`` and beyond). ``cv_sent`` deliberately
   does not count: seeing a CV is not an interview;
3. the same ``Job.hiring_manager_contact_id`` as *T*, which must not be NULL.

``S <> T`` is not a detail — it is what keeps the feature from strangling itself.
``CandidateStage`` is append-only, so a candidate rejected on *T* keeps that row
on *T* forever; without the exclusion every later forward move of a re-opened
process would 409 and the pipeline would freeze.

Deliberately *not* sourced from ``InterviewFeedback``: it carries no
``rejection_reason_id``, so it cannot honour rule (1) — it would veto on
"too expensive" too. It is a fine source for enriching *what the manager said*
once a verdict exists, but not for deciding that one exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.models.contact import Contact
from app.models.job import Job
from app.models.pipeline_template import RejectionReason
from app.models.recruitment_pipeline import STAGE_ORDER, CandidateStage, PipelineStage

# Stages proving the manager met the candidate *and could still say no*.
#
# Bounded on both ends, and the upper bound is not cosmetic: production history
# has 133 pairs that reach `hired` and later carry a `rejected` row, against a
# single genuine `client_interview → rejected`. Those 133 are contracts that
# ended, not candidates a manager turned down — counting them would make the
# veto fire almost exclusively on people the client once *hired*.
#
# `onboarding` is excluded for the same reason: past acceptance, a later
# rejection is the engagement ending, not a verdict on the person.
_MET_START = STAGE_ORDER.index(PipelineStage.client_interview)
_MET_END = STAGE_ORDER.index(PipelineStage.negotiation)
MANAGER_MET_STAGES: frozenset[PipelineStage] = frozenset(
    STAGE_ORDER[_MET_START : _MET_END + 1]
)

# The only moves the veto blocks: the ones that put the candidate in front of
# the client again.
#
# `hired` is deliberately absent — it means the manager has just accepted the
# candidate, so blocking it would be absurd. Internal moves (screening,
# interview) are absent for a different reason: every pipeline that predates
# this feature would otherwise 409 on its next forward step, with no way for the
# recruiter to unstick it.
VETO_ENFORCED_STAGES: frozenset[PipelineStage] = frozenset(
    {PipelineStage.cv_sent, PipelineStage.client_interview}
)


def puts_candidate_before_client(stage: Optional[PipelineStage]) -> bool:
    """Should a move to ``stage`` be checked against the manager's veto?"""
    return stage in VETO_ENFORCED_STAGES


@dataclass(frozen=True)
class ManagerVerdict:
    """One manager's standing rejection of one candidate."""

    candidate_id: int
    hiring_manager_contact_id: int
    hiring_manager_name: Optional[str]
    source_job_id: int
    source_job_title: Optional[str]
    rejected_at: datetime
    rejection_reason_id: int
    rejection_reason_name: str
    rejection_note: Optional[str]

    def as_polish_detail(self) -> str:
        """One sentence for an HTTP 409 — who, when, why.

        Deliberately omits the other recruitment's title: the caller may have no
        access to that job, and the manager's own name is not a leak (they are
        the manager of the job being written to).
        """
        who = self.hiring_manager_name or "Hiring manager tej rekrutacji"
        when = self.rejected_at.strftime("%d.%m.%Y")
        return (
            f"{who} odrzucił(a) tego kandydata po rozmowie {when} "
            f"— powód: „{self.rejection_reason_name}”. "
            "To ten sam hiring manager co w tej rekrutacji."
        )


async def load_manager_rejections(
    db: AsyncSession,
    *,
    job: Job,
    candidate_ids: Sequence[int] | None,
) -> dict[int, ManagerVerdict]:
    """Return ``{candidate_id: most recent verdict}`` for ``job``'s manager.

    ``candidate_ids=None`` explicitly requests all verdicts for freshness checks.
    Issues **no query at all** when the job has no hiring manager or there are
    no candidates to check, so the feature costs nothing on jobs where the
    manager field was never filled in.
    """
    manager_id = job.hiring_manager_contact_id
    ids = None if candidate_ids is None else {int(cid) for cid in candidate_ids}
    if manager_id is None or ids == set():
        return {}

    rejected = aliased(CandidateStage)
    met = aliased(CandidateStage)

    manager_met_candidate = exists().where(
        met.candidate_id == rejected.candidate_id,
        met.job_id == rejected.job_id,
        met.stage.in_(tuple(MANAGER_MET_STAGES)),
        # The meeting has to precede the rejection. An aggregate ("was there
        # ever a client_interview row, was there ever a rejected row") would
        # also match `rejected → re-opened → client_interview`, which is the
        # opposite story.
        met.moved_at <= rejected.moved_at,
    )

    stmt = (
        select(
            rejected.candidate_id,
            rejected.job_id,
            rejected.moved_at,
            rejected.rejection_reason_id,
            rejected.rejection_note,
            RejectionReason.name,
            Job.title,
            Contact.name.label("manager_name"),
        )
        .select_from(rejected)
        .join(Job, Job.id == rejected.job_id)
        .join(RejectionReason, RejectionReason.id == rejected.rejection_reason_id)
        # Outer: a deleted contact nulls the link, and losing the name must not
        # lose the veto.
        .outerjoin(Contact, Contact.id == Job.hiring_manager_contact_id)
        .where(
            rejected.candidate_id.in_(ids) if ids is not None else True,
            rejected.stage == PipelineStage.rejected,
            # Never let a job veto its own candidates — see module docstring.
            rejected.job_id != job.id,
            Job.hiring_manager_contact_id == manager_id,
            RejectionReason.disqualifies_person.is_(True),
            manager_met_candidate,
        )
        # Newest first, so the first row seen per candidate is the one we keep.
        .order_by(rejected.candidate_id, rejected.moved_at.desc())
    )

    verdicts: dict[int, ManagerVerdict] = {}
    for row in (await db.execute(stmt)).all():
        if row.candidate_id in verdicts:
            continue
        verdicts[row.candidate_id] = ManagerVerdict(
            candidate_id=row.candidate_id,
            hiring_manager_contact_id=manager_id,
            hiring_manager_name=row.manager_name,
            source_job_id=row.job_id,
            source_job_title=row.title,
            rejected_at=row.moved_at,
            rejection_reason_id=row.rejection_reason_id,
            rejection_reason_name=row.name,
            rejection_note=row.rejection_note,
        )
    return verdicts


async def load_all_vetoes_for_candidate(
    db: AsyncSession, *, candidate_id: int
) -> list[ManagerVerdict]:
    """Every manager who has rejected this candidate after meeting them.

    Job-agnostic, newest first, one entry per manager (their latest verdict).
    The badge on a job-scoped view can only name one manager; a candidate turned
    down by four of them needs the list — and the reasons — without opening
    every past recruitment.
    """
    rejected = aliased(CandidateStage)
    met = aliased(CandidateStage)

    stmt = (
        select(
            rejected.job_id,
            rejected.moved_at,
            rejected.rejection_reason_id,
            rejected.rejection_note,
            RejectionReason.name,
            Job.title,
            Job.hiring_manager_contact_id,
            Contact.name.label("manager_name"),
        )
        .select_from(rejected)
        .join(Job, Job.id == rejected.job_id)
        .join(RejectionReason, RejectionReason.id == rejected.rejection_reason_id)
        .outerjoin(Contact, Contact.id == Job.hiring_manager_contact_id)
        .where(
            rejected.candidate_id == candidate_id,
            rejected.stage == PipelineStage.rejected,
            Job.hiring_manager_contact_id.is_not(None),
            RejectionReason.disqualifies_person.is_(True),
            exists().where(
                met.candidate_id == rejected.candidate_id,
                met.job_id == rejected.job_id,
                met.stage.in_(tuple(MANAGER_MET_STAGES)),
                met.moved_at <= rejected.moved_at,
            ),
        )
        .order_by(rejected.moved_at.desc())
    )

    out: list[ManagerVerdict] = []
    seen_managers: set[int] = set()
    for row in (await db.execute(stmt)).all():
        if row.hiring_manager_contact_id in seen_managers:
            continue
        seen_managers.add(row.hiring_manager_contact_id)
        out.append(
            ManagerVerdict(
                candidate_id=candidate_id,
                hiring_manager_contact_id=row.hiring_manager_contact_id,
                hiring_manager_name=row.manager_name,
                source_job_id=row.job_id,
                source_job_title=row.title,
                rejected_at=row.moved_at,
                rejection_reason_id=row.rejection_reason_id,
                rejection_reason_name=row.name,
                rejection_note=row.rejection_note,
            )
        )
    return out


async def veto_for_candidate_stage(
    db: AsyncSession, *, candidate_stage_id: int
) -> Optional[ManagerVerdict]:
    """Veto standing against the candidate on this pipeline row's own job.

    Used on the paths where a candidate goes *out* to the client. Blocking at
    assignment time only protects rows created after this feature shipped: every
    pipeline that already existed is past that gate, flipping
    ``disqualifies_person`` on turns historical rejections into verdicts
    retroactively, and ``Job.hiring_manager_contact_id`` can be edited to
    someone who vetoed the candidate long ago.
    """
    row = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id).where(
                CandidateStage.id == candidate_stage_id
            )
        )
    ).first()
    if row is None:
        return None

    job = await db.scalar(select(Job).where(Job.id == row.job_id))
    if job is None:
        return None

    verdicts = await load_manager_rejections(
        db, job=job, candidate_ids=[row.candidate_id]
    )
    return verdicts.get(row.candidate_id)
