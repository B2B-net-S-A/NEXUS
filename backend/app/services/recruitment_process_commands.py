"""Single transactional write layer for recruitment pipeline state.

The legacy ``candidate_stages`` table remains the event/audit representation,
but every native writer must append through this module.  The command updates
``RecruitmentProcess`` in the same transaction and freezes Priority Lock / KPI
eligibility at process-open time.

Callers retain their existing validation, activity, CV-snapshot, notification
and commit behaviour.  Commands flush, but never commit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import Select, and_, delete, func, select, tuple_, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.recruitment_priority import (
    PriorityExceptionStatus,
    PriorityChannel,
    PriorityMemberStatus,
    PriorityMode,
    PriorityOriginKind,
    RecruitmentPriorityException,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess
from app.models.user import User, UserRole
from app.models.workflow_revision import (
    StageRevision,
    WorkflowDefinition,
    WorkflowRevision,
    WorkflowRevisionStatus,
)
from app.services.priority_work_policy import (
    PriorityWorkDecision,
    PriorityWorkLocked,
    PriorityWorkReason,
    assert_priority_work_access,
    current_priority_assignment,
    effective_priority_mode,
    invalidate_milestone_counts,
)
from app.services.semantic_states import LEGACY_TO_SEMANTIC


_TERMINAL_STAGES = {
    PipelineStage.hired,
    PipelineStage.rejected,
    PipelineStage.withdrawn,
}

# Stopnie, które `assignment_milestone_counts` faktycznie zlicza — tylko one
# mogą unieważnić memo progresu otwarte przez `milestone_counts_scope`.
_MILESTONE_COUNT_STAGES = {PipelineStage.verified, PipelineStage.cv_sent}


def canonical_candidate_lock_order(candidate_ids: Iterable[int]) -> list[int]:
    """Faza 1 globalnej kolejności blokad: kandydaci rosnąco, bez duplikatów.

    Globalna kolejność brzmi: **wszyscy kandydaci operacji (rosnąco po id) →
    dopiero potem oferty (rosnąco po id) → reszta**. Wsadowy
    `sync_external_observed_processes` trzymał się jej od początku, ale
    wywołujący w pętli (bulk-move, bulk-proposals) przeplatali
    kandydat→oferta→kandydat, więc czekali na kolejnego kandydata trzymając już
    blokadę oferty — klasyczne ABBA z wsadem Traffita. Każdy wywołujący, który
    dotyka więcej niż jednej pary, musi wziąć komplet blokad kandydatów przez tę
    funkcję ZANIM `transition_process` zablokuje pierwszą ofertę.
    """

    return sorted(dict.fromkeys(candidate_ids))


def lock_candidates_stmt(candidate_ids: Iterable[int]) -> Select:
    """``SELECT id ... FOR UPDATE`` w kanonicznej kolejności blokad."""

    return (
        select(Candidate.id)
        .where(Candidate.id.in_(canonical_candidate_lock_order(candidate_ids)))
        .order_by(Candidate.id)
        .with_for_update()
    )


@dataclass(frozen=True)
class _StageSemantics:
    workflow_revision_id: Optional[int]
    stage_revision_id: Optional[int]
    semantic_key: str
    is_terminal: bool


async def _resolve_stage_semantics(
    db: AsyncSession,
    stages: list[CandidateStage],
) -> dict[int, _StageSemantics]:
    """Resolve the same published workflow bridge used by the backfill.

    Custom stage definitions must never silently inherit the mirrored legacy
    enum (usually ``new``). A published ``StageRevision`` is authoritative;
    an unmapped custom definition is quarantined as ``unmapped``.
    """

    stage_def_ids = {
        stage_def_id
        for stage in stages
        if (stage_def_id := getattr(stage, "stage_def_id", None)) is not None
    }
    revision_by_stage_def: dict[int, tuple[int, str, int, bool]] = {}
    definition_by_id: dict[int, tuple[Optional[str], bool, Optional[int]]] = {}
    if stage_def_ids:
        revision_rows = (
            await db.execute(
                select(
                    StageRevision.source_stage_def_id,
                    StageRevision.id,
                    StageRevision.semantic_key,
                    StageRevision.workflow_revision_id,
                    StageRevision.is_terminal,
                )
                .join(
                    WorkflowRevision,
                    WorkflowRevision.id == StageRevision.workflow_revision_id,
                )
                .where(
                    StageRevision.source_stage_def_id.in_(stage_def_ids),
                    WorkflowRevision.status == WorkflowRevisionStatus.published,
                )
                .order_by(StageRevision.id.desc())
            )
        ).all()
        for (
            stage_def_id,
            stage_revision_id,
            semantic,
            workflow_id,
            terminal,
        ) in revision_rows:
            revision_by_stage_def.setdefault(
                stage_def_id,
                (stage_revision_id, semantic, workflow_id, terminal),
            )

        definition_rows = (
            await db.execute(
                select(
                    PipelineStageDef.id,
                    PipelineStageDef.legacy_enum_value,
                    PipelineStageDef.is_terminal,
                    WorkflowRevision.id,
                )
                .outerjoin(
                    WorkflowDefinition,
                    WorkflowDefinition.template_id == PipelineStageDef.template_id,
                )
                .outerjoin(
                    WorkflowRevision,
                    and_(
                        WorkflowRevision.workflow_id == WorkflowDefinition.id,
                        WorkflowRevision.status == WorkflowRevisionStatus.published,
                    ),
                )
                .where(PipelineStageDef.id.in_(stage_def_ids))
            )
        ).all()
        definition_by_id = {
            stage_def_id: (legacy_value, terminal, workflow_revision_id)
            for stage_def_id, legacy_value, terminal, workflow_revision_id in (
                definition_rows
            )
        }

    resolved: dict[int, _StageSemantics] = {}
    for stage in stages:
        stage_def_id = getattr(stage, "stage_def_id", None)
        mapped = revision_by_stage_def.get(stage_def_id)
        if mapped is not None:
            stage_revision_id, semantic, workflow_revision_id, terminal = mapped
            resolved[stage.id] = _StageSemantics(
                workflow_revision_id=workflow_revision_id,
                stage_revision_id=stage_revision_id,
                semantic_key=semantic,
                is_terminal=bool(terminal),
            )
            continue
        definition = definition_by_id.get(stage_def_id)
        if definition is not None:
            legacy_value, terminal, workflow_revision_id = definition
            resolved[stage.id] = _StageSemantics(
                workflow_revision_id=workflow_revision_id,
                stage_revision_id=None,
                semantic_key=LEGACY_TO_SEMANTIC.get(
                    legacy_value or "",
                    "unmapped",
                ),
                is_terminal=bool(terminal),
            )
            continue
        resolved[stage.id] = _StageSemantics(
            workflow_revision_id=None,
            stage_revision_id=None,
            semantic_key=LEGACY_TO_SEMANTIC.get(stage.stage.value, "unmapped"),
            is_terminal=stage.stage in _TERMINAL_STAGES,
        )
    return resolved


def _origin_for_decision(
    requested: PriorityOriginKind, decision: PriorityWorkDecision
) -> PriorityOriginKind:
    if decision.reason is PriorityWorkReason.approved_exception:
        return PriorityOriginKind.approved_exception
    if decision.violation:
        return PriorityOriginKind.shadow_violation
    return requested


async def _latest_process(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    lock: bool = True,
) -> Optional[RecruitmentProcess]:
    stmt = (
        select(RecruitmentProcess)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
        )
        .order_by(
            RecruitmentProcess.attempt_no.desc(),
            RecruitmentProcess.id.desc(),
        )
        .limit(1)
    )
    if lock:
        stmt = stmt.with_for_update()
    return await db.scalar(stmt)


async def _latest_stage(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> Optional[CandidateStage]:
    return await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )


async def _lock_latest_stage(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> CandidateStage:
    locked_candidate = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if locked_candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    stage = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
        .with_for_update()
    )
    if stage is None:
        raise HTTPException(
            status_code=404,
            detail="Ten kandydat nie bierze udziału w tej rekrutacji.",
        )
    return stage


async def update_latest_client_rate(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    rate_value: Any,
    rate_unit: Optional[str],
    rate_currency: Optional[str],
) -> tuple[CandidateStage, tuple[Any, Optional[str], Optional[str]]]:
    """Update finance metadata through the canonical CandidateStage writer."""

    stage = await _lock_latest_stage(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
    )
    previous = (
        stage.client_rate_value,
        stage.client_rate_unit,
        stage.client_rate_currency,
    )
    if rate_value is None:
        stage.client_rate_value = None
        stage.client_rate_unit = None
        stage.client_rate_currency = None
    else:
        stage.client_rate_value = rate_value
        stage.client_rate_unit = rate_unit
        stage.client_rate_currency = rate_currency
    await db.flush()
    return stage, previous


async def update_latest_expected_rate(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    rate_value: Any,
    rate_unit: Optional[str],
    rate_currency: Optional[str],
) -> tuple[CandidateStage, Optional[Job], bool]:
    """Update expected rate and re-evaluate the verified budget gate."""

    stage = await _lock_latest_stage(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
    )
    if rate_value is None:
        stage.expected_rate_value = None
        stage.expected_rate_unit = None
        stage.expected_rate_currency = None
    else:
        stage.expected_rate_value = rate_value
        stage.expected_rate_unit = rate_unit
        stage.expected_rate_currency = rate_currency

    job: Optional[Job] = None
    became_pending = False
    if stage.stage == PipelineStage.verified:
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if job is not None and job.salary_max is not None and rate_value is not None:
            from app.services.rate_normalization import normalize_rate_to_monthly

            stage.budget_max_at_move = int(job.salary_max)
            normalized, _note = normalize_rate_to_monthly(
                Decimal(rate_value),
                rate_unit,
                rate_currency,
            )
            if normalized is None or normalized > Decimal(job.salary_max):
                became_pending = stage.verification_status != VerificationStatus.pending
                stage.verification_status = VerificationStatus.pending
                stage.approved_by = None
                stage.approved_at = None
            else:
                was_pending = stage.verification_status == VerificationStatus.pending
                stage.verification_status = VerificationStatus.active
                if was_pending:
                    # Automatic acceptance happened at this rate correction,
                    # not retroactively at the original over-budget move.
                    stage.approved_by = None
                    stage.approved_at = datetime.now(timezone.utc)
                if stage.moved_by is not None:
                    await record_accepted_verification(
                        db,
                        stage=stage,
                        verifier_user_id=stage.moved_by,
                    )
    await db.flush()
    return stage, job, became_pending


async def _create_process(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    job: Job,
    previous_process: Optional[RecruitmentProcess],
    decision: PriorityWorkDecision,
    actor_user_id: Optional[int],
    origin_kind: PriorityOriginKind,
    source_authority: str,
    semantics: _StageSemantics,
) -> RecruitmentProcess:
    opened_at = stage.moved_at or datetime.now(timezone.utc)
    terminal = semantics.is_terminal
    process = RecruitmentProcess(
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        client_id=job.client_id,
        attempt_no=(previous_process.attempt_no + 1 if previous_process else 1),
        previous_process_id=previous_process.id if previous_process else None,
        workflow_revision_id=semantics.workflow_revision_id,
        current_stage_revision_id=semantics.stage_revision_id,
        current_semantic_state=semantics.semantic_key,
        legacy_current_candidate_stage_id=stage.id,
        state_version=1,
        status=ProcessStatus.closed if terminal else ProcessStatus.open,
        owner_user_id=decision.assignment_owner_user_id,
        source_authority=source_authority,
        opened_at=opened_at,
        closed_at=opened_at if terminal else None,
        origin_assignment_id=decision.assignment_id,
        eligibility_assignment_id=(
            decision.assignment_id if decision.kpi_eligible is not False else None
        ),
        opened_by_user_id=actor_user_id,
        origin_kind=_origin_for_decision(origin_kind, decision),
        priority_compliant_at_open=decision.priority_compliant,
        kpi_eligible=decision.kpi_eligible,
        kpi_eligibility_reason=decision.reason.value,
        kpi_eligibility_decided_at=(
            opened_at if decision.kpi_eligible is not None else None
        ),
    )
    db.add(process)
    await db.flush()
    if decision.exception_id is not None:
        exception = await db.scalar(
            select(RecruitmentPriorityException)
            .where(
                RecruitmentPriorityException.id == decision.exception_id,
                RecruitmentPriorityException.status == PriorityExceptionStatus.consumed,
            )
            .with_for_update()
        )
        if exception is not None:
            exception.consumed_process_id = process.id
    return process


async def _sync_process_to_stage(
    db: AsyncSession,
    *,
    process: RecruitmentProcess,
    stage: CandidateStage,
    source_authority: str,
    semantics: _StageSemantics,
) -> None:
    if process.status in {ProcessStatus.closed, ProcessStatus.voided}:
        raise RuntimeError("A terminal recruitment attempt cannot be reopened in place")
    moved_at = stage.moved_at or datetime.now(timezone.utc)
    terminal = semantics.is_terminal
    process.legacy_current_candidate_stage_id = stage.id
    process.workflow_revision_id = (
        semantics.workflow_revision_id or process.workflow_revision_id
    )
    process.current_stage_revision_id = semantics.stage_revision_id
    process.current_semantic_state = semantics.semantic_key
    process.status = ProcessStatus.closed if terminal else ProcessStatus.open
    process.closed_at = moved_at if terminal else None
    process.source_authority = source_authority
    process.state_version = (process.state_version or 0) + 1
    if process.origin_kind is None:
        process.origin_kind = PriorityOriginKind.legacy
    if process.opened_at is None:
        process.opened_at = moved_at


def _external_stage_starts_new_attempt(
    process: RecruitmentProcess,
    stage: CandidateStage,
) -> bool:
    """Return whether a Traffit milestone is provably newer than a terminal attempt.

    A terminal attempt is immutable.  In particular, re-importing historical
    Traffit rows after a corrective delete must not resurrect a voided attempt.
    Only a distinct external milestone whose source timestamp is later than the
    terminal cutoff may enter through the external-observed admission path and
    become a new attempt.
    """

    if process.status not in {ProcessStatus.closed, ProcessStatus.voided}:
        return False
    if stage.external_source != "traffit":
        return False
    if process.legacy_current_candidate_stage_id == stage.id:
        return False
    terminal_at = (
        process.voided_at
        if process.status == ProcessStatus.voided
        else process.closed_at
    )
    return bool(
        terminal_at is not None
        and stage.moved_at is not None
        and stage.moved_at > terminal_at
    )


def _process_already_observes_stage(
    process: RecruitmentProcess,
    stage: CandidateStage,
    semantics: _StageSemantics,
) -> bool:
    """Avoid mutating state/version when Traffit replays the current milestone."""

    expected_status = (
        ProcessStatus.closed if semantics.is_terminal else ProcessStatus.open
    )
    return bool(
        process.legacy_current_candidate_stage_id == stage.id
        and process.current_semantic_state == semantics.semantic_key
        and process.current_stage_revision_id == semantics.stage_revision_id
        and process.status == expected_status
    )


async def _create_observed_attempt(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    job: Job,
    previous_process: Optional[RecruitmentProcess],
    semantics: _StageSemantics,
) -> RecruitmentProcess:
    """Create one legacy-gap or external-observed attempt with frozen eligibility."""

    is_external_stage = stage.external_source == "traffit"
    decision = PriorityWorkDecision(
        allowed=True,
        mode=PriorityMode.off,
        reason=(
            PriorityWorkReason.external_observed
            if is_external_stage
            else PriorityWorkReason.continuation
        ),
        is_continuation=not is_external_stage,
        kpi_eligible=False if is_external_stage else None,
        priority_compliant=None,
    )
    return await _create_process(
        db,
        stage=stage,
        job=job,
        previous_process=previous_process,
        decision=decision,
        actor_user_id=stage.moved_by,
        origin_kind=(
            PriorityOriginKind.external_observed
            if is_external_stage
            else PriorityOriginKind.legacy
        ),
        source_authority=(
            "external_observed" if is_external_stage else "legacy_gap_repair"
        ),
        semantics=semantics,
    )


async def transition_process(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    stage: PipelineStage,
    actor_user_id: Optional[int],
    stage_def_id: Optional[int] = None,
    origin_kind: PriorityOriginKind = PriorityOriginKind.assigned,
    source_authority: str = "live_command",
    require_existing: bool = False,
    frozen_origin_assignment_id: Optional[int] = None,
    frozen_priority_compliant: Optional[bool] = None,
    work_channel: Optional[PriorityChannel] = None,
    moved_at: Optional[datetime] = None,
    _strict_open: bool = False,
    **candidate_stage_values: Any,
) -> CandidateStage:
    """Append a stage event and synchronize its canonical process.

    ``require_existing`` is used by signing/contract automation: such hooks may
    advance carry-over, but may never manufacture a fresh recruitment.
    """

    # One lock order for every entry point.  Besides serialising first-open
    # attempts, it matches the existing /pipeline/move and signing lock order.
    locked_candidate = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if locked_candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    previous_stage = await _latest_stage(db, candidate_id=candidate_id, job_id=job_id)
    previous_process = await _latest_process(
        db, candidate_id=candidate_id, job_id=job_id
    )
    if previous_stage is not None and previous_process is None:
        # Repair the missing aggregate before deciding whether this is carry-
        # over. A terminal legacy row becomes a closed attempt, so reopening
        # must pass the current assignment policy and creates attempt 2.
        previous_semantics = (await _resolve_stage_semantics(db, [previous_stage]))[
            previous_stage.id
        ]
        previous_process = await _create_process(
            db,
            stage=previous_stage,
            job=job,
            previous_process=None,
            decision=PriorityWorkDecision(
                allowed=True,
                mode=PriorityMode.off,
                reason=PriorityWorkReason.continuation,
                is_continuation=not previous_semantics.is_terminal,
                assignment_owner_user_id=previous_stage.moved_by,
                kpi_eligible=None,
                priority_compliant=None,
            ),
            actor_user_id=previous_stage.moved_by,
            origin_kind=PriorityOriginKind.legacy,
            source_authority="legacy_gap_repair",
            semantics=previous_semantics,
        )
    continuation_exists = (
        previous_process is not None and previous_process.status == ProcessStatus.open
    )
    if _strict_open and continuation_exists:
        # `open_process` is an idempotent ingress command. The candidate lock
        # serialises concurrent pre-checks; the loser reuses the existing
        # stage instead of appending a duplicate `new` event.
        if previous_stage is None:  # pragma: no cover - inconsistent legacy data
            raise RuntimeError("Open process exists without a CandidateStage")
        return previous_stage
    decision = await assert_priority_work_access(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        actor_user_id=actor_user_id,
        origin_kind=origin_kind,
        action="transition_process" if continuation_exists else "open_process",
        continuation_exists=continuation_exists,
        require_existing=require_existing,
        frozen_origin_assignment_id=frozen_origin_assignment_id,
        frozen_priority_compliant=frozen_priority_compliant,
        work_channel=work_channel,
        # `is_open` (0270), nie `status`: to pytanie brzmi „czy MY prowadzimy
        # tę rekrutację", a nie „czy żyje u klienta". Status jest lustrem
        # Traffita i po naprawie mapowania obejmuje ~305 rekrutacji, z których
        # zdecydowanej większości nikt nie przekazał do searchu.
        job_is_open=job.is_open,
    )

    values = dict(candidate_stage_values)
    # The command owns identity/timestamp fields; silently accepting duplicates
    # would make the frozen policy refer to a different pair than the row.
    for owned in (
        "candidate_id",
        "job_id",
        "stage",
        "stage_def_id",
        "moved_by",
        "moved_at",
    ):
        values.pop(owned, None)
    stage_row = CandidateStage(
        candidate_id=candidate_id,
        job_id=job_id,
        stage=stage,
        stage_def_id=stage_def_id,
        moved_at=moved_at or datetime.now(timezone.utc),
        moved_by=actor_user_id,
        **values,
    )
    db.add(stage_row)
    await db.flush()
    if stage_row.stage in _MILESTONE_COUNT_STAGES:
        invalidate_milestone_counts()
    semantics = (await _resolve_stage_semantics(db, [stage_row]))[stage_row.id]

    process = previous_process
    if process is None or (
        process.status in {ProcessStatus.closed, ProcessStatus.voided}
        and not continuation_exists
    ):
        process = await _create_process(
            db,
            stage=stage_row,
            job=job,
            previous_process=previous_process,
            decision=decision,
            actor_user_id=actor_user_id,
            origin_kind=origin_kind,
            source_authority=source_authority,
            semantics=semantics,
        )
    else:
        await _sync_process_to_stage(
            db,
            process=process,
            stage=stage_row,
            source_authority=source_authority,
            semantics=semantics,
        )

    if (
        stage_row.stage == PipelineStage.verified
        and stage_row.verification_status == VerificationStatus.active
        and actor_user_id is not None
    ):
        await record_accepted_verification(
            db, stage=stage_row, verifier_user_id=actor_user_id, process=process
        )
    await db.flush()
    return stage_row


async def open_process(
    db: AsyncSession,
    **kwargs: Any,
) -> CandidateStage:
    """Named entry command for assign/import endpoints."""

    return await transition_process(db, _strict_open=True, **kwargs)


async def record_accepted_verification(
    db: AsyncSession,
    *,
    stage: CandidateStage,
    verifier_user_id: int,
    process: Optional[RecruitmentProcess] = None,
) -> RecruitmentProcess:
    """Freeze first-verifier credit and eligibility.

    The verifier is ``stage.moved_by`` even when an approver later accepts a
    pending rate.  Explicit one-shot exceptions never become KPI eligible.
    """

    if process is None:
        process = await _latest_process(
            db,
            candidate_id=stage.candidate_id,
            job_id=stage.job_id,
        )
    if process is None:
        # Legacy pending verification created before command-layer rollout.
        await sync_external_observed_process(
            db, candidate_id=stage.candidate_id, job_id=stage.job_id
        )
        process = await _latest_process(
            db,
            candidate_id=stage.candidate_id,
            job_id=stage.job_id,
        )
    if process is None:  # pragma: no cover - only corrupt FK-less data
        raise RuntimeError("Cannot attach verification to a missing process")

    if process.credit_user_id is not None:
        # First accepted verifier is immutable.  A later duplicate `verified`
        # event must not steal credit or re-evaluate a frozen plan decision.
        return process

    process.credit_user_id = verifier_user_id
    # Carry-over belongs to the first accepted verifier unless HoR already
    # made an explicit handoff.  A delayed pending-verification approval must
    # never undo that ownership decision.
    if process.ownership_confirmed_at is None:
        process.owner_user_id = verifier_user_id

    if process.origin_kind == PriorityOriginKind.approved_exception:
        if process.kpi_eligible is None:
            process.kpi_eligible = False
            process.kpi_eligibility_decided_at = datetime.now(timezone.utc)
        process.kpi_eligibility_reason = PriorityWorkReason.approved_exception.value
        return process

    # Human-assigned opens freeze eligibility at process-open time.  This is
    # the key carry-over invariant: accepting a pending verification after a
    # plan supersede cannot rewrite the old decision.
    if process.kpi_eligible is not None:
        return process

    # Reconciled historical processes retain NULL eligibility so historical
    # KPI and frozen podiums keep their legacy attribution semantics.
    if process.origin_kind == PriorityOriginKind.legacy:
        return process

    # Public/invite inbound is admitted before a verifier exists.  If it was
    # routed through a compliant assignment, preserve that origin assignment
    # even when the plan has since been superseded.
    if (
        process.priority_compliant_at_open is True
        and process.origin_assignment_id is not None
    ):
        process.eligibility_assignment_id = process.origin_assignment_id
        process.kpi_eligible = True
        process.kpi_eligibility_reason = PriorityWorkReason.assigned.value
        process.kpi_eligibility_decided_at = datetime.now(timezone.utc)
        return process

    mode = await effective_priority_mode(db, verifier_user_id)
    assignment, member, _plan = await current_priority_assignment(
        db, user_id=verifier_user_id, job_id=stage.job_id
    )
    assignment_is_active = bool(
        assignment and member and member.status == PriorityMemberStatus.active
    )
    if assignment_is_active:
        process.eligibility_assignment_id = assignment.id
        process.kpi_eligible = True
        process.kpi_eligibility_reason = PriorityWorkReason.assigned.value
    elif mode in (PriorityMode.off, PriorityMode.shadow):
        # `off` is strict backward compatibility; shadow only observes.
        process.kpi_eligible = True
        process.kpi_eligibility_reason = (
            PriorityWorkReason.mode_off.value
            if mode is PriorityMode.off
            else PriorityWorkReason.shadow_no_assignment.value
        )
    else:
        process.kpi_eligible = False
        process.kpi_eligibility_reason = PriorityWorkReason.job_not_assigned.value
    process.kpi_eligibility_decided_at = datetime.now(timezone.utc)
    return process


async def _lock_current_pending_verification(
    db: AsyncSession,
    *,
    candidate_stage_id: int,
) -> CandidateStage:
    locator = (
        await db.execute(
            select(CandidateStage.candidate_id, CandidateStage.job_id).where(
                CandidateStage.id == candidate_stage_id
            )
        )
    ).first()
    if locator is None:
        raise HTTPException(status_code=404, detail="CandidateStage not found")
    locked_candidate = await db.scalar(
        select(Candidate.id)
        .where(Candidate.id == locator.candidate_id)
        .with_for_update()
    )
    if locked_candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    stage = await db.scalar(
        select(CandidateStage)
        .where(CandidateStage.id == candidate_stage_id)
        .with_for_update()
    )
    if stage is None:
        raise HTTPException(status_code=404, detail="CandidateStage not found")
    if stage.stage != PipelineStage.verified:
        raise HTTPException(
            status_code=422,
            detail="Decyzja dotyczy wyłącznie stage'a 'verified'",
        )
    if stage.verification_status != VerificationStatus.pending:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Status nie jest 'pending' (obecny: {stage.verification_status.value})"
            ),
        )
    latest_id = await db.scalar(
        select(CandidateStage.id)
        .where(
            CandidateStage.candidate_id == stage.candidate_id,
            CandidateStage.job_id == stage.job_id,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    if latest_id != stage.id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ten rekord nie jest aktualnym stanem procesu — proces został "
                "już przesunięty dalej. Odśwież listę weryfikacji."
            ),
        )
    return stage


async def accept_pending_verification(
    db: AsyncSession,
    *,
    candidate_stage_id: int,
    approver_user_id: int,
) -> CandidateStage:
    """Atomically accept the current pending verification."""

    stage = await _lock_current_pending_verification(
        db,
        candidate_stage_id=candidate_stage_id,
    )
    stage.verification_status = VerificationStatus.active
    stage.approved_by = approver_user_id
    stage.approved_at = datetime.now(timezone.utc)
    invalidate_milestone_counts()
    if stage.moved_by is not None:
        await record_accepted_verification(
            db,
            stage=stage,
            verifier_user_id=stage.moved_by,
        )
    await db.flush()
    return stage


async def reject_pending_verification(
    db: AsyncSession,
    *,
    candidate_stage_id: int,
    approver_user_id: int,
    note: str,
) -> tuple[CandidateStage, CandidateStage]:
    """Atomically reject pending verification and append its revert event."""

    stage = await _lock_current_pending_verification(
        db,
        candidate_stage_id=candidate_stage_id,
    )
    now = datetime.now(timezone.utc)
    stage.verification_status = VerificationStatus.rejected
    stage.rejected_by = approver_user_id
    stage.rejected_at = now
    stage.rejection_note = note
    process = await _latest_process(
        db,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
    )
    if (
        process is not None
        and process.credit_user_id is not None
        and process.credit_user_id == stage.moved_by
    ):
        accepted_conditions = [
            CandidateStage.candidate_id == stage.candidate_id,
            CandidateStage.job_id == stage.job_id,
            CandidateStage.id != stage.id,
            CandidateStage.stage == PipelineStage.verified,
            CandidateStage.verification_status == VerificationStatus.active,
        ]
        if process.opened_at is not None:
            accepted_conditions.append(CandidateStage.moved_at >= process.opened_at)
        other_accepted = await db.scalar(
            select(CandidateStage.id).where(*accepted_conditions).limit(1)
        )
        if other_accepted is None:
            # A rate edit can return an already accepted verification to
            # pending. If that decision is then rejected, the rejected row may
            # not permanently reserve first-verifier credit.
            process.credit_user_id = None

    previous = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == stage.candidate_id,
            CandidateStage.job_id == stage.job_id,
            CandidateStage.id != stage.id,
            CandidateStage.moved_at < stage.moved_at,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    revert_stage = previous.stage if previous is not None else PipelineStage.new
    revert_stage_def_id = previous.stage_def_id if previous is not None else None
    rate_label = (
        f"{stage.expected_rate_value} "
        f"{(stage.expected_rate_currency or 'PLN')}/"
        f"{(stage.expected_rate_unit or 'monthly')}"
    )
    budget_label = (
        f"{stage.budget_max_at_move}" if stage.budget_max_at_move is not None else "?"
    )
    revert = await transition_process(
        db,
        candidate_id=stage.candidate_id,
        job_id=stage.job_id,
        stage=revert_stage,
        stage_def_id=revert_stage_def_id,
        moved_at=now,
        actor_user_id=approver_user_id,
        work_channel=PriorityChannel.database,
        notes=(
            f"Rejected verification: {note} (rate {rate_label} > budżet {budget_label})"
        ),
        verification_status=VerificationStatus.active,
    )
    await db.flush()
    return stage, revert


async def void_process(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    actor_user: User,
) -> Optional[RecruitmentProcess]:
    """Mark the canonical process void before the legacy corrective delete.

    Under enforcement this is a HoR correction only.  ``off`` and
    ``shadow`` retain the old endpoint behaviour while still leaving a durable
    canonical audit record.
    """

    locked_candidate = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if locked_candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    mode = await effective_priority_mode(db, actor_user.id)
    if mode is PriorityMode.enforce and not actor_user.has_role(
        UserRole.head_of_recruitment
    ):
        decision = PriorityWorkDecision(
            allowed=False,
            mode=mode,
            reason=PriorityWorkReason.void_requires_manager,
            is_continuation=True,
            kpi_eligible=None,
        )
        raise PriorityWorkLocked(
            decision,
            action="void_process",
            candidate_id=candidate_id,
            job_id=job_id,
        )

    process = await _latest_process(db, candidate_id=candidate_id, job_id=job_id)
    if process is None:
        await sync_external_observed_process(
            db, candidate_id=candidate_id, job_id=job_id
        )
        process = await _latest_process(db, candidate_id=candidate_id, job_id=job_id)
    if process is None:
        return None
    now = datetime.now(timezone.utc)
    process.status = ProcessStatus.voided
    process.voided_at = now
    process.closed_at = now
    process.state_version = (process.state_version or 0) + 1
    # Voided procesy wypadają z `classified_process`, więc progres assignmentu
    # policzony przed korektą jest już nieaktualny.
    invalidate_milestone_counts()
    await db.flush()
    return process


async def delete_voided_stage_history(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> int:
    """Physically remove legacy events only after the aggregate is voided.

    The candidate lock shares the canonical writer lock order, so no stage can
    be appended between the corrective archive snapshot and this delete.
    """

    locked_candidate = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if locked_candidate is None:
        raise HTTPException(status_code=404, detail="Candidate not found")
    process = await _latest_process(db, candidate_id=candidate_id, job_id=job_id)
    if process is None or process.status != ProcessStatus.voided:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Historia może zostać usunięta dopiero po oznaczeniu procesu voided.",
        )
    result = await db.execute(
        delete(CandidateStage).where(
            CandidateStage.candidate_id == candidate_id,
            CandidateStage.job_id == job_id,
        )
    )
    return int(result.rowcount or 0)


async def claim_stage_sla_alert(
    db: AsyncSession,
    *,
    candidate_stage_id: int,
) -> bool:
    """Atomically claim CandidateStage SLA metadata for the alert adapter."""

    result = await db.execute(
        update(CandidateStage)
        .where(
            CandidateStage.id == candidate_stage_id,
            CandidateStage.sla_alerted_at.is_(None),
        )
        .values(sla_alerted_at=func.now())
        .returning(CandidateStage.id)
    )
    return result.scalar_one_or_none() is not None


async def release_stage_sla_alert(
    db: AsyncSession,
    *,
    candidate_stage_id: int,
) -> None:
    """Release a failed external SLA notification claim."""

    await db.execute(
        update(CandidateStage)
        .where(CandidateStage.id == candidate_stage_id)
        .values(sla_alerted_at=None)
    )


async def handoff_process(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    new_owner_user_id: int,
    actor_user: User,
) -> RecruitmentProcess:
    """Change continuation owner without changing verifier/KPI credit."""

    if not actor_user.has_role(UserRole.head_of_recruitment):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Handoff może wykonać tylko Head of Recruitment.",
        )
    new_owner = await db.scalar(
        select(User).where(
            User.id == new_owner_user_id,
            User.is_active.is_(True),
        )
    )
    if new_owner is None or not new_owner.has_any_role(
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.tac,
    ):
        raise HTTPException(
            status_code=422,
            detail="Nowy właściciel nie jest aktywnym rekruterem, sourcerem ani TAC.",
        )
    process = await _latest_process(db, candidate_id=candidate_id, job_id=job_id)
    if process is None or process.status != ProcessStatus.open:
        raise HTTPException(status_code=404, detail="Aktywny proces nie istnieje.")
    process.owner_user_id = new_owner_user_id
    process.ownership_confirmed_at = datetime.now(timezone.utc)
    process.ownership_confirmed_by_user_id = actor_user.id
    process.state_version = (process.state_version or 0) + 1
    await db.flush()
    return process


async def _lock_external_pair(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> Optional[Job]:
    """Serialize external reconciliation with every native pair writer."""

    candidate_exists = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate_exists is None:
        return None
    return await db.scalar(select(Job).where(Job.id == job_id).with_for_update())


async def sync_external_observed_process(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> Optional[RecruitmentProcess]:
    """Synchronise the explicit Traffit/raw-SQL adapter with the aggregate."""

    job = await _lock_external_pair(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
    )
    if job is None:
        return None
    # Read stage/process only after waiting for the canonical Candidate -> Job
    # locks. A concurrent native or external writer may have completed while
    # this transaction waited, so an earlier snapshot cannot choose attempt N+1.
    stage = await _latest_stage(db, candidate_id=candidate_id, job_id=job_id)
    if stage is None:
        return None
    semantics = (await _resolve_stage_semantics(db, [stage]))[stage.id]
    process = await _latest_process(db, candidate_id=candidate_id, job_id=job_id)
    if process is None or _external_stage_starts_new_attempt(process, stage):
        process = await _create_observed_attempt(
            db,
            stage=stage,
            job=job,
            previous_process=process,
            semantics=semantics,
        )
    elif process.status == ProcessStatus.open and not _process_already_observes_stage(
        process, stage, semantics
    ):
        await _sync_process_to_stage(
            db,
            process=process,
            stage=stage,
            source_authority=(
                "external_observed"
                if stage.external_source == "traffit"
                else process.source_authority
            ),
            semantics=semantics,
        )
        # An external observation may advance a process that already existed
        # natively or was reconstructed as legacy.  It must not rewrite that
        # process's origin or eligibility.
    # A closed/voided attempt which does not have a provably newer Traffit
    # milestone is intentionally left unchanged. This makes repeated imports
    # idempotent and prevents historical rows from resurrecting voided work.
    await db.flush()
    return process


async def sync_external_observed_processes(
    db: AsyncSession,
    *,
    pairs: list[tuple[int, int]],
) -> int:
    """Batch variant for the high-volume Traffit raw-SQL adapter.

    It avoids an N+1 query per imported history event.  Caller controls batch
    size and commit boundaries.
    """

    pair_keys = list(dict.fromkeys(pairs))
    if not pair_keys:
        return 0

    # Lock all resources in the same Candidate -> Job order used by native
    # commands (patrz `canonical_candidate_lock_order`). Sorted ids also give
    # concurrent Traffit batches one deterministic order. Everything below is
    # intentionally read after the locks so it sees a process committed while
    # this batch was waiting instead of racing the same attempt number.
    await db.execute(
        lock_candidates_stmt(candidate_id for candidate_id, _ in pair_keys)
    )
    job_ids = sorted({job_id for _, job_id in pair_keys})
    jobs = {
        job.id: job
        for job in (
            (
                await db.execute(
                    select(Job)
                    .where(Job.id.in_(job_ids))
                    .order_by(Job.id)
                    .with_for_update()
                )
            )
            .scalars()
            .all()
        )
    }
    latest_stages = (
        (
            await db.execute(
                select(CandidateStage)
                .where(
                    tuple_(CandidateStage.candidate_id, CandidateStage.job_id).in_(
                        pair_keys
                    )
                )
                .distinct(CandidateStage.candidate_id, CandidateStage.job_id)
                .order_by(
                    CandidateStage.candidate_id,
                    CandidateStage.job_id,
                    CandidateStage.moved_at.desc(),
                    CandidateStage.id.desc(),
                )
            )
        )
        .scalars()
        .all()
    )
    process_rows = (
        (
            await db.execute(
                select(RecruitmentProcess)
                .where(
                    tuple_(
                        RecruitmentProcess.candidate_id,
                        RecruitmentProcess.job_id,
                    ).in_(pair_keys)
                )
                .order_by(
                    RecruitmentProcess.candidate_id,
                    RecruitmentProcess.job_id,
                    RecruitmentProcess.attempt_no.desc(),
                    RecruitmentProcess.id.desc(),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    # PostgreSQL forbids ``FOR UPDATE`` on a ``DISTINCT ON`` query. Lock all
    # (normally one) attempts for the touched pairs, then retain the first row
    # from the descending attempt/id order in Python.
    process_by_pair: dict[tuple[int, int], RecruitmentProcess] = {}
    for process in process_rows:
        process_by_pair.setdefault((process.candidate_id, process.job_id), process)
    semantics_by_stage = await _resolve_stage_semantics(db, latest_stages)
    synced = 0
    for stage in latest_stages:
        key = (stage.candidate_id, stage.job_id)
        semantics = semantics_by_stage[stage.id]
        process = process_by_pair.get(key)
        if process is None or _external_stage_starts_new_attempt(process, stage):
            job = jobs.get(stage.job_id)
            if job is None:
                continue
            process = await _create_observed_attempt(
                db,
                stage=stage,
                job=job,
                previous_process=process,
                semantics=semantics,
            )
            process_by_pair[key] = process
        elif (
            process.status == ProcessStatus.open
            and not _process_already_observes_stage(process, stage, semantics)
        ):
            await _sync_process_to_stage(
                db,
                process=process,
                stage=stage,
                source_authority=(
                    "external_observed"
                    if stage.external_source == "traffit"
                    else process.source_authority
                ),
                semantics=semantics,
            )
            # Preserve an existing native/legacy origin and its frozen
            # eligibility.  Only a newly created Traffit-observed process is
            # explicitly ineligible.
        # Terminal attempts without a strictly newer external milestone are a
        # deliberate no-op. Replaying the same Traffit batch cannot reopen or
        # create another attempt.
        synced += 1
    await db.flush()
    return synced
