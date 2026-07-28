"""Atomic domain service for candidate-global telephone coordination.

The service owns state transitions, capacity and audit writes.  It deliberately
does not read feature flags and never commits: ingress hooks decide whether the
feature is active, while the API/worker owns the surrounding transaction.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from typing import Any, Iterable, Mapping, Optional, Sequence
from zoneinfo import ZoneInfo

from sqlalchemy import and_, exists
from sqlalchemy import case as sql_case
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.call import Call, CallDirection, CallStatus
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.candidate_contact import (
    CONTACT_OPPORTUNITY_OUTCOMES,
    CONTACT_OUTCOMES,
    CandidateContactCase,
    CandidateContactEvent,
    CandidateContactEventType,
    CandidateContactOpportunity,
    CandidateContactOpportunityOutcome,
    CandidateContactOpportunitySource,
    CandidateContactOutcome,
    CandidateContactState,
    CandidateContactTraffitLedger,
)
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole

WARSAW = ZoneInfo("Europe/Warsaw")
QUEUE_LIMIT = 20
OPERATIONAL_ROLES = (UserRole.recruiter, UserRole.sourcer, UserRole.tac)
_PRIORITY_WEIGHT = {
    JobPriority.urgent.value: 4,
    JobPriority.high.value: 3,
    JobPriority.medium.value: 2,
    JobPriority.low.value: 1,
}
_SOURCE_ALIASES = {
    "pipeline": CandidateContactOpportunitySource.pipeline.value,
    "nexus_pipeline": CandidateContactOpportunitySource.pipeline.value,
    "nexus_pipeline_bulk": CandidateContactOpportunitySource.pipeline.value,
    "shortlist": CandidateContactOpportunitySource.shortlist.value,
    "nexus_shortlist": CandidateContactOpportunitySource.shortlist.value,
    "nexus_shortlist_promotion": CandidateContactOpportunitySource.shortlist.value,
    "traffit": CandidateContactOpportunitySource.traffit.value,
    "traffit_pipeline_import": CandidateContactOpportunitySource.traffit.value,
    "manual": CandidateContactOpportunitySource.manual.value,
}
_TRAFFIT_TERMINAL_WORKFLOW_TYPES = {"end-good", "end-bad", "wait"}


class ContactValidationError(ValueError):
    """The request violates a contact-domain invariant (HTTP 422)."""


class CandidateContactError(ContactValidationError):
    """Base error mapped by the HTTP layer."""


class ContactCaseNotFound(CandidateContactError):
    pass


class ContactOpportunityNotFound(CandidateContactError):
    pass


class ContactConflict(CandidateContactError):
    """A current row/owner/capacity/idempotency conflict (HTTP 409)."""


class ContactCaseVersionConflict(ContactConflict):
    def __init__(self, *, expected: int, actual: int):
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"candidate contact case version conflict: expected {expected}, actual {actual}"
        )


class ContactCaseOwnershipError(ContactConflict):
    pass


class ContactCapacityError(ContactConflict):
    pass


class ContactIdempotencyConflict(ContactConflict):
    pass


@dataclass(frozen=True)
class AttemptResult:
    case: CandidateContactCase
    call: Call
    replayed: bool = False

    @property
    def call_id(self) -> Optional[int]:
        return self.call.id


@dataclass
class ProcessingStats:
    scanned: int = 0
    reassigned: int = 0
    cooldown_released: int = 0
    phone_restored: int = 0
    assigned_from_waiting: int = 0
    completed: int = 0


def _as_utc(value: Optional[datetime]) -> datetime:
    moment = value or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        # Domain callers deal in persisted timestamps.  Treat a naive value as
        # UTC instead of silently applying the host machine's timezone.
        return moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def _local(value: datetime) -> datetime:
    return _as_utc(value).astimezone(WARSAW)


def _next_weekday(day):
    next_day = day + timedelta(days=1)
    while next_day.weekday() >= 5:
        next_day += timedelta(days=1)
    return next_day


def next_business_day_at(
    value: datetime, *, hour: int = 10, minute: int = 0
) -> datetime:
    """Return the next Mon–Fri local time as an aware UTC timestamp."""

    local = _local(value)
    target = datetime.combine(
        _next_weekday(local.date()),
        time(hour=hour, minute=minute),
        tzinfo=WARSAW,
    )
    return target.astimezone(timezone.utc)


def initial_contact_due_at(value: datetime) -> datetime:
    """16:00 Warsaw cutoff; same-day 18:00, otherwise next weekday 10:00."""

    local = _local(value)
    cutoff = time(16, 0)
    if local.weekday() < 5 and local.timetz().replace(tzinfo=None) <= cutoff:
        return local.replace(hour=18, minute=0, second=0, microsecond=0).astimezone(
            timezone.utc
        )
    return next_business_day_at(local, hour=10)


def _normalise_source(source: str) -> str:
    try:
        return _SOURCE_ALIASES[source]
    except KeyError as exc:
        raise CandidateContactError(f"unsupported contact source: {source}") from exc


def _source_external_id_key(value: str) -> tuple[int, int | str]:
    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, str(value))


def _is_newer_source_position(
    opportunity: CandidateContactOpportunity,
    *,
    occurred_at: datetime,
    external_id: Optional[str],
) -> bool:
    current_at = opportunity.source_cursor_created_at
    if current_at is None:
        return True
    incoming_at = _as_utc(occurred_at)
    current_at = _as_utc(current_at)
    if incoming_at != current_at:
        return incoming_at > current_at
    if external_id is None or opportunity.source_cursor_external_id is None:
        # Equal-second ordering without both ids would be arbitrary.
        return False
    return _source_external_id_key(external_id) > _source_external_id_key(
        opportunity.source_cursor_external_id
    )


def _advance_source_position(
    opportunity: CandidateContactOpportunity,
    *,
    occurred_at: datetime,
    external_id: Optional[str],
) -> None:
    opportunity.source_cursor_created_at = _as_utc(occurred_at)
    opportunity.source_cursor_external_id = external_id


def _set_local_close_fence(
    opportunity: CandidateContactOpportunity,
    *,
    occurred_at: datetime,
) -> None:
    """Fence stale Traffit starts after an authoritative Nexus-side close."""

    current_source_at = opportunity.source_cursor_created_at
    if current_source_at is None or occurred_at >= _as_utc(current_source_at):
        opportunity.source_cursor_created_at = occurred_at
        opportunity.source_cursor_external_id = None


def _traffit_ledger_action(raw_payload: Mapping[str, Any]) -> Optional[str]:
    synthetic_action = raw_payload.get("contact_action")
    if synthetic_action in {"ensure", "close"}:
        return str(synthetic_action)
    workflow_state = raw_payload.get("workflow_state")
    if not isinstance(workflow_state, Mapping):
        return None
    workflow_type = str(workflow_state.get("type") or "").strip()
    if bool(workflow_state.get("is_rejection")) or (
        workflow_type in _TRAFFIT_TERMINAL_WORKFLOW_TYPES
    ):
        return "close"
    return "ensure" if workflow_type else None


async def _latest_processed_traffit_pair_event(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> Optional[CandidateContactTraffitLedger]:
    latest_at = await db.scalar(
        select(func.max(CandidateContactTraffitLedger.source_created_at)).where(
            CandidateContactTraffitLedger.status == "processed",
            CandidateContactTraffitLedger.candidate_id == candidate_id,
            CandidateContactTraffitLedger.job_id == job_id,
        )
    )
    if latest_at is None:
        return None
    rows = (
        (
            await db.execute(
                select(CandidateContactTraffitLedger).where(
                    CandidateContactTraffitLedger.status == "processed",
                    CandidateContactTraffitLedger.candidate_id == candidate_id,
                    CandidateContactTraffitLedger.job_id == job_id,
                    CandidateContactTraffitLedger.source_created_at == latest_at,
                )
            )
        )
        .scalars()
        .all()
    )
    return (
        max(
            rows,
            key=lambda row: _source_external_id_key(row.external_event_id),
        )
        if rows
        else None
    )


async def _newer_traffit_terminal_exists(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    occurred_at: datetime,
    external_id: Optional[str],
) -> bool:
    latest = await _latest_processed_traffit_pair_event(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
    )
    if latest is None or _traffit_ledger_action(latest.raw_payload) != "close":
        return False
    incoming_at = _as_utc(occurred_at)
    latest_at = _as_utc(latest.source_created_at)
    if latest_at != incoming_at:
        return latest_at > incoming_at
    if external_id is None:
        return True
    return _source_external_id_key(latest.external_event_id) >= _source_external_id_key(
        external_id
    )


async def _record_traffit_terminal_watermark(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    occurred_at: datetime,
    external_id: Optional[str],
    reason: str,
) -> None:
    """Persist a no-case terminal so every later Traffit ingress sees it."""

    event_id = external_id or (
        f"terminal:{candidate_id}:{job_id}:{int(occurred_at.timestamp() * 1_000_000)}"
    )
    event_id = event_id[:255]
    ledger = await db.scalar(
        select(CandidateContactTraffitLedger)
        .where(CandidateContactTraffitLedger.external_event_id == event_id)
        .with_for_update()
    )
    payload = {
        "id": event_id,
        "created_at": occurred_at.isoformat(),
        "contact_action": "close",
        "reason": reason,
    }
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    attempted_at = datetime.now(timezone.utc)
    if ledger is None:
        ledger = CandidateContactTraffitLedger(
            external_event_id=event_id,
            source_created_at=occurred_at,
            candidate_id=candidate_id,
            job_id=job_id,
            status="processed",
            payload_hash=payload_hash,
            raw_payload=payload,
            attempts=1,
            last_attempt_at=attempted_at,
            processed_at=attempted_at,
        )
        db.add(ledger)
    else:
        ledger.source_created_at = occurred_at
        ledger.candidate_id = candidate_id
        ledger.job_id = job_id
        ledger.status = "processed"
        ledger.payload_hash = payload_hash
        ledger.raw_payload = payload
        ledger.attempts = int(ledger.attempts or 0) + 1
        ledger.last_attempt_at = attempted_at
        ledger.error = None
        ledger.processed_at = attempted_at
    await db.flush()


def _normalise_contact_outcome(
    outcome: CandidateContactOutcome | str,
) -> str:
    value = (
        outcome.value if isinstance(outcome, CandidateContactOutcome) else str(outcome)
    )
    if value not in CONTACT_OUTCOMES:
        raise CandidateContactError(f"unsupported contact outcome: {value}")
    return value


def _normalise_job_outcomes(
    values: Mapping[int, CandidateContactOpportunityOutcome | str]
    | Sequence[Any]
    | None,
) -> dict[int, str]:
    if not values:
        return {}
    if isinstance(values, Mapping):
        raw_items: Iterable[tuple[Any, Any]] = values.items()
    else:
        items: list[tuple[Any, Any]] = []
        for item in values:
            if isinstance(item, Mapping):
                items.append((item.get("job_id"), item.get("outcome")))
            else:
                items.append(
                    (getattr(item, "job_id", None), getattr(item, "outcome", None))
                )
        raw_items = items

    result: dict[int, str] = {}
    for raw_job_id, raw_outcome in raw_items:
        try:
            job_id = int(raw_job_id)
        except (TypeError, ValueError) as exc:
            raise CandidateContactError("opportunity outcome requires job_id") from exc
        value = (
            raw_outcome.value
            if isinstance(raw_outcome, CandidateContactOpportunityOutcome)
            else str(raw_outcome)
        )
        if value not in CONTACT_OPPORTUNITY_OUTCOMES:
            raise CandidateContactError(
                f"unsupported opportunity outcome for job {job_id}: {value}"
            )
        if job_id in result:
            raise CandidateContactError(
                f"duplicate opportunity outcome for job {job_id}"
            )
        result[job_id] = value
    return result


def _event(
    db: AsyncSession,
    case: CandidateContactCase,
    event_type: CandidateContactEventType | str,
    *,
    occurred_at: datetime,
    actor_user_id: Optional[int] = None,
    opportunity: Optional[CandidateContactOpportunity] = None,
    call_id: Optional[int] = None,
    from_state: Optional[str] = None,
    to_state: Optional[str] = None,
    details: Optional[dict[str, Any]] = None,
    idempotency_key: Optional[str] = None,
) -> None:
    db.add(
        CandidateContactEvent(
            case_id=case.id,
            candidate_id=case.candidate_id,
            opportunity_id=opportunity.id if opportunity else None,
            job_id=opportunity.job_id if opportunity else None,
            actor_user_id=actor_user_id,
            call_id=call_id,
            event_type=(
                event_type.value
                if isinstance(event_type, CandidateContactEventType)
                else event_type
            ),
            from_state=from_state,
            to_state=to_state,
            details=details or {},
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
        )
    )


def _set_state(
    case: CandidateContactCase,
    state: CandidateContactState | str,
) -> str:
    old = case.state
    case.state = state.value if isinstance(state, CandidateContactState) else state
    return old


async def _open_job_rows(
    db: AsyncSession, case_id: int
) -> list[tuple[Job, CandidateContactOpportunity]]:
    return list(
        (
            await db.execute(
                select(Job, CandidateContactOpportunity)
                .join(
                    CandidateContactOpportunity,
                    CandidateContactOpportunity.job_id == Job.id,
                )
                .where(
                    CandidateContactOpportunity.case_id == case_id,
                    CandidateContactOpportunity.closed_at.is_(None),
                    Job.status != JobStatus.closed,
                )
            )
        ).all()
    )


def _job_priority(job: Job) -> int:
    value = (
        job.priority.value
        if isinstance(job.priority, JobPriority)
        else str(job.priority)
    )
    return _PRIORITY_WEIGHT.get(value, 0)


async def _eligible_users(
    db: AsyncSession,
    case: CandidateContactCase,
) -> tuple[list[tuple[Job, CandidateContactOpportunity]], list[User]]:
    job_rows = await _open_job_rows(db, case.id)
    if not job_rows:
        return [], []
    job_ids = [job.id for job, _ in job_rows]
    user_ids: set[int] = set()
    for job, _ in job_rows:
        for user_id in (
            job.recruiter_id,
            job.tac_id,
            job.delivery_lead_id,
        ):
            if user_id is not None:
                user_ids.add(user_id)
    collaborator_ids = (
        (
            await db.execute(
                select(JobCollaborator.user_id).where(
                    JobCollaborator.job_id.in_(job_ids),
                    JobCollaborator.removed_from_auto_cc.is_(False),
                )
            )
        )
        .scalars()
        .all()
    )
    user_ids.update(collaborator_ids)
    if not user_ids:
        return job_rows, []
    users = (
        (
            await db.execute(
                select(User).where(User.id.in_(user_ids), User.is_active.is_(True))
            )
        )
        .scalars()
        .all()
    )
    operational = [user for user in users if user.has_any_role(*OPERATIONAL_ROLES)]
    return job_rows, operational


async def _current_owner_is_eligible(
    db: AsyncSession,
    case: CandidateContactCase,
) -> bool:
    if case.owner_user_id is None:
        return False
    _, eligible = await _eligible_users(db, case)
    return case.owner_user_id in {user.id for user in eligible}


async def _pending_queue_state(
    db: AsyncSession,
    case: CandidateContactCase,
) -> str:
    """Recover callback semantics after a capacity/unassigned transition."""

    if case.state == CandidateContactState.callback_due.value:
        return CandidateContactState.callback_due.value
    has_callback_opportunity = await db.scalar(
        select(func.count(CandidateContactOpportunity.id)).where(
            CandidateContactOpportunity.case_id == case.id,
            CandidateContactOpportunity.closed_at.is_(None),
            CandidateContactOpportunity.outcome.in_(
                (
                    CandidateContactOpportunityOutcome.maybe.value,
                    CandidateContactOpportunityOutcome.not_presented.value,
                )
            ),
        )
    )
    if has_callback_opportunity:
        return CandidateContactState.callback_due.value
    latest_call = (
        await db.execute(
            select(Call.contact_outcome, Call.callback_at)
            .where(Call.contact_case_id == case.id)
            .order_by(Call.started_at.desc(), Call.id.desc())
            .limit(1)
        )
    ).one_or_none()
    if (
        latest_call is not None
        and latest_call.contact_outcome
        == CandidateContactOutcome.callback_requested.value
        and latest_call.callback_at is not None
        and case.due_at is not None
        and _as_utc(latest_call.callback_at) == _as_utc(case.due_at)
    ):
        return CandidateContactState.callback_due.value
    return CandidateContactState.queued.value


async def _claim_slot(
    db: AsyncSession,
    *,
    user_id: int,
) -> Optional[int]:
    # The user-row lock serializes all slot allocation for this owner.  The
    # partial UNIQUE index and 1..20 CHECK remain the final DB-level fence.
    # populate_existing, bo ten sam user bywa już w sesji z niezablokowanego
    # odczytu (_eligible_users, auth) — kontrola is_active/roles musi patrzeć
    # na stan po zdjęciu blokady, nie na snapshot sprzed niej.
    user = await db.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active or not user.has_any_role(*OPERATIONAL_ROLES):
        return None
    # AsyncSessionLocal disables autoflush. Persist earlier allocations made
    # by this transaction before reading the owner's occupied slots; otherwise
    # a worker processing a batch could repeatedly choose slot 1 and only fail
    # against the UNIQUE fence at the final flush.
    await db.flush()
    used = set(
        (
            await db.execute(
                select(CandidateContactCase.queue_slot).where(
                    CandidateContactCase.owner_user_id == user_id,
                    CandidateContactCase.queue_slot.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    )
    return next((slot for slot in range(1, QUEUE_LIMIT + 1) if slot not in used), None)


async def _assign_best_owner(
    db: AsyncSession,
    case: CandidateContactCase,
    *,
    due_at: datetime,
    occurred_at: datetime,
    exclude_owner_ids: Iterable[int] = (),
    queue_state: CandidateContactState | str = CandidateContactState.queued,
) -> bool:
    target_state = (
        queue_state.value
        if isinstance(queue_state, CandidateContactState)
        else str(queue_state)
    )
    if target_state not in {
        CandidateContactState.queued.value,
        CandidateContactState.callback_due.value,
    }:
        raise CandidateContactError(
            f"unsupported queue assignment state: {target_state}"
        )
    excluded = {int(value) for value in exclude_owner_ids if value is not None}
    job_rows, users = await _eligible_users(db, case)
    if job_rows:
        ordered_jobs = sorted(
            job_rows,
            key=lambda row: (
                -_job_priority(row[0]),
                row[1].linked_at or occurred_at,
                row[0].id,
            ),
        )
        case.primary_job_id = ordered_jobs[0][0].id
    by_id = {user.id: user for user in users if user.id not in excluded}

    # Serialize the complete least-loaded decision, not only the final slot
    # claim. Locking every eligible user in stable ID order means concurrent
    # workers with overlapping pools cannot both observe the same stale load
    # and select U1 while U2 has become less loaded.
    if by_id:
        # populate_existing: _eligible_users załadowało tych samych userów BEZ
        # blokady kilka linii wyżej, więc bez odświeżenia poniższy re-filtr
        # is_active/roles czytałby snapshot sprzed locka i byłby no-opem.
        locked_users = (
            (
                await db.execute(
                    select(User)
                    .where(User.id.in_(sorted(by_id)))
                    .order_by(User.id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
            .scalars()
            .all()
        )
        by_id = {
            user.id: user
            for user in locked_users
            if user.is_active
            and user.has_any_role(*OPERATIONAL_ROLES)
            and user.id not in excluded
        }
        # AsyncSessionLocal disables autoflush. Make allocations from earlier
        # cases in this worker batch visible to the load aggregate below.
        await db.flush()

    # Only the owner of the first priority/oldest opportunity is preferred.
    # If that exact owner is absent/inactive/full, fallback is global by load;
    # an owner of the second opportunity does not get another priority jump.
    first_job = ordered_jobs[0][0] if job_rows else None
    preferred = (
        [first_job.recruiter_id]
        if first_job is not None and first_job.recruiter_id in by_id
        else []
    )

    load_rows = (
        (
            await db.execute(
                select(
                    CandidateContactCase.owner_user_id,
                    func.count(CandidateContactCase.id),
                )
                .where(
                    CandidateContactCase.owner_user_id.in_(list(by_id) or [-1]),
                    CandidateContactCase.queue_slot.is_not(None),
                )
                .group_by(CandidateContactCase.owner_user_id)
            )
        ).all()
        if by_id
        else []
    )
    loads = {int(owner_id): int(count) for owner_id, count in load_rows}
    fallback = sorted(
        (user_id for user_id in by_id if user_id not in preferred),
        key=lambda user_id: (loads.get(user_id, 0), user_id),
    )

    for user_id in [*preferred, *fallback]:
        slot = await _claim_slot(db, user_id=user_id)
        if slot is None:
            continue
        case.owner_user_id = user_id
        case.queue_slot = slot
        case.assigned_at = occurred_at
        case.due_at = due_at
        case.cooldown_until = None
        case.completed_at = None
        case.state = target_state
        return True

    case.owner_user_id = None
    case.queue_slot = None
    case.assigned_at = None
    case.due_at = due_at
    case.state = (
        CandidateContactState.awaiting_capacity.value
        if by_id
        else CandidateContactState.unassigned.value
    )
    return False


def _complete_case(case: CandidateContactCase, occurred_at: datetime) -> None:
    if case.owner_user_id is not None:
        case.previous_owner_user_id = case.owner_user_id
    case.owner_user_id = None
    case.queue_slot = None
    case.due_at = None
    case.cooldown_until = None
    case.completed_at = occurred_at
    case.state = CandidateContactState.completed.value


async def _recompute_case_after_opportunities(
    db: AsyncSession,
    case: CandidateContactCase,
    *,
    occurred_at: datetime,
    actor_user_id: Optional[int] = None,
) -> None:
    if case.state == CandidateContactState.suppressed.value:
        return
    open_opportunities = (
        (
            await db.execute(
                select(CandidateContactOpportunity).where(
                    CandidateContactOpportunity.case_id == case.id,
                    CandidateContactOpportunity.closed_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )
    if not open_opportunities:
        _complete_case(case, occurred_at)
        return
    if all(
        opportunity.outcome == CandidateContactOpportunityOutcome.interested.value
        and opportunity.meeting_event_id is not None
        for opportunity in open_opportunities
    ):
        _complete_case(case, occurred_at)
        return
    # Closing one of several opportunities must not bypass a safety hold on
    # the candidate-global case. The final close may complete the case, but a
    # remaining opportunity waits for cooldown expiry or a corrected phone.
    if case.state in {
        CandidateContactState.cooldown.value,
        CandidateContactState.blocked_no_phone.value,
    }:
        return
    has_callback_outcome = any(
        opportunity.outcome
        in {
            CandidateContactOpportunityOutcome.maybe.value,
            CandidateContactOpportunityOutcome.not_presented.value,
        }
        for opportunity in open_opportunities
    )
    has_uncontacted = any(
        opportunity.outcome is None for opportunity in open_opportunities
    )
    if (
        has_callback_outcome
        or has_uncontacted
        or case.state == CandidateContactState.callback_due.value
    ):
        # `None` is still a first call; only an explicit maybe/not_presented
        # turns it into a callback. Closing one of several pre-call jobs must
        # not relabel the remaining first attempt.
        old_queue_state = case.state
        desired_state = (
            CandidateContactState.callback_due.value
            if has_callback_outcome
            or case.state == CandidateContactState.callback_due.value
            else CandidateContactState.queued.value
        )
        owner_is_eligible = await _current_owner_is_eligible(db, case)
        if not owner_is_eligible or case.queue_slot is None:
            old_owner_id = case.owner_user_id
            old_due_at = case.due_at
            fresh_due_at = initial_contact_due_at(occurred_at)
            reassigned_due_at = (
                old_due_at
                if old_due_at is not None and _as_utc(old_due_at) > occurred_at
                else fresh_due_at
            )
            case.previous_owner_user_id = old_owner_id
            case.owner_user_id = None
            case.queue_slot = None
            case.assigned_at = None
            case.state = CandidateContactState.unassigned.value
            await _assign_best_owner(
                db,
                case,
                due_at=reassigned_due_at,
                occurred_at=occurred_at,
                exclude_owner_ids=([old_owner_id] if old_owner_id is not None else []),
                queue_state=desired_state,
            )
            _event(
                db,
                case,
                (
                    CandidateContactEventType.reassigned
                    if case.owner_user_id is not None
                    else CandidateContactEventType.awaiting_capacity
                ),
                occurred_at=occurred_at,
                actor_user_id=actor_user_id,
                from_state=old_queue_state,
                to_state=case.state,
                details={
                    "reason": (
                        "owner_no_longer_eligible"
                        if not owner_is_eligible
                        else "owner_missing_queue_slot"
                    ),
                    "old_owner_user_id": old_owner_id,
                    "new_owner_user_id": case.owner_user_id,
                    "queue_slot": case.queue_slot,
                    "previous_due_at": (
                        old_due_at.isoformat() if old_due_at is not None else None
                    ),
                },
            )
        else:
            case.state = desired_state
        return
    case.queue_slot = None
    case.due_at = None
    old_owner_id = case.owner_user_id
    if not await _current_owner_is_eligible(db, case):
        case.previous_owner_user_id = old_owner_id
        case.owner_user_id = None
        case.assigned_at = None
        await _assign_handoff_owner(db, case, occurred_at=occurred_at)
    case.state = CandidateContactState.handoff_pending.value
    if old_owner_id != case.owner_user_id:
        _event(
            db,
            case,
            (
                CandidateContactEventType.reassigned
                if case.owner_user_id is not None
                else CandidateContactEventType.awaiting_capacity
            ),
            occurred_at=occurred_at,
            actor_user_id=actor_user_id,
            from_state=CandidateContactState.handoff_pending.value,
            to_state=case.state,
            details={
                "reason": "handoff_owner_no_longer_eligible",
                "old_owner_user_id": old_owner_id,
                "new_owner_user_id": case.owner_user_id,
            },
        )


async def _assign_handoff_owner(
    db: AsyncSession,
    case: CandidateContactCase,
    *,
    occurred_at: datetime,
    exclude_owner_ids: Iterable[int] = (),
) -> None:
    """Restore a deterministic relationship owner without consuming a slot."""

    job_rows, eligible = await _eligible_users(db, case)
    excluded = {int(value) for value in exclude_owner_ids if value is not None}
    by_id = {user.id: user for user in eligible if user.id not in excluded}
    if case.previous_owner_user_id in by_id:
        case.owner_user_id = case.previous_owner_user_id
        case.assigned_at = case.assigned_at or occurred_at
        return
    ordered_jobs = sorted(
        job_rows,
        key=lambda row: (
            -_job_priority(row[0]),
            row[1].linked_at or datetime.max.replace(tzinfo=timezone.utc),
            row[0].id,
        ),
    )
    first_job = ordered_jobs[0][0] if ordered_jobs else None
    if first_job is not None and first_job.recruiter_id in by_id:
        case.owner_user_id = first_job.recruiter_id
        case.assigned_at = case.assigned_at or occurred_at
        return
    if not by_id:
        return
    load_rows = (
        await db.execute(
            select(
                CandidateContactCase.owner_user_id,
                func.count(CandidateContactCase.id),
            )
            .where(
                CandidateContactCase.owner_user_id.in_(list(by_id)),
                CandidateContactCase.queue_slot.is_not(None),
            )
            .group_by(CandidateContactCase.owner_user_id)
        )
    ).all()
    loads = {int(owner_id): int(count) for owner_id, count in load_rows}
    case.owner_user_id = min(
        by_id, key=lambda user_id: (loads.get(user_id, 0), user_id)
    )
    case.assigned_at = case.assigned_at or occurred_at


async def ensure_contact_opportunity(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    source: str,
    source_external_ref: Optional[str] = None,
    occurred_at: Optional[datetime] = None,
    assign_if_possible: bool = True,
) -> Optional[CandidateContactCase]:
    """Idempotently add one recruitment to a candidate-global contact case."""

    now = _as_utc(occurred_at)
    canonical_source = _normalise_source(source)
    is_traffit = canonical_source == CandidateContactOpportunitySource.traffit.value
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    if candidate is None:
        raise CandidateContactError(f"candidate {candidate_id} not found")
    # Share a row lock with job close/delete so the closed-job check and
    # opportunity creation form one serializable decision.
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        raise CandidateContactError(f"job {job_id} not found")
    if job.status == JobStatus.closed:
        # Contact intake is ancillary to the pipeline transaction. Fail closed
        # without raising and rolling back the caller's primary write.
        return None

    case = await db.scalar(
        select(CandidateContactCase)
        .where(CandidateContactCase.candidate_id == candidate_id)
        .with_for_update()
    )
    if is_traffit and await _newer_traffit_terminal_exists(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
        occurred_at=now,
        external_id=source_external_ref,
    ):
        return case
    created_case = case is None
    if case is None:
        case = CandidateContactCase(
            candidate_id=candidate_id,
            state=CandidateContactState.unassigned.value,
            due_at=initial_contact_due_at(now),
        )
        db.add(case)
        await db.flush()
        _event(
            db,
            case,
            CandidateContactEventType.case_created,
            occurred_at=now,
            from_state=None,
            to_state=case.state,
            details={"source": canonical_source},
        )
    current_phone = (candidate.phone or "").strip()
    rejected_phone = (case.blocked_phone_value or "").strip()
    phone_is_usable = bool(current_phone) and (
        not rejected_phone or current_phone != rejected_phone
    )

    opportunity = await db.scalar(
        select(CandidateContactOpportunity)
        .where(
            CandidateContactOpportunity.candidate_id == candidate_id,
            CandidateContactOpportunity.job_id == job_id,
        )
        .with_for_update()
    )
    if opportunity is not None and is_traffit:
        if not _is_newer_source_position(
            opportunity,
            occurred_at=now,
            external_id=source_external_ref,
        ):
            return case
        _advance_source_position(
            opportunity,
            occurred_at=now,
            external_id=source_external_ref,
        )
        if opportunity.closed_at is None:
            # Persist the latest source tuple while preserving linked_at, which
            # remains the oldest assignment for deterministic owner selection.
            await db.flush()
            return case
    elif opportunity is not None and opportunity.closed_at is None:
        return case
    if (
        opportunity is not None
        and opportunity.closed_at is not None
        and not is_traffit
        and now <= _as_utc(opportunity.closed_at)
    ):
        # Overlap polling and daily imports may replay an older non-terminal
        # history row after a newer terminal event. Only a source event newer
        # than the close is allowed to reopen this candidate/job link.
        return case

    reopened_opportunity = opportunity is not None
    if opportunity is None:
        opportunity = CandidateContactOpportunity(
            case_id=case.id,
            candidate_id=candidate_id,
            job_id=job_id,
            source=canonical_source,
            source_external_ref=source_external_ref,
            linked_at=now,
            source_cursor_created_at=now if is_traffit else None,
            source_cursor_external_id=(source_external_ref if is_traffit else None),
        )
        db.add(opportunity)
    else:
        opportunity.closed_at = None
        opportunity.closed_reason = None
        opportunity.source = canonical_source
        opportunity.source_external_ref = (
            source_external_ref or opportunity.source_external_ref
        )
        # A real reopen starts a new recruitment-contact cycle.  Keep replayed
        # events for an already-open link from mutating linked_at above, but
        # use the new cycle's source time for owner-priority decisions here.
        opportunity.linked_at = now
        opportunity.outcome = None
        opportunity.presented_at = None
        opportunity.meeting_event_id = None
        opportunity.meeting_scheduled_at = None
    await db.flush()
    existing_handoff = await db.scalar(
        select(CalendarEvent)
        .where(
            CalendarEvent.candidate_id == candidate_id,
            CalendarEvent.job_id == job_id,
            CalendarEvent.event_type.in_((EventType.screening, EventType.interview)),
            CalendarEvent.status.in_((EventStatus.scheduled, EventStatus.completed)),
        )
        .order_by(CalendarEvent.start_time, CalendarEvent.id)
        .limit(1)
    )
    if existing_handoff is not None:
        opportunity.outcome = CandidateContactOpportunityOutcome.interested.value
        opportunity.presented_at = opportunity.presented_at or now
        opportunity.meeting_event_id = existing_handoff.id
        opportunity.meeting_scheduled_at = now
        _event(
            db,
            case,
            CandidateContactEventType.handoff_scheduled,
            occurred_at=now,
            opportunity=opportunity,
            from_state=case.state,
            to_state=case.state,
            details={
                "calendar_event_id": existing_handoff.id,
                "discovered_during_intake": True,
            },
        )
    _event(
        db,
        case,
        CandidateContactEventType.opportunity_added,
        occurred_at=now,
        opportunity=opportunity,
        from_state=case.state,
        to_state=case.state,
        details={
            "source": canonical_source,
            "source_external_ref": source_external_ref,
            "reopened": reopened_opportunity,
        },
    )

    if (
        case.state != CandidateContactState.suppressed.value
        and existing_handoff is not None
    ):
        # AsyncSessionLocal uses autoflush=False. Persist the handoff adopted
        # above before the aggregate SQL decides whether every opportunity is
        # complete; otherwise the database still sees a NULL outcome/meeting
        # and can incorrectly reopen the case into the phone queue.
        await db.flush()
        incomplete_count = await db.scalar(
            select(func.count(CandidateContactOpportunity.id)).where(
                CandidateContactOpportunity.case_id == case.id,
                CandidateContactOpportunity.closed_at.is_(None),
                or_(
                    CandidateContactOpportunity.outcome
                    != CandidateContactOpportunityOutcome.interested.value,
                    CandidateContactOpportunity.outcome.is_(None),
                    CandidateContactOpportunity.meeting_event_id.is_(None),
                ),
            )
        )
        if not incomplete_count:
            old_state = case.state
            _complete_case(case, now)
            if not created_case:
                case.version += 1
            _event(
                db,
                case,
                CandidateContactEventType.case_completed,
                occurred_at=now,
                from_state=old_state,
                to_state=case.state,
                details={"reason": "existing_calendar_handoff"},
            )
            await db.flush()
            return case
        # Adopting an already-scheduled handoff must not itself reopen the
        # phone queue. If every remaining opportunity has already been
        # presented, the case only waits for meetings on the other interested
        # jobs and stays relationship-owned without consuming a slot.
        if assign_if_possible:
            await _recompute_case_after_opportunities(
                db,
                case,
                occurred_at=now,
            )
            if case.state == CandidateContactState.handoff_pending.value:
                if not created_case:
                    case.version += 1
                await db.flush()
                return case

    if case.state == CandidateContactState.suppressed.value:
        case.version += 1
        return case
    if case.state in {
        CandidateContactState.cooldown.value,
        CandidateContactState.blocked_no_phone.value,
    }:
        case.version += 1
        return case

    old_state = case.state
    terminal_reopening = case.state in {
        CandidateContactState.completed.value,
        CandidateContactState.cancelled.value,
    }
    handoff_phone_reopening = (
        case.state == CandidateContactState.handoff_pending.value
        and bool(
            await db.scalar(
                select(func.count(CandidateContactOpportunity.id)).where(
                    CandidateContactOpportunity.case_id == case.id,
                    CandidateContactOpportunity.closed_at.is_(None),
                    CandidateContactOpportunity.outcome.is_(None),
                )
            )
        )
    )
    if not assign_if_possible:
        if created_case or terminal_reopening or handoff_phone_reopening:
            if terminal_reopening or handoff_phone_reopening:
                case.attempt_count = 0
                case.cycle += 1
            if not handoff_phone_reopening:
                case.owner_user_id = None
            if terminal_reopening:
                # A newly opened opportunity is a fresh assignment decision,
                # not a cooldown/EOD retry. Do not inherit the former owner as
                # an exclusion when assignment is enabled later.
                case.previous_owner_user_id = None
            case.queue_slot = None
            case.completed_at = None
            if not phone_is_usable:
                case.state = CandidateContactState.blocked_no_phone.value
                case.blocked_phone_value = current_phone or case.blocked_phone_value
                case.due_at = None
            else:
                case.blocked_phone_value = None
                case.state = CandidateContactState.unassigned.value
                case.due_at = initial_contact_due_at(now)
            if terminal_reopening or handoff_phone_reopening:
                _event(
                    db,
                    case,
                    CandidateContactEventType.case_reopened,
                    occurred_at=now,
                    from_state=old_state,
                    to_state=case.state,
                    details={"assignment_enabled": False},
                )
        if not created_case:
            case.version += 1
        await db.flush()
        return case

    reopening = terminal_reopening or case.state in {
        CandidateContactState.handoff_pending.value,
    }
    if reopening:
        case.completed_at = None
        case.attempt_count = 0
        case.cycle += 1
        case.due_at = initial_contact_due_at(now)

    if not phone_is_usable:
        case.queue_slot = None
        case.due_at = None
        case.state = CandidateContactState.blocked_no_phone.value
        case.blocked_phone_value = current_phone or case.blocked_phone_value
    else:
        case.blocked_phone_value = None
    if phone_is_usable and reopening and case.owner_user_id is not None:
        slot = await _claim_slot(db, user_id=case.owner_user_id)
        if slot is not None:
            case.queue_slot = slot
            case.due_at = initial_contact_due_at(now)
            case.state = CandidateContactState.queued.value
        else:
            case.queue_slot = None
            case.state = CandidateContactState.awaiting_capacity.value
    elif phone_is_usable and (
        case.owner_user_id is None
        or case.state
        in {
            CandidateContactState.unassigned.value,
            CandidateContactState.awaiting_capacity.value,
            CandidateContactState.completed.value,
            CandidateContactState.cancelled.value,
        }
    ):
        await _assign_best_owner(
            db,
            case,
            due_at=initial_contact_due_at(now),
            occurred_at=now,
        )

    if reopening:
        _event(
            db,
            case,
            CandidateContactEventType.case_reopened,
            occurred_at=now,
            from_state=old_state,
            to_state=case.state,
        )
    if case.state != old_state:
        event_type = (
            CandidateContactEventType.assigned
            if case.owner_user_id is not None
            else CandidateContactEventType.awaiting_capacity
        )
        _event(
            db,
            case,
            event_type,
            occurred_at=now,
            from_state=old_state,
            to_state=case.state,
            details={
                "owner_user_id": case.owner_user_id,
                "queue_slot": case.queue_slot,
            },
        )
    if not created_case:
        case.version += 1
    await db.flush()
    return case


async def close_contact_opportunity(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    reason: str,
    actor_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
    source: Optional[str] = None,
    source_external_ref: Optional[str] = None,
    enforce_source_order: bool = True,
) -> Optional[CandidateContactCase]:
    """Close exactly one candidate/job link and recompute the global case."""

    now = _as_utc(occurred_at)
    canonical_source = _normalise_source(source) if source is not None else None
    is_traffit = canonical_source == CandidateContactOpportunitySource.traffit.value
    if is_traffit:
        # Match ensure's Candidate → Job → Case lock order. This makes the
        # no-case terminal watermark and a concurrent stale start one
        # serializable decision across both strict and daily Traffit ingress.
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == candidate_id).with_for_update()
        )
        job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
        if candidate is None or job is None:
            return None
    case = await db.scalar(
        select(CandidateContactCase)
        .where(CandidateContactCase.candidate_id == candidate_id)
        .with_for_update()
    )
    if case is None:
        if is_traffit:
            await _record_traffit_terminal_watermark(
                db,
                candidate_id=candidate_id,
                job_id=job_id,
                occurred_at=now,
                external_id=source_external_ref,
                reason=reason,
            )
        return None
    opportunity = await db.scalar(
        select(CandidateContactOpportunity)
        .where(
            CandidateContactOpportunity.candidate_id == candidate_id,
            CandidateContactOpportunity.job_id == job_id,
        )
        .with_for_update()
    )
    if opportunity is None:
        if is_traffit:
            await _record_traffit_terminal_watermark(
                db,
                candidate_id=candidate_id,
                job_id=job_id,
                occurred_at=now,
                external_id=source_external_ref,
                reason=reason,
            )
        return case
    if is_traffit:
        if not _is_newer_source_position(
            opportunity,
            occurred_at=now,
            external_id=source_external_ref,
        ):
            return case
        _advance_source_position(
            opportunity,
            occurred_at=now,
            external_id=source_external_ref,
        )
        if opportunity.closed_at is not None:
            # A later terminal still advances the durable source tuple, so an
            # older delayed start cannot reopen after it.
            opportunity.closed_at = now
            opportunity.closed_reason = reason[:64]
            await db.flush()
            return case
    elif opportunity.closed_at is not None:
        return case
    if enforce_source_order and now < _as_utc(opportunity.linked_at):
        # A delayed Traffit exception retry may arrive after a newer start
        # already reopened this candidate/job opportunity.  Source ordering is
        # authoritative. Equal timestamps are allowed here because Traffit
        # callers resolve their secondary external-id order above.
        return case
    if not enforce_source_order:
        now = max(now, _as_utc(opportunity.linked_at))
    if not is_traffit:
        # A Nexus-side close is authoritative at its wall-clock position.
        # The id-less fence rejects equal-time Traffit starts; Traffit
        # terminals retain their numeric equal-second ID.
        _set_local_close_fence(opportunity, occurred_at=now)
    old_state = case.state
    opportunity.closed_at = now
    opportunity.closed_reason = reason[:64]
    _event(
        db,
        case,
        CandidateContactEventType.opportunity_closed,
        occurred_at=now,
        actor_user_id=actor_user_id,
        opportunity=opportunity,
        from_state=old_state,
        details={"reason": reason},
    )
    await db.flush()
    await _recompute_case_after_opportunities(
        db,
        case,
        occurred_at=now,
        actor_user_id=actor_user_id,
    )
    case.version += 1
    if case.state == CandidateContactState.completed.value and old_state != case.state:
        _event(
            db,
            case,
            CandidateContactEventType.case_completed,
            occurred_at=now,
            actor_user_id=actor_user_id,
            from_state=old_state,
            to_state=case.state,
        )
    await db.flush()
    return case


async def close_job_contact_opportunities(
    db: AsyncSession,
    *,
    job_id: int,
    reason: str,
    actor_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
) -> list[CandidateContactCase]:
    """Close every active opportunity for one job, recomputing each case.

    Job close/delete paths must call this before deleting the Job.  Relying on
    ``ON DELETE CASCADE`` alone would remove opportunity rows without releasing
    the candidate-global queue slot.
    """

    # Serialize with ensure_contact_opportunity. A close must not scan before
    # an in-flight intake commits and then leave that opportunity open.
    job = await db.scalar(select(Job).where(Job.id == job_id).with_for_update())
    if job is None:
        return []
    candidate_ids = list(
        (
            await db.execute(
                select(CandidateContactOpportunity.candidate_id)
                .where(
                    CandidateContactOpportunity.job_id == job_id,
                    CandidateContactOpportunity.closed_at.is_(None),
                )
                .order_by(CandidateContactOpportunity.candidate_id)
            )
        )
        .scalars()
        .all()
    )
    changed: list[CandidateContactCase] = []
    for candidate_id in candidate_ids:
        case = await close_contact_opportunity(
            db,
            candidate_id=candidate_id,
            job_id=job_id,
            reason=reason,
            actor_user_id=actor_user_id,
            occurred_at=occurred_at,
            enforce_source_order=False,
        )
        if case is not None:
            changed.append(case)
    return changed


def _request_fingerprint(
    *,
    case_id: int,
    actor_user_id: int,
    outcome: str,
    opportunity_outcomes: Mapping[int, str],
    callback_at: Optional[datetime],
    notes: Optional[str],
    source: str,
) -> str:
    payload = {
        "case_id": case_id,
        "actor_user_id": actor_user_id,
        "outcome": outcome,
        "opportunity_outcomes": sorted(opportunity_outcomes.items()),
        "callback_at": callback_at.isoformat() if callback_at else None,
        "notes": notes,
        "source": source,
    }
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _event_attempt_key(idempotency_key: str, suffix: Optional[str] = None) -> str:
    digest = hashlib.sha256(idempotency_key.encode("utf-8")).hexdigest()
    return f"attempt:{digest}" + (f":{suffix}" if suffix else "")


async def record_contact_attempt(
    db: AsyncSession,
    *,
    case_id: int,
    actor_user_id: int,
    outcome: CandidateContactOutcome | str,
    opportunity_outcomes: Mapping[int, CandidateContactOpportunityOutcome | str]
    | Sequence[Any]
    | None,
    expected_version: int,
    idempotency_key: str,
    callback_at: Optional[datetime] = None,
    occurred_at: Optional[datetime] = None,
    notes: Optional[str] = None,
    source: str = "manual",
    allow_non_owner: bool = False,
) -> AttemptResult:
    """Persist Call + job results + state/audit as one caller-owned transaction."""

    now = _as_utc(occurred_at)
    normalised_outcome = _normalise_contact_outcome(outcome)
    job_outcomes = _normalise_job_outcomes(opportunity_outcomes)
    key = idempotency_key.strip()
    if not key or len(key) > 160:
        raise CandidateContactError("Idempotency-Key must contain 1..160 characters")
    callback_utc = _as_utc(callback_at) if callback_at is not None else None
    if callback_utc is not None and callback_utc <= now:
        raise CandidateContactError("callback_at must be in the future")
    needs_callback = (
        normalised_outcome == CandidateContactOutcome.callback_requested.value
        or any(
            value
            in {
                CandidateContactOpportunityOutcome.maybe.value,
                CandidateContactOpportunityOutcome.not_presented.value,
            }
            for value in job_outcomes.values()
        )
    )
    if needs_callback and callback_utc is None:
        raise CandidateContactError(
            "callback_at is required for callback_requested, maybe or not_presented"
        )
    if (
        normalised_outcome
        not in {
            CandidateContactOutcome.connected.value,
            CandidateContactOutcome.callback_requested.value,
        }
        and job_outcomes
    ):
        raise CandidateContactError(
            "job outcomes are allowed only when a conversation occurred"
        )

    fingerprint = _request_fingerprint(
        case_id=case_id,
        actor_user_id=actor_user_id,
        outcome=normalised_outcome,
        opportunity_outcomes=job_outcomes,
        callback_at=callback_utc,
        notes=notes,
        source=source,
    )
    # Global key lock closes the cross-case race that a case-row lock cannot:
    # the same Idempotency-Key used concurrently on two candidates must become
    # replay/conflict, never a raw UNIQUE IntegrityError.
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock(hashtextextended(:idempotency_key, 20260728))"
        ),
        {"idempotency_key": key},
    )
    candidate_id = await db.scalar(
        select(CandidateContactCase.candidate_id).where(
            CandidateContactCase.id == case_id
        )
    )
    if candidate_id is None:
        raise ContactCaseNotFound(f"contact case {case_id} not found")
    # Shared lock order across ensure/intake and attempts: Candidate → Case.
    candidate = await db.scalar(
        select(Candidate).where(Candidate.id == candidate_id).with_for_update()
    )
    # populate_existing jest tu obowiązkowe: endpoint ładuje sprawę BEZ blokady
    # (identity mapa), a sesja nie wygasza obiektów (expire_on_commit=False).
    # Bez tego select FOR UPDATE bierze lock, ale oddaje instancję z pamięci
    # nietkniętą — i guardy niżej (version/owner/state) porównują stan sprzed
    # blokady. To nie jest rzadki wyścig: request blokuje się na locku
    # Candidate wyżej, czyli czeka dokładnie na transakcję, która podbija
    # version. Bez odświeżenia expected_version jest no-opem.
    case = await db.scalar(
        select(CandidateContactCase)
        .where(CandidateContactCase.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise ContactCaseNotFound(f"contact case {case_id} not found")
    existing_call = await db.scalar(
        select(Call).where(Call.contact_idempotency_key == key)
    )
    if existing_call is not None:
        if existing_call.contact_request_hash != fingerprint:
            raise ContactIdempotencyConflict(
                "Idempotency-Key was already used for a different attempt payload"
            )
        if existing_call.contact_case_id != case.id:
            raise ContactIdempotencyConflict(
                "Idempotency-Key belongs to a different contact case"
            )
        return AttemptResult(case=case, call=existing_call, replayed=True)
    if case.version != expected_version:
        raise ContactCaseVersionConflict(expected=expected_version, actual=case.version)
    if not allow_non_owner and case.owner_user_id != actor_user_id:
        raise ContactCaseOwnershipError(
            f"user {actor_user_id} is not owner of contact case {case_id}"
        )
    if case.state not in {
        CandidateContactState.queued.value,
        CandidateContactState.callback_due.value,
    }:
        raise CandidateContactError(
            "attempt can be logged only for queued or callback_due cases"
        )

    open_opportunities = (
        (
            await db.execute(
                select(CandidateContactOpportunity)
                .where(
                    CandidateContactOpportunity.case_id == case.id,
                    CandidateContactOpportunity.closed_at.is_(None),
                )
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    open_by_job = {
        opportunity.job_id: opportunity for opportunity in open_opportunities
    }
    if normalised_outcome in {
        CandidateContactOutcome.connected.value,
        CandidateContactOutcome.callback_requested.value,
    } and set(job_outcomes) != set(open_by_job):
        missing = sorted(set(open_by_job) - set(job_outcomes))
        extra = sorted(set(job_outcomes) - set(open_by_job))
        raise CandidateContactError(
            f"conversation requires exactly one outcome per open job; "
            f"missing={missing}, extra={extra}"
        )
    if (
        normalised_outcome == CandidateContactOutcome.callback_requested.value
        and open_by_job
        and all(
            value == CandidateContactOpportunityOutcome.not_interested.value
            for value in job_outcomes.values()
        )
    ):
        raise CandidateContactError(
            "callback_requested is inconsistent when every job is not_interested"
        )

    held_owner_id = case.owner_user_id
    held_queue_slot = case.queue_slot
    call_status = {
        CandidateContactOutcome.connected.value: CallStatus.completed,
        CandidateContactOutcome.callback_requested.value: CallStatus.completed,
        CandidateContactOutcome.no_answer.value: CallStatus.missed,
        CandidateContactOutcome.wrong_number.value: CallStatus.failed,
        CandidateContactOutcome.do_not_contact.value: CallStatus.completed,
    }[normalised_outcome]
    call = Call(
        candidate_id=case.candidate_id,
        user_id=actor_user_id,
        contact_case_id=case.id,
        direction=CallDirection.outbound,
        status=call_status,
        started_at=now,
        summary=notes,
        contact_outcome=normalised_outcome,
        contact_source=source[:32],
        contact_idempotency_key=key,
        contact_request_hash=fingerprint,
        callback_at=callback_utc,
    )
    db.add(call)
    await db.flush()

    if candidate is not None and (
        candidate.last_contacted_at is None or candidate.last_contacted_at < now
    ):
        candidate.last_contacted_at = now

    old_state = case.state
    case.last_attempt_at = now
    for job_id, job_outcome in job_outcomes.items():
        opportunity = open_by_job[job_id]
        opportunity.outcome = job_outcome
        if job_outcome != CandidateContactOpportunityOutcome.not_presented.value:
            opportunity.presented_at = now
        if job_outcome == CandidateContactOpportunityOutcome.not_interested.value:
            _set_local_close_fence(opportunity, occurred_at=now)
            opportunity.closed_at = now
            opportunity.closed_reason = "not_interested"
        _event(
            db,
            case,
            CandidateContactEventType.opportunity_outcome_recorded,
            occurred_at=now,
            actor_user_id=actor_user_id,
            opportunity=opportunity,
            call_id=call.id,
            from_state=old_state,
            details={"outcome": job_outcome},
            idempotency_key=_event_attempt_key(key, f"job:{job_id}"),
        )

    if normalised_outcome == CandidateContactOutcome.no_answer.value:
        case.attempt_count += 1
        if case.attempt_count >= 2:
            old_owner_id = case.owner_user_id
            case.previous_owner_user_id = old_owner_id
            case.owner_user_id = None
            case.queue_slot = None
            case.cooldown_until = now + timedelta(hours=72)
            case.due_at = case.cooldown_until
            case.state = CandidateContactState.cooldown.value
            _event(
                db,
                case,
                CandidateContactEventType.cooldown_started,
                occurred_at=now,
                actor_user_id=actor_user_id,
                call_id=call.id,
                from_state=old_state,
                to_state=case.state,
                details={
                    "previous_owner_user_id": old_owner_id,
                    "cooldown_until": case.cooldown_until.isoformat(),
                },
            )
        else:
            case.state = CandidateContactState.queued.value
            case.due_at = next_business_day_at(now, hour=10)
    elif normalised_outcome == CandidateContactOutcome.wrong_number.value:
        case.blocked_phone_value = candidate.phone if candidate is not None else None
        case.queue_slot = None
        case.due_at = None
        case.state = CandidateContactState.blocked_no_phone.value
        _event(
            db,
            case,
            CandidateContactEventType.phone_blocked,
            occurred_at=now,
            actor_user_id=actor_user_id,
            call_id=call.id,
            from_state=old_state,
            to_state=case.state,
            details={"phone_value_present": bool(case.blocked_phone_value)},
        )
    elif normalised_outcome == CandidateContactOutcome.do_not_contact.value:
        case.previous_owner_user_id = case.owner_user_id
        case.owner_user_id = None
        case.queue_slot = None
        case.due_at = None
        case.cooldown_until = None
        case.completed_at = now
        case.state = CandidateContactState.suppressed.value
        _event(
            db,
            case,
            CandidateContactEventType.suppressed,
            occurred_at=now,
            actor_user_id=actor_user_id,
            call_id=call.id,
            from_state=old_state,
            to_state=case.state,
        )
    else:
        case.attempt_count = 0
        case.due_at = callback_utc
        await db.flush()
        await _recompute_case_after_opportunities(
            db,
            case,
            occurred_at=now,
            actor_user_id=actor_user_id,
        )
        if normalised_outcome == CandidateContactOutcome.callback_requested.value:
            # Explicit callback is authoritative even when all jobs are
            # interested: the caller promised another phone call before
            # handoff. Restore the slot released by generic recompute.
            case.owner_user_id = held_owner_id
            case.queue_slot = held_queue_slot
            case.completed_at = None
            case.state = CandidateContactState.callback_due.value
            case.due_at = callback_utc
        elif case.state == CandidateContactState.callback_due.value:
            case.due_at = callback_utc

    case.version += 1
    _event(
        db,
        case,
        CandidateContactEventType.attempt_logged,
        occurred_at=now,
        actor_user_id=actor_user_id,
        call_id=call.id,
        from_state=old_state,
        to_state=case.state,
        details={
            "outcome": normalised_outcome,
            "callback_at": callback_utc.isoformat() if callback_utc else None,
            "attempt_count": case.attempt_count,
        },
        idempotency_key=_event_attempt_key(key),
    )
    if case.state == CandidateContactState.completed.value and old_state != case.state:
        _event(
            db,
            case,
            CandidateContactEventType.case_completed,
            occurred_at=now,
            actor_user_id=actor_user_id,
            call_id=call.id,
            from_state=old_state,
            to_state=case.state,
        )
    await db.flush()
    return AttemptResult(case=case, call=call)


async def reassign_contact_case(
    db: AsyncSession,
    *,
    case_id: int,
    actor_user_id: Optional[int],
    reason: str,
    expected_version: Optional[int] = None,
    target_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
    exclude_owner_ids: Iterable[int] = (),
    force_fresh_due_at: bool = False,
) -> CandidateContactCase:
    """Audited manual/worker reassignment with the same 20-slot fence."""

    now = _as_utc(occurred_at)
    # Jak w record_contact_attempt: endpoint preloaduje sprawę bez blokady,
    # więc bez populate_existing guardy version/state czytają stan sprzed locka.
    case = await db.scalar(
        select(CandidateContactCase)
        .where(CandidateContactCase.id == case_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise ContactCaseNotFound(f"contact case {case_id} not found")
    if expected_version is not None and case.version != expected_version:
        raise ContactCaseVersionConflict(expected=expected_version, actual=case.version)
    if case.state not in {
        CandidateContactState.unassigned.value,
        CandidateContactState.awaiting_capacity.value,
        CandidateContactState.queued.value,
        CandidateContactState.callback_due.value,
        CandidateContactState.handoff_pending.value,
        CandidateContactState.blocked_no_phone.value,
    }:
        raise CandidateContactError(
            "manual reassignment is allowed only for unassigned, "
            "awaiting_capacity, queued, callback_due, handoff_pending "
            "or blocked_no_phone cases"
        )

    old_state = case.state
    old_owner_id = case.owner_user_id
    relationship_only = old_state in {
        CandidateContactState.handoff_pending.value,
        CandidateContactState.blocked_no_phone.value,
    }
    if target_user_id is not None and target_user_id == old_owner_id:
        raise CandidateContactError("target user is already the contact owner")
    if relationship_only:
        case.previous_owner_user_id = old_owner_id
        case.owner_user_id = None
        case.queue_slot = None
        case.assigned_at = None
        if target_user_id is not None:
            _, eligible = await _eligible_users(db, case)
            if target_user_id not in {user.id for user in eligible}:
                raise CandidateContactError(
                    "target user is not an active operational member of a linked job"
                )
            case.owner_user_id = target_user_id
            case.assigned_at = now
        else:
            exclusions = {
                *[int(value) for value in exclude_owner_ids if value is not None],
                *([old_owner_id] if old_owner_id is not None else []),
            }
            await _assign_handoff_owner(
                db,
                case,
                occurred_at=now,
                exclude_owner_ids=exclusions,
            )
        case.version += 1
        reassigned = (
            case.owner_user_id is not None and case.owner_user_id != old_owner_id
        )
        _event(
            db,
            case,
            (
                CandidateContactEventType.reassigned
                if reassigned
                else CandidateContactEventType.awaiting_capacity
            ),
            occurred_at=now,
            actor_user_id=actor_user_id,
            from_state=old_state,
            to_state=case.state,
            details={
                "reason": reason,
                "old_owner_user_id": old_owner_id,
                "new_owner_user_id": case.owner_user_id,
                "queue_slot": None,
                "relationship_only": True,
            },
        )
        await db.flush()
        return case

    target_queue_state = (
        CandidateContactState.callback_due.value
        if old_state == CandidateContactState.callback_due.value
        else CandidateContactState.queued.value
    )
    preserved_due_at = (
        case.due_at
        if not force_fresh_due_at
        and old_state == CandidateContactState.callback_due.value
        and case.due_at is not None
        and _as_utc(case.due_at) > now
        else None
    )
    case.previous_owner_user_id = old_owner_id
    case.owner_user_id = None
    case.queue_slot = None
    case.assigned_at = None
    case.cooldown_until = None
    # Slot allocation flushes pending state before reading capacity. Keep this
    # row valid because queued/callback_due rows must always own a slot.
    case.state = CandidateContactState.unassigned.value
    case.attempt_count = 0
    case.cycle += 1
    due_at = preserved_due_at or initial_contact_due_at(now)

    if target_user_id is not None:
        _, eligible = await _eligible_users(db, case)
        if target_user_id not in {user.id for user in eligible}:
            raise CandidateContactError(
                "target user is not an active operational member of a linked job"
            )
        slot = await _claim_slot(db, user_id=target_user_id)
        if slot is None:
            raise ContactCapacityError(f"user {target_user_id} has no free queue slot")
        case.owner_user_id = target_user_id
        case.queue_slot = slot
        case.assigned_at = now
        case.due_at = due_at
        case.state = target_queue_state
    else:
        exclusions = {
            *[int(value) for value in exclude_owner_ids if value is not None],
            *([old_owner_id] if old_owner_id is not None else []),
        }
        await _assign_best_owner(
            db,
            case,
            due_at=due_at,
            occurred_at=now,
            exclude_owner_ids=exclusions,
            queue_state=target_queue_state,
        )

    case.version += 1
    reassigned = case.owner_user_id is not None and case.owner_user_id != old_owner_id
    _event(
        db,
        case,
        (
            CandidateContactEventType.reassigned
            if reassigned
            else CandidateContactEventType.awaiting_capacity
        ),
        occurred_at=now,
        actor_user_id=actor_user_id,
        from_state=old_state,
        to_state=case.state,
        details={
            "reason": reason,
            "old_owner_user_id": old_owner_id,
            "new_owner_user_id": case.owner_user_id,
            "queue_slot": case.queue_slot,
            "preserved_due_at": (
                preserved_due_at.isoformat() if preserved_due_at is not None else None
            ),
        },
    )
    await db.flush()
    return case


async def sync_calendar_handoff(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    event_id: int,
    scheduled: bool,
    actor_user_id: Optional[int] = None,
    occurred_at: Optional[datetime] = None,
) -> Optional[CandidateContactCase]:
    """Apply scheduling/cancellation of one screening/interview opportunity."""

    now = _as_utc(occurred_at)
    case = await db.scalar(
        select(CandidateContactCase)
        .where(CandidateContactCase.candidate_id == candidate_id)
        .with_for_update()
    )
    if case is None:
        return None
    opportunity = await db.scalar(
        select(CandidateContactOpportunity)
        .where(
            CandidateContactOpportunity.candidate_id == candidate_id,
            CandidateContactOpportunity.job_id == job_id,
            CandidateContactOpportunity.closed_at.is_(None),
        )
        .with_for_update()
    )
    if opportunity is None:
        return case
    if scheduled and opportunity.meeting_event_id == event_id:
        return case
    if not scheduled and opportunity.meeting_event_id != event_id:
        return case

    old_state = case.state
    replacement_event_id: Optional[int] = None
    if scheduled:
        opportunity.outcome = CandidateContactOpportunityOutcome.interested.value
        opportunity.presented_at = opportunity.presented_at or now
        opportunity.meeting_event_id = event_id
        opportunity.meeting_scheduled_at = now
        event_type = CandidateContactEventType.handoff_scheduled
    else:
        replacement_event_id = await db.scalar(
            select(CalendarEvent.id)
            .where(
                CalendarEvent.candidate_id == candidate_id,
                CalendarEvent.job_id == job_id,
                CalendarEvent.event_type.in_(
                    [EventType.screening, EventType.interview]
                ),
                CalendarEvent.status.in_(
                    (EventStatus.scheduled, EventStatus.completed)
                ),
                CalendarEvent.id != event_id,
            )
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
            .limit(1)
        )
        opportunity.meeting_event_id = replacement_event_id
        if replacement_event_id is None:
            opportunity.meeting_scheduled_at = None
        event_type = CandidateContactEventType.handoff_cancelled
    await db.flush()
    await _recompute_case_after_opportunities(
        db,
        case,
        occurred_at=now,
        actor_user_id=actor_user_id,
    )
    case.version += 1
    _event(
        db,
        case,
        event_type,
        occurred_at=now,
        actor_user_id=actor_user_id,
        opportunity=opportunity,
        from_state=old_state,
        to_state=case.state,
        details={
            "calendar_event_id": event_id,
            "replacement_calendar_event_id": (
                replacement_event_id if not scheduled else None
            ),
        },
    )
    if case.state == CandidateContactState.completed.value and old_state != case.state:
        _event(
            db,
            case,
            CandidateContactEventType.case_completed,
            occurred_at=now,
            actor_user_id=actor_user_id,
            from_state=old_state,
            to_state=case.state,
        )
    await db.flush()
    return case


def _is_eod_overdue(case: CandidateContactCase, now: datetime) -> bool:
    if case.due_at is None or case.due_at > now:
        return False
    due_local = _local(case.due_at)
    turnover_day = due_local.date()
    while turnover_day.weekday() >= 5:
        turnover_day = _next_weekday(turnover_day)
    turnover_at = datetime.combine(
        turnover_day,
        time(18, 0),
        tzinfo=WARSAW,
    )
    if (
        case.state == CandidateContactState.callback_due.value
        and due_local > turnover_at
    ):
        # A callback explicitly promised after 18:00 cannot become overdue at
        # the instant it is due merely because that day's turnover has passed.
        turnover_day = _next_weekday(turnover_day)
        turnover_at = datetime.combine(
            turnover_day,
            time(18, 0),
            tzinfo=WARSAW,
        )
    if (
        case.state == CandidateContactState.callback_due.value
        and case.assigned_at is not None
        and _as_utc(case.assigned_at) >= turnover_at.astimezone(timezone.utc)
    ):
        assigned_local = _local(case.assigned_at)
        reassignment_day = assigned_local.date()
        while reassignment_day.weekday() >= 5:
            reassignment_day = _next_weekday(reassignment_day)
        reassignment_turnover = datetime.combine(
            reassignment_day,
            time(18, 0),
            tzinfo=WARSAW,
        )
        if assigned_local >= reassignment_turnover:
            reassignment_turnover = datetime.combine(
                _next_weekday(reassignment_day),
                time(18, 0),
                tzinfo=WARSAW,
            )
        turnover_at = max(turnover_at, reassignment_turnover)
    # Absolute comparison catches up after downtime: a Friday turnover remains
    # due on Saturday and on Monday morning, not only inside Friday's window.
    return _as_utc(now) >= turnover_at.astimezone(timezone.utc)


async def process_contact_cases(
    db: AsyncSession,
    *,
    now: Optional[datetime] = None,
    limit: int = 100,
) -> ProcessingStats:
    """Claim and process a restart-safe bounded batch using SKIP LOCKED."""

    tick = _as_utc(now)
    retry_touch_at = datetime.now(timezone.utc)
    stats = ProcessingStats()
    bounded_limit = max(1, min(int(limit), 500))
    retry_states = (
        CandidateContactState.unassigned.value,
        CandidateContactState.awaiting_capacity.value,
        CandidateContactState.blocked_no_phone.value,
    )
    actionable_states = (
        CandidateContactState.queued.value,
        CandidateContactState.callback_due.value,
    )
    owner_managed_states = (
        CandidateContactState.queued.value,
        CandidateContactState.callback_due.value,
        CandidateContactState.handoff_pending.value,
    )
    owner_access_exists = exists(
        select(1)
        .select_from(CandidateContactOpportunity)
        .join(Job, Job.id == CandidateContactOpportunity.job_id)
        .outerjoin(
            JobCollaborator,
            and_(
                JobCollaborator.job_id == Job.id,
                JobCollaborator.user_id == User.id,
                JobCollaborator.removed_from_auto_cc.is_(False),
            ),
        )
        .where(
            CandidateContactOpportunity.case_id == CandidateContactCase.id,
            CandidateContactOpportunity.closed_at.is_(None),
            Job.status != JobStatus.closed,
            or_(
                Job.recruiter_id == User.id,
                Job.tac_id == User.id,
                Job.delivery_lead_id == User.id,
                JobCollaborator.user_id == User.id,
            ),
        )
    ).correlate(CandidateContactCase, User)
    eligible_owner_exists = exists(
        select(1)
        .select_from(User)
        .where(
            User.id == CandidateContactCase.owner_user_id,
            User.is_active.is_(True),
            or_(
                User.role.in_(OPERATIONAL_ROLES),
                *(User.roles.contains([role.value]) for role in OPERATIONAL_ROLES),
            ),
            owner_access_exists,
        )
    ).correlate(CandidateContactCase)
    invalid_owner = and_(
        or_(
            CandidateContactCase.state.in_(owner_managed_states),
            and_(
                CandidateContactCase.state.in_(
                    (
                        CandidateContactState.unassigned.value,
                        CandidateContactState.awaiting_capacity.value,
                    )
                ),
                CandidateContactCase.owner_user_id.is_not(None),
            ),
        ),
        ~eligible_owner_exists,
    )
    phone_missing = and_(
        CandidateContactCase.state.in_(actionable_states),
        exists(
            select(1)
            .select_from(Candidate)
            .where(
                Candidate.id == CandidateContactCase.candidate_id,
                func.btrim(func.coalesce(Candidate.phone, "")) == "",
            )
        ).correlate(CandidateContactCase),
    )
    safety_condition = or_(phone_missing, invalid_owner)
    state_priority = sql_case(
        (
            CandidateContactCase.state == CandidateContactState.cooldown.value,
            0,
        ),
        (CandidateContactCase.state.in_(actionable_states), 1),
        else_=2,
    )
    # Actionable/cooldown work remains ordered by its business deadline. Retry
    # states use their last scan time so a permanently blocked first page
    # cannot starve rows beyond the bounded batch.
    fair_order_at = sql_case(
        (
            CandidateContactCase.state.in_(retry_states),
            CandidateContactCase.updated_at,
        ),
        else_=CandidateContactCase.due_at,
    )
    safety_cases = (
        (
            await db.execute(
                select(CandidateContactCase)
                .where(safety_condition)
                .order_by(
                    CandidateContactCase.updated_at.asc(),
                    CandidateContactCase.id.asc(),
                )
                .limit(bounded_limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    cases = (
        (
            await db.execute(
                select(CandidateContactCase)
                .where(
                    or_(
                        and_(
                            CandidateContactCase.state.in_(retry_states),
                            ~safety_condition,
                        ),
                        (
                            CandidateContactCase.state
                            == CandidateContactState.cooldown.value
                        )
                        & (CandidateContactCase.cooldown_until <= tick),
                        and_(
                            CandidateContactCase.state.in_(actionable_states),
                            CandidateContactCase.due_at <= tick,
                            ~safety_condition,
                        ),
                    )
                )
                .order_by(
                    state_priority,
                    fair_order_at.asc().nullslast(),
                    CandidateContactCase.id.asc(),
                )
                .limit(bounded_limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    work = [*safety_cases, *cases]
    stats.scanned = len(work)

    for case in work:
        if case.state in actionable_states:
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == case.candidate_id)
            )
            if candidate is None or not (candidate.phone or "").strip():
                old_state = case.state
                case.blocked_phone_value = candidate.phone if candidate else None
                case.queue_slot = None
                case.due_at = None
                case.state = CandidateContactState.blocked_no_phone.value
                case.version += 1
                _event(
                    db,
                    case,
                    CandidateContactEventType.phone_blocked,
                    occurred_at=tick,
                    from_state=old_state,
                    to_state=case.state,
                    details={
                        "reason": "phone_cleared",
                        "owner_user_id": case.owner_user_id,
                        "phone_value_present": False,
                    },
                )
                continue

        owner_needs_validation = case.state in owner_managed_states or (
            case.state
            in {
                CandidateContactState.unassigned.value,
                CandidateContactState.awaiting_capacity.value,
            }
            and case.owner_user_id is not None
        )
        if owner_needs_validation and not await _current_owner_is_eligible(db, case):
            old_state = case.state
            old_owner_id = case.owner_user_id
            if case.state == CandidateContactState.handoff_pending.value:
                before = (
                    case.owner_user_id,
                    case.previous_owner_user_id,
                    case.assigned_at,
                )
                if old_owner_id is not None:
                    case.previous_owner_user_id = old_owner_id
                case.owner_user_id = None
                case.queue_slot = None
                case.assigned_at = None
                await _assign_handoff_owner(db, case, occurred_at=tick)
                case.state = CandidateContactState.handoff_pending.value
                after = (
                    case.owner_user_id,
                    case.previous_owner_user_id,
                    case.assigned_at,
                )
                if after != before:
                    case.version += 1
                    if case.owner_user_id is not None:
                        stats.reassigned += 1
                    _event(
                        db,
                        case,
                        (
                            CandidateContactEventType.reassigned
                            if case.owner_user_id is not None
                            else CandidateContactEventType.awaiting_capacity
                        ),
                        occurred_at=tick,
                        from_state=old_state,
                        to_state=case.state,
                        details={
                            "reason": "invalid_handoff_owner",
                            "old_owner_user_id": old_owner_id,
                            "new_owner_user_id": case.owner_user_id,
                        },
                    )
                else:
                    case.updated_at = max(
                        retry_touch_at,
                        _as_utc(case.updated_at) + timedelta(microseconds=1),
                    )
            else:
                reassigned_case = await reassign_contact_case(
                    db,
                    case_id=case.id,
                    actor_user_id=None,
                    reason="invalid_owner",
                    occurred_at=tick,
                    exclude_owner_ids=(
                        [old_owner_id] if old_owner_id is not None else []
                    ),
                    force_fresh_due_at=True,
                )
                if reassigned_case.owner_user_id not in {None, old_owner_id}:
                    stats.reassigned += 1
            continue

        if case.state == CandidateContactState.blocked_no_phone.value:
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == case.candidate_id)
            )
            current_phone = (candidate.phone or "").strip() if candidate else ""
            if (
                not current_phone
                or current_phone == (case.blocked_phone_value or "").strip()
            ):
                case.updated_at = max(
                    retry_touch_at,
                    _as_utc(case.updated_at) + timedelta(microseconds=1),
                )
                continue
            old_state = case.state
            old_owner_id = case.owner_user_id
            case.blocked_phone_value = None
            case.attempt_count = 0
            case.cycle += 1
            restored_due_at = initial_contact_due_at(tick)
            retained_owner = False
            if await _current_owner_is_eligible(db, case):
                slot = await _claim_slot(db, user_id=old_owner_id)
                if slot is not None:
                    case.queue_slot = slot
                    case.assigned_at = tick
                    case.due_at = restored_due_at
                    case.cooldown_until = None
                    case.completed_at = None
                    case.state = CandidateContactState.queued.value
                    retained_owner = True
            if not retained_owner:
                case.previous_owner_user_id = old_owner_id
                await _assign_best_owner(
                    db,
                    case,
                    due_at=restored_due_at,
                    occurred_at=tick,
                    exclude_owner_ids=(
                        [old_owner_id] if old_owner_id is not None else []
                    ),
                )
            case.version += 1
            stats.phone_restored += 1
            if case.owner_user_id not in {None, old_owner_id}:
                stats.reassigned += 1
                _event(
                    db,
                    case,
                    CandidateContactEventType.reassigned,
                    occurred_at=tick,
                    from_state=old_state,
                    to_state=case.state,
                    details={
                        "reason": "phone_restored_owner_unavailable",
                        "old_owner_user_id": old_owner_id,
                        "new_owner_user_id": case.owner_user_id,
                    },
                )
            _event(
                db,
                case,
                CandidateContactEventType.phone_restored,
                occurred_at=tick,
                from_state=old_state,
                to_state=case.state,
                details={
                    "queue_slot": case.queue_slot,
                    "owner_user_id": case.owner_user_id,
                    "retained_owner": retained_owner,
                },
            )
            continue

        if case.state == CandidateContactState.cooldown.value:
            old_state = case.state
            excluded = (
                [case.previous_owner_user_id]
                if case.previous_owner_user_id is not None
                else []
            )
            case.attempt_count = 0
            case.cycle += 1
            case.cooldown_until = None
            await _assign_best_owner(
                db,
                case,
                due_at=initial_contact_due_at(tick),
                occurred_at=tick,
                exclude_owner_ids=excluded,
            )
            case.version += 1
            stats.cooldown_released += 1
            if case.owner_user_id is not None:
                stats.reassigned += 1
            _event(
                db,
                case,
                CandidateContactEventType.cooldown_ended,
                occurred_at=tick,
                from_state=old_state,
                to_state=case.state,
                details={
                    "excluded_owner_user_ids": excluded,
                    "new_owner_user_id": case.owner_user_id,
                },
            )
            continue

        if case.state in {
            CandidateContactState.unassigned.value,
            CandidateContactState.awaiting_capacity.value,
        }:
            old_state = case.state
            before = (
                case.state,
                case.owner_user_id,
                case.queue_slot,
                case.due_at,
                case.primary_job_id,
                case.assigned_at,
            )
            fresh_due_at = initial_contact_due_at(tick)
            queue_state = await _pending_queue_state(db, case)
            assignment_due_at = (
                case.due_at
                if queue_state == CandidateContactState.callback_due.value
                and case.due_at is not None
                else (
                    max(case.due_at, fresh_due_at)
                    if case.due_at is not None
                    else fresh_due_at
                )
            )
            assigned = False
            if case.owner_user_id is not None:
                slot = await _claim_slot(db, user_id=case.owner_user_id)
                if slot is not None:
                    case.queue_slot = slot
                    case.assigned_at = tick
                    case.due_at = assignment_due_at
                    case.cooldown_until = None
                    case.completed_at = None
                    case.state = queue_state
                    assigned = True
                else:
                    case.queue_slot = None
                    case.due_at = assignment_due_at
                    case.state = CandidateContactState.awaiting_capacity.value
            else:
                assigned = await _assign_best_owner(
                    db,
                    case,
                    due_at=assignment_due_at,
                    occurred_at=tick,
                    exclude_owner_ids=(
                        [case.previous_owner_user_id]
                        if case.previous_owner_user_id is not None
                        else []
                    ),
                    queue_state=queue_state,
                )
            after = (
                case.state,
                case.owner_user_id,
                case.queue_slot,
                case.due_at,
                case.primary_job_id,
                case.assigned_at,
            )
            if after != before:
                case.version += 1
                if assigned:
                    stats.assigned_from_waiting += 1
                _event(
                    db,
                    case,
                    (
                        CandidateContactEventType.assigned
                        if assigned
                        else CandidateContactEventType.awaiting_capacity
                    ),
                    occurred_at=tick,
                    from_state=old_state,
                    to_state=case.state,
                    details={
                        "owner_user_id": case.owner_user_id,
                        "queue_slot": case.queue_slot,
                        "previous_due_at": (
                            before[3].isoformat() if before[3] is not None else None
                        ),
                        "reason": (
                            None if assigned else "no_eligible_owner_or_capacity"
                        ),
                    },
                )
            else:
                case.updated_at = max(
                    retry_touch_at,
                    _as_utc(case.updated_at) + timedelta(microseconds=1),
                )
            continue

        if case.state in {
            CandidateContactState.queued.value,
            CandidateContactState.callback_due.value,
        } and _is_eod_overdue(case, tick):
            reassigned_case = await reassign_contact_case(
                db,
                case_id=case.id,
                actor_user_id=None,
                reason="eod_overdue",
                occurred_at=tick,
                exclude_owner_ids=(
                    [case.owner_user_id] if case.owner_user_id is not None else []
                ),
            )
            if reassigned_case.owner_user_id is not None:
                stats.reassigned += 1

    await db.flush()
    return stats


__all__ = [
    "AttemptResult",
    "CandidateContactError",
    "ContactCapacityError",
    "ContactCaseNotFound",
    "ContactCaseOwnershipError",
    "ContactCaseVersionConflict",
    "ContactConflict",
    "ContactIdempotencyConflict",
    "ContactOpportunityNotFound",
    "ContactValidationError",
    "ProcessingStats",
    "ensure_contact_opportunity",
    "close_contact_opportunity",
    "close_job_contact_opportunities",
    "initial_contact_due_at",
    "next_business_day_at",
    "process_contact_cases",
    "reassign_contact_case",
    "record_contact_attempt",
    "sync_calendar_handoff",
]
