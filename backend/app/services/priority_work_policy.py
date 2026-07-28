"""Priority Lock policy for opening candidate/job recruitment processes.

The policy is deliberately separate from the HTTP entry points.  Every writer
uses :mod:`app.services.recruitment_process_commands`, which asks this module
for one frozen decision before the first ``CandidateStage`` row is written.

Important invariants:

* an existing, non-voided candidate/job process is always continuation work;
* ``off`` preserves the legacy behaviour;
* ``shadow`` records a violation but does not reject the write;
* ``enforce`` requires a current published-plan assignment (or a consumed,
  one-shot exception);
* accepted blockers on a lagging higher rank release the lower-rank gate;
* exceptions are locked and consumed in the caller's transaction.
"""

from __future__ import annotations

import enum
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Iterator, Optional

from fastapi import HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.recruitment_priority import (
    PriorityBlockerStatus,
    PriorityChannel,
    PriorityExceptionStatus,
    PriorityMemberStatus,
    PriorityMode,
    PriorityOriginKind,
    PriorityPlanStatus,
    RecruitmentPriorityAssignment,
    RecruitmentPriorityBlocker,
    RecruitmentPriorityException,
    RecruitmentPriorityPlan,
    RecruitmentPriorityPlanMember,
    RecruitmentPriorityUserMode,
)
from app.models.recruitment_process import ProcessStatus, RecruitmentProcess


class PriorityWorkReason(str, enum.Enum):
    continuation = "CONTINUATION"
    mode_off = "MODE_OFF"
    assigned = "ACTIVE_ASSIGNMENT"
    shadow_no_assignment = "SHADOW_NO_ASSIGNMENT"
    shadow_channel_mismatch = "SHADOW_CHANNEL_MISMATCH"
    shadow_higher_rank_behind = "SHADOW_HIGHER_RANK_BEHIND"
    shadow_job_not_open = "SHADOW_JOB_NOT_OPEN"
    approved_exception = "APPROVED_EXCEPTION"
    external_inbound = "EXTERNAL_INBOUND"
    manager_inbound = "MANAGER_INBOUND"
    external_observed = "EXTERNAL_OBSERVED"
    job_not_assigned = "JOB_NOT_ASSIGNED"
    channel_not_assigned = "CHANNEL_NOT_ASSIGNED"
    job_not_open = "JOB_NOT_OPEN"
    member_paused = "PLAN_MEMBER_PAUSED"
    higher_rank_behind = "HIGHER_RANK_BEHIND"
    existing_process_required = "EXISTING_PROCESS_REQUIRED"
    void_requires_manager = "VOID_REQUIRES_MANAGER"


@dataclass(frozen=True)
class PriorityWorkDecision:
    allowed: bool
    mode: PriorityMode
    reason: PriorityWorkReason
    is_continuation: bool
    active_plan_id: Optional[int] = None
    assignment_id: Optional[int] = None
    assignment_owner_user_id: Optional[int] = None
    exception_id: Optional[int] = None
    kpi_eligible: Optional[bool] = None
    priority_compliant: Optional[bool] = None
    violation: bool = False


class PriorityWorkLocked(HTTPException):
    """Structured 409 shared by all user-facing pipeline writers."""

    def __init__(
        self,
        decision: PriorityWorkDecision,
        *,
        action: str,
        candidate_id: int,
        job_id: int,
    ) -> None:
        message_by_reason = {
            PriorityWorkReason.job_not_assigned: (
                "Nie możesz dodać nowej osoby do tego requestu, ponieważ nie "
                "jest on w Twoim aktywnym planie pracy."
            ),
            PriorityWorkReason.member_paused: (
                "Twój plan pracy jest wstrzymany. Nadal obsługuj rozpoczęte "
                "procesy, ale nie dodawaj nowych osób."
            ),
            PriorityWorkReason.channel_not_assigned: (
                "Ten request jest w Twoim planie, ale nie w kanale użytym "
                "przez tę operację. Użyj kanału wskazanego w assignmencie."
            ),
            PriorityWorkReason.job_not_open: (
                "Request nie jest opublikowany. Możesz dokończyć rozpoczęte "
                "procesy, ale nie możesz dodawać nowych osób."
            ),
            PriorityWorkReason.higher_rank_behind: (
                "Wyższy priorytet nie osiągnął jeszcze targetu i nie ma "
                "zaakceptowanego blockera."
            ),
            PriorityWorkReason.existing_process_required: (
                "Automatyczna zmiana może kontynuować tylko istniejący proces."
            ),
            PriorityWorkReason.void_requires_manager: (
                "Aktywnego procesu nie można usunąć, aby porzucić rozpoczętą "
                "pracę. Korektę może wykonać Head of Recruitment."
            ),
        }
        next_action_by_reason = {
            PriorityWorkReason.higher_rank_behind: "WORK_HIGHER_PRIORITY",
            PriorityWorkReason.existing_process_required: (
                "CONTACT_HEAD_OF_RECRUITMENT"
            ),
        }
        super().__init__(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "PRIORITY_WORK_LOCKED",
                "action": action,
                "candidate_id": candidate_id,
                "job_id": job_id,
                "active_plan_id": decision.active_plan_id,
                "reason": decision.reason.value,
                "next_action": next_action_by_reason.get(
                    decision.reason,
                    "CONTACT_HEAD_OF_RECRUITMENT",
                ),
                "message": message_by_reason.get(
                    decision.reason,
                    "Ta operacja jest zablokowana przez aktywny plan pracy.",
                ),
            },
        )
        self.decision = decision


_MODE_ORDER = {
    PriorityMode.off: 0,
    PriorityMode.shadow: 1,
    PriorityMode.enforce: 2,
}
_RANK_ORDER = {"A": 1, "B": 2, "C": 3, "D": 4, "E": 5}

# ``None`` = memo wyłączone.  W środku bloku: assignment_id -> progres albo
# ``None`` dla „assignment nie ma jeszcze żadnego kamienia milowego".
_milestone_counts_memo: ContextVar[Optional[dict[int, Optional[dict[str, int]]]]] = (
    ContextVar("priority_milestone_counts_memo", default=None)
)


@contextmanager
def milestone_counts_scope() -> Iterator[None]:
    """Reuse assignment progress across one pass over a single job.

    ``assignment_milestone_counts`` scans ``VERIFIER_ANCHORED_CTE``; a bulk add
    repeats that identical scan once per candidate while the writer holds the
    candidate and job row locks.  The memo lives only inside this block — it is
    a ``ContextVar``, so it never outlives the request, never crosses a task
    boundary, and is dropped by :func:`invalidate_milestone_counts` as soon as a
    write inside the block can change a count.
    """

    token = _milestone_counts_memo.set({})
    try:
        yield
    finally:
        _milestone_counts_memo.reset(token)


def invalidate_milestone_counts() -> None:
    """Drop memoized progress after a write that can change a milestone count."""

    memo = _milestone_counts_memo.get()
    if memo is not None:
        memo.clear()


def _coerce_mode(value: object) -> PriorityMode:
    if isinstance(value, PriorityMode):
        return value
    raw = getattr(value, "value", value)
    try:
        return PriorityMode(str(raw).strip().lower())
    except (TypeError, ValueError):
        # Invalid runtime configuration must fail safe for rollout: a typo may
        # not unexpectedly block the entire recruitment team.
        return PriorityMode.off


def combine_priority_modes(
    global_mode: PriorityMode | str,
    user_mode: PriorityMode | str | None,
) -> PriorityMode:
    """Return the least invasive of global and per-user rollout modes."""

    global_value = _coerce_mode(global_mode)
    if user_mode is None:
        return global_value
    user_value = _coerce_mode(user_mode)
    return min((global_value, user_value), key=_MODE_ORDER.__getitem__)


async def effective_priority_mode(
    db: AsyncSession, user_id: Optional[int]
) -> PriorityMode:
    global_mode = _coerce_mode(
        getattr(settings, "RECRUITMENT_PRIORITY_MODE", PriorityMode.off.value)
    )
    if user_id is None or global_mode is PriorityMode.off:
        return global_mode
    row = await db.scalar(
        select(RecruitmentPriorityUserMode).where(
            RecruitmentPriorityUserMode.user_id == user_id
        )
    )
    return combine_priority_modes(global_mode, row.mode if row else None)


async def _current_assignment(
    db: AsyncSession,
    *,
    user_id: int,
    job_id: int,
    now: datetime,
) -> tuple[
    Optional[RecruitmentPriorityAssignment],
    Optional[RecruitmentPriorityPlanMember],
    Optional[RecruitmentPriorityPlan],
]:
    row = (
        await db.execute(
            select(
                RecruitmentPriorityAssignment,
                RecruitmentPriorityPlanMember,
                RecruitmentPriorityPlan,
            )
            .join(
                RecruitmentPriorityPlanMember,
                RecruitmentPriorityPlanMember.id
                == RecruitmentPriorityAssignment.plan_member_id,
            )
            .join(
                RecruitmentPriorityPlan,
                RecruitmentPriorityPlan.id == RecruitmentPriorityPlanMember.plan_id,
            )
            .where(
                RecruitmentPriorityPlan.status == PriorityPlanStatus.published,
                RecruitmentPriorityPlan.effective_from <= now,
                RecruitmentPriorityPlanMember.user_id == user_id,
                RecruitmentPriorityAssignment.job_id == job_id,
            )
            .order_by(
                RecruitmentPriorityPlan.version.desc(),
                RecruitmentPriorityAssignment.id.desc(),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return None, None, None
    return row[0], row[1], row[2]


async def current_priority_assignment(
    db: AsyncSession,
    *,
    user_id: int,
    job_id: int,
    now: Optional[datetime] = None,
) -> tuple[
    Optional[RecruitmentPriorityAssignment],
    Optional[RecruitmentPriorityPlanMember],
    Optional[RecruitmentPriorityPlan],
]:
    """Public read helper used when an inbound process gets its first verifier."""

    return await _current_assignment(
        db,
        user_id=user_id,
        job_id=job_id,
        now=now or datetime.now(timezone.utc),
    )


async def assignment_milestone_counts(
    db: AsyncSession,
    assignment_ids: Iterable[int],
) -> dict[int, dict[str, int]]:
    """Count verified/recommended processes with canonical attempt semantics.

    ``VERIFIER_ANCHORED_CTE`` owns the process windows and first accepted
    milestone rules used by KPI.  Reading its ``classified_process`` and
    ``classified_mf`` CTEs here prevents an old attempt's ``cv_sent`` from
    completing a newer assignment and requires recommendation time to be at
    or after the accepted ``verified`` in the same process attempt.

    Inside :func:`milestone_counts_scope` each assignment is scanned once.
    """

    ids = list(dict.fromkeys(assignment_ids))
    if not ids:
        return {}

    memo = _milestone_counts_memo.get()
    if memo is None:
        return await _query_milestone_counts(db, ids)

    missing = [assignment_id for assignment_id in ids if assignment_id not in memo]
    if missing:
        fetched = await _query_milestone_counts(db, missing)
        memo.update(
            {assignment_id: fetched.get(assignment_id) for assignment_id in missing}
        )
    return {
        assignment_id: progress
        for assignment_id in ids
        if (progress := memo.get(assignment_id)) is not None
    }


async def _query_milestone_counts(
    db: AsyncSession,
    ids: list[int],
) -> dict[int, dict[str, int]]:
    from app.services.kpi_panel import VERIFIER_ANCHORED_CTE

    rows = (
        await db.execute(
            text(
                VERIFIER_ANCHORED_CTE
                + """
                SELECT cp.eligibility_assignment_id AS assignment_id,
                       count(DISTINCT cp.id) AS verifications,
                       count(DISTINCT cp.id) FILTER (
                           WHERE recommendation.process_id IS NOT NULL
                       ) AS recommendations
                FROM classified_process cp
                JOIN classified_mf verified
                  ON verified.process_id = cp.id
                 AND verified.stage = 'verified'
                LEFT JOIN classified_mf recommendation
                  ON recommendation.process_id = cp.id
                 AND recommendation.stage = 'cv_sent'
                 AND recommendation.reached_at >= verified.reached_at
                WHERE cp.eligibility_assignment_id =
                      ANY(CAST(:assignment_ids AS INTEGER[]))
                  AND cp.kpi_eligible IS TRUE
                  AND cp.credit_user_id IS NOT NULL
                GROUP BY cp.eligibility_assignment_id
                """
            ),
            {"assignment_ids": ids},
        )
    ).all()
    return {
        int(row.assignment_id): {
            "verifications": int(row.verifications),
            "recommendations": int(row.recommendations),
        }
        for row in rows
    }


async def _accepted_verification_count(db: AsyncSession, assignment_id: int) -> int:
    counts = await assignment_milestone_counts(db, [assignment_id])
    return counts.get(assignment_id, {}).get("verifications", 0)


def _assignment_targets_reached(
    assignment: RecruitmentPriorityAssignment,
    progress: dict[str, int],
) -> bool:
    if progress["verifications"] < assignment.verification_target:
        return False
    return progress["recommendations"] >= assignment.recommendation_target


async def _higher_rank_is_behind(
    db: AsyncSession,
    *,
    assignment: RecruitmentPriorityAssignment,
    member: RecruitmentPriorityPlanMember,
) -> bool:
    current_rank = _RANK_ORDER[getattr(assignment.rank, "value", assignment.rank)]
    siblings = (
        (
            await db.execute(
                select(RecruitmentPriorityAssignment).where(
                    RecruitmentPriorityAssignment.plan_member_id == member.id
                )
            )
        )
        .scalars()
        .all()
    )
    higher_assignments = []
    for higher in siblings:
        rank_value = getattr(higher.rank, "value", higher.rank)
        if _RANK_ORDER[str(rank_value)] >= current_rank:
            continue
        higher_assignments.append(higher)
    if not higher_assignments:
        return False

    higher_ids = [higher.id for higher in higher_assignments]
    progress_by_id = await assignment_milestone_counts(db, higher_ids)
    blocker_ids = set(
        (
            await db.execute(
                select(RecruitmentPriorityBlocker.assignment_id).where(
                    RecruitmentPriorityBlocker.assignment_id.in_(higher_ids),
                    RecruitmentPriorityBlocker.status == PriorityBlockerStatus.accepted,
                    RecruitmentPriorityBlocker.resolved_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    empty_progress = {"verifications": 0, "recommendations": 0}
    for higher in higher_assignments:
        if _assignment_targets_reached(
            higher,
            progress_by_id.get(higher.id, empty_progress),
        ):
            continue
        if higher.id in blocker_ids:
            continue
        return True
    return False


async def _consume_exception(
    db: AsyncSession,
    *,
    user_id: int,
    job_id: int,
    candidate_id: int,
    now: datetime,
) -> Optional[RecruitmentPriorityException]:
    row = await db.scalar(
        select(RecruitmentPriorityException)
        .where(
            RecruitmentPriorityException.user_id == user_id,
            RecruitmentPriorityException.job_id == job_id,
            RecruitmentPriorityException.status == PriorityExceptionStatus.approved,
            RecruitmentPriorityException.valid_from <= now,
            RecruitmentPriorityException.expires_at > now,
        )
        .order_by(RecruitmentPriorityException.id)
        .with_for_update()
        .limit(1)
    )
    if row is None:
        return None
    row.status = PriorityExceptionStatus.consumed
    row.consumed_at = now
    row.consumed_candidate_id = candidate_id
    await db.flush()
    return row


async def _has_continuation(
    db: AsyncSession, *, candidate_id: int, job_id: int
) -> bool:
    process = await db.scalar(
        select(RecruitmentProcess.id)
        .where(
            RecruitmentProcess.candidate_id == candidate_id,
            RecruitmentProcess.job_id == job_id,
            RecruitmentProcess.status == ProcessStatus.open,
        )
        .limit(1)
    )
    return process is not None


async def decide_priority_work_access(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    actor_user_id: Optional[int],
    origin_kind: PriorityOriginKind = PriorityOriginKind.assigned,
    action: str = "open_process",
    continuation_exists: Optional[bool] = None,
    consume_exception: bool = True,
    require_existing: bool = False,
    frozen_origin_assignment_id: Optional[int] = None,
    frozen_priority_compliant: Optional[bool] = None,
    work_channel: Optional[PriorityChannel] = None,
    job_is_open: Optional[bool] = None,
) -> PriorityWorkDecision:
    """Freeze the policy decision for a process-open attempt.

    The caller owns commit/rollback.  A consumed exception therefore rolls
    back together with a failed stage write.
    """

    mode = await effective_priority_mode(db, actor_user_id)
    if continuation_exists is None:
        continuation_exists = await _has_continuation(
            db, candidate_id=candidate_id, job_id=job_id
        )
    if continuation_exists:
        return PriorityWorkDecision(
            allowed=True,
            mode=mode,
            reason=PriorityWorkReason.continuation,
            is_continuation=True,
        )

    # `off` nie może odrzucić żadnej pracy człowieka — automat podpisu umowy
    # zachowuje się wtedy jak przed Priority Lockiem i wpada niżej w `mode_off`.
    if require_existing and mode is not PriorityMode.off:
        return PriorityWorkDecision(
            allowed=False,
            mode=mode,
            reason=PriorityWorkReason.existing_process_required,
            is_continuation=False,
            kpi_eligible=False,
            priority_compliant=False,
        )

    now = datetime.now(timezone.utc)
    if origin_kind == PriorityOriginKind.external_observed:
        # Traffit is evidence imported from an external system, never a source
        # of recruiter KPI credit or plan ownership.
        return PriorityWorkDecision(
            allowed=True,
            mode=mode,
            reason=PriorityWorkReason.external_observed,
            is_continuation=False,
            kpi_eligible=False,
            priority_compliant=None,
        )

    if job_is_open is False and mode is not PriorityMode.off:
        if mode is PriorityMode.shadow:
            return PriorityWorkDecision(
                allowed=True,
                mode=mode,
                reason=PriorityWorkReason.shadow_job_not_open,
                is_continuation=False,
                assignment_owner_user_id=actor_user_id,
                kpi_eligible=True,
                priority_compliant=False,
                violation=True,
            )
        return PriorityWorkDecision(
            allowed=False,
            mode=mode,
            reason=PriorityWorkReason.job_not_open,
            is_continuation=False,
            assignment_owner_user_id=actor_user_id,
            kpi_eligible=False,
            priority_compliant=False,
        )

    if origin_kind == PriorityOriginKind.external_inbound:
        frozen_row = None
        if frozen_origin_assignment_id is not None:
            frozen_row = (
                await db.execute(
                    select(
                        RecruitmentPriorityAssignment,
                        RecruitmentPriorityPlanMember,
                        RecruitmentPriorityPlan,
                    )
                    .join(
                        RecruitmentPriorityPlanMember,
                        RecruitmentPriorityPlanMember.id
                        == RecruitmentPriorityAssignment.plan_member_id,
                    )
                    .join(
                        RecruitmentPriorityPlan,
                        RecruitmentPriorityPlan.id
                        == RecruitmentPriorityPlanMember.plan_id,
                    )
                    .where(
                        RecruitmentPriorityAssignment.id == frozen_origin_assignment_id,
                        RecruitmentPriorityAssignment.job_id == job_id,
                    )
                    .limit(1)
                )
            ).first()
        if frozen_priority_compliant is not None:
            frozen_assignment = frozen_member = frozen_plan = None
            if frozen_row is not None:
                frozen_assignment, frozen_member, frozen_plan = frozen_row
            return PriorityWorkDecision(
                allowed=True,
                mode=mode,
                reason=PriorityWorkReason.external_inbound,
                is_continuation=False,
                active_plan_id=frozen_plan.id if frozen_plan else None,
                assignment_id=frozen_assignment.id if frozen_assignment else None,
                assignment_owner_user_id=(
                    frozen_member.user_id if frozen_member else None
                ),
                kpi_eligible=None,
                priority_compliant=frozen_priority_compliant,
            )
        if frozen_row is not None:
            frozen_assignment, frozen_member, frozen_plan = frozen_row
            return PriorityWorkDecision(
                allowed=True,
                mode=mode,
                reason=PriorityWorkReason.external_inbound,
                is_continuation=False,
                active_plan_id=frozen_plan.id,
                assignment_id=frozen_assignment.id,
                assignment_owner_user_id=frozen_member.user_id,
                kpi_eligible=None,
                priority_compliant=True,
            )
        assignment = member = plan = None
        if actor_user_id is not None:
            assignment, member, plan = await _current_assignment(
                db, user_id=actor_user_id, job_id=job_id, now=now
            )
        assignment_is_active = bool(
            assignment and member and member.status == PriorityMemberStatus.active
        )
        return PriorityWorkDecision(
            allowed=True,
            mode=mode,
            reason=PriorityWorkReason.external_inbound,
            is_continuation=False,
            active_plan_id=plan.id if plan else None,
            assignment_id=assignment.id if assignment else None,
            assignment_owner_user_id=(
                member.user_id if assignment_is_active and member else None
            ),
            # Eligibility is decided when the first verification is accepted.
            # This keeps inbound data while preventing link creator/approver
            # identity from manufacturing KPI credit.
            kpi_eligible=None,
            priority_compliant=assignment_is_active,
        )

    if mode is PriorityMode.off:
        return PriorityWorkDecision(
            allowed=True,
            mode=mode,
            reason=PriorityWorkReason.mode_off,
            is_continuation=False,
            assignment_owner_user_id=actor_user_id,
            kpi_eligible=True,
            priority_compliant=None,
        )

    assignment = member = plan = None
    if actor_user_id is not None:
        assignment, member, plan = await _current_assignment(
            db, user_id=actor_user_id, job_id=job_id, now=now
        )
    blocked_reason: PriorityWorkReason
    if assignment is None or member is None:
        blocked_reason = PriorityWorkReason.job_not_assigned
    elif member.status != PriorityMemberStatus.active:
        blocked_reason = PriorityWorkReason.member_paused
    elif work_channel is None or not (
        assignment.channel == PriorityChannel.mixed
        or assignment.channel == work_channel
    ):
        blocked_reason = PriorityWorkReason.channel_not_assigned
    else:
        # New sourcing on the lower rank stops after its verification target.
        # Whether a higher rank is "done" is stricter: both verification and
        # recommendation targets must be met (or its blocker accepted).
        target_reached = (
            await _accepted_verification_count(db, assignment.id)
            >= assignment.verification_target
        )
        blocked_by_rank = target_reached and await _higher_rank_is_behind(
            db, assignment=assignment, member=member
        )
        if not blocked_by_rank:
            return PriorityWorkDecision(
                allowed=True,
                mode=mode,
                reason=PriorityWorkReason.assigned,
                is_continuation=False,
                active_plan_id=plan.id if plan else None,
                assignment_id=assignment.id,
                assignment_owner_user_id=member.user_id,
                kpi_eligible=True,
                priority_compliant=True,
            )
        blocked_reason = PriorityWorkReason.higher_rank_behind

    if mode is PriorityMode.enforce and consume_exception and actor_user_id is not None:
        exception = await _consume_exception(
            db,
            user_id=actor_user_id,
            job_id=job_id,
            candidate_id=candidate_id,
            now=now,
        )
        if exception is not None:
            return PriorityWorkDecision(
                allowed=True,
                mode=mode,
                reason=PriorityWorkReason.approved_exception,
                is_continuation=False,
                active_plan_id=plan.id if plan else None,
                assignment_id=exception.origin_assignment_id,
                assignment_owner_user_id=actor_user_id,
                exception_id=exception.id,
                kpi_eligible=False,
                priority_compliant=False,
            )

    if mode is PriorityMode.shadow:
        reason = {
            PriorityWorkReason.higher_rank_behind: (
                PriorityWorkReason.shadow_higher_rank_behind
            ),
            PriorityWorkReason.channel_not_assigned: (
                PriorityWorkReason.shadow_channel_mismatch
            ),
        }.get(blocked_reason, PriorityWorkReason.shadow_no_assignment)
        return PriorityWorkDecision(
            allowed=True,
            mode=mode,
            reason=reason,
            is_continuation=False,
            active_plan_id=plan.id if plan else None,
            assignment_id=assignment.id if assignment else None,
            assignment_owner_user_id=actor_user_id,
            kpi_eligible=True,
            priority_compliant=False,
            violation=True,
        )

    return PriorityWorkDecision(
        allowed=False,
        mode=mode,
        reason=blocked_reason,
        is_continuation=False,
        active_plan_id=plan.id if plan else None,
        assignment_id=assignment.id if assignment else None,
        assignment_owner_user_id=actor_user_id,
        kpi_eligible=False,
        priority_compliant=False,
    )


async def assert_priority_work_access(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    actor_user_id: Optional[int],
    origin_kind: PriorityOriginKind = PriorityOriginKind.assigned,
    action: str = "open_process",
    continuation_exists: Optional[bool] = None,
    consume_exception: bool = True,
    require_existing: bool = False,
    frozen_origin_assignment_id: Optional[int] = None,
    frozen_priority_compliant: Optional[bool] = None,
    work_channel: Optional[PriorityChannel] = None,
    job_is_open: Optional[bool] = None,
) -> PriorityWorkDecision:
    decision = await decide_priority_work_access(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        actor_user_id=actor_user_id,
        origin_kind=origin_kind,
        action=action,
        continuation_exists=continuation_exists,
        consume_exception=consume_exception,
        require_existing=require_existing,
        frozen_origin_assignment_id=frozen_origin_assignment_id,
        frozen_priority_compliant=frozen_priority_compliant,
        work_channel=work_channel,
        job_is_open=job_is_open,
    )
    if not decision.allowed:
        raise PriorityWorkLocked(
            decision,
            action=action,
            candidate_id=candidate_id,
            job_id=job_id,
        )
    return decision
