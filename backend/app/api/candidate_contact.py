"""Candidate-global first-contact queue API.

Pipeline rows stay job-scoped.  This router exposes one candidate-global case
while projecting only opportunities the caller may see, preserving the
existing recruitment membership boundary for candidate PII.
"""

from __future__ import annotations

import base64
import json
from datetime import datetime, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import and_, case as sa_case, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import OperationalUser, require_roles
from app.api.recruitment_access import job_scope_clause
from app.core.config import settings
from app.core.database import get_db
from app.core.scheduling import local_day_bounds
from app.models.candidate import Candidate
from app.models.call import Call
from app.models.candidate_contact import (
    CandidateContactCase,
    CandidateContactEvent,
    CandidateContactOpportunity,
    CandidateContactTraffitCursor,
    CandidateContactTraffitLedger,
)
from app.models.client import Client
from app.models.job import Job
from app.models.user import User, UserRole
from app.schemas.candidate_contact import ContactAttemptCreate, ContactReassignRequest
from app.services.candidate_contact import (
    CandidateContactError,
    ContactCapacityError,
    ContactContentionError,
    ContactCaseNotFound,
    ContactCaseOwnershipError,
    ContactCaseVersionConflict,
    ContactIdempotencyConflict,
    ContactOpportunityNotFound,
    reassign_contact_case,
    record_contact_attempt,
)

from app.api.section_access import SOURCING_SECTION_DEPENDENCIES

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

ContactCaller = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.recruiter,
            UserRole.sourcer,
            UserRole.tac,
            UserRole.talent_community_manager,
        )
    ),
]
ContactOversight = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.head_of_recruitment)),
]

_ACTIONABLE_STATES = ("queued", "callback_due")
_OWNER_QUEUE_STATES = (
    "queued",
    "callback_due",
    "handoff_pending",
    "blocked_no_phone",
    "awaiting_capacity",
)
_OVERSIGHT_EXCEPTION_BASE_STATES = (
    "unassigned",
    "awaiting_capacity",
    "blocked_no_phone",
)
_OVERSIGHT_REASSIGNMENT_EVENTS = ("reassigned", "cooldown_ended")
_CAPACITY = 20
_TRAFFIT_STREAM = "recruitment_history_contact"


class ContactPersonDTO(BaseModel):
    id: int
    name: Optional[str] = None
    lastname: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    current_role: Optional[str] = None


class ContactOwnerDTO(BaseModel):
    id: int
    name: str


class ContactOpportunityDTO(BaseModel):
    id: int
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    outcome: Optional[str] = None
    meeting_status: Optional[str] = None
    owner: Optional[ContactOwnerDTO] = None


class ContactCaseDTO(BaseModel):
    id: int
    status: str
    owner: Optional[ContactOwnerDTO] = None
    due_at: Optional[datetime] = None
    callback_at: Optional[datetime] = None
    attempts_in_cycle: int
    version: int
    candidate: ContactPersonDTO
    opportunities: list[ContactOpportunityDTO] = Field(default_factory=list)


class ContactQueueUtilizationDTO(BaseModel):
    used: int
    capacity: int = _CAPACITY


class ContactQueueResponseDTO(BaseModel):
    items: list[ContactCaseDTO]
    utilization: ContactQueueUtilizationDTO
    next_cursor: Optional[str] = None


class ContactFeatureStatusDTO(BaseModel):
    enabled: bool
    assignment_enabled: bool
    traffit_intake_enabled: bool


class ContactOversightCountersDTO(BaseModel):
    overdue: int = 0
    unassigned: int = 0
    awaiting_capacity: int = 0
    blocked_no_phone: int = 0
    ownerless_handoff: int = 0
    reassigned_today: int = 0
    traffit_lag_seconds: Optional[int] = None
    traffit_status: Optional[str] = None
    traffit_last_error: Optional[str] = None
    traffit_exception_count: int = 0


class ContactOversightResponseDTO(BaseModel):
    counters: ContactOversightCountersDTO
    items: list[ContactCaseDTO]
    next_cursor: Optional[str] = None


def _disabled_queue() -> ContactQueueResponseDTO:
    return ContactQueueResponseDTO(
        items=[],
        utilization=ContactQueueUtilizationDTO(used=0),
    )


def _queue_priority_expression():
    return sa_case(
        (CandidateContactCase.state.in_(_ACTIONABLE_STATES), 0),
        (CandidateContactCase.state == "blocked_no_phone", 1),
        (CandidateContactCase.state == "awaiting_capacity", 2),
        (CandidateContactCase.state == "handoff_pending", 3),
        else_=4,
    )


def _queue_priority_value(contact_case: CandidateContactCase) -> int:
    if contact_case.state in _ACTIONABLE_STATES:
        return 0
    return {
        "blocked_no_phone": 1,
        "awaiting_capacity": 2,
        "handoff_pending": 3,
    }.get(contact_case.state, 4)


def _queue_sort_at(contact_case: CandidateContactCase) -> datetime:
    value = contact_case.due_at or contact_case.created_at
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _encode_cursor(contact_case: CandidateContactCase) -> str:
    raw = json.dumps(
        {
            "id": contact_case.id,
            "priority": _queue_priority_value(contact_case),
            "sort_at": _queue_sort_at(contact_case).isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(value: str | None) -> tuple[int, datetime, int] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        priority = int(payload["priority"])
        sort_at = datetime.fromisoformat(payload["sort_at"])
        case_id = int(payload["id"])
        if priority < 0 or priority > 4 or case_id < 1:
            raise ValueError
        if sort_at.tzinfo is None:
            sort_at = sort_at.replace(tzinfo=timezone.utc)
        return priority, sort_at.astimezone(timezone.utc), case_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Invalid cursor")


def _oversight_exception_clause(now: datetime):
    return or_(
        CandidateContactCase.state.in_(_OVERSIGHT_EXCEPTION_BASE_STATES),
        and_(
            CandidateContactCase.state == "handoff_pending",
            CandidateContactCase.owner_user_id.is_(None),
        ),
        and_(
            CandidateContactCase.state.in_(_ACTIONABLE_STATES),
            CandidateContactCase.due_at < now,
        ),
        and_(
            CandidateContactCase.state == "cooldown",
            CandidateContactCase.cooldown_until <= now,
        ),
    )


def _oversight_priority_expression():
    return sa_case(
        (CandidateContactCase.state.in_(_ACTIONABLE_STATES), 0),
        (CandidateContactCase.state == "blocked_no_phone", 1),
        (CandidateContactCase.state == "unassigned", 2),
        (CandidateContactCase.state == "awaiting_capacity", 3),
        (
            and_(
                CandidateContactCase.state == "handoff_pending",
                CandidateContactCase.owner_user_id.is_(None),
            ),
            4,
        ),
        (CandidateContactCase.state == "cooldown", 5),
        else_=6,
    )


def _oversight_priority_value(contact_case: CandidateContactCase) -> int:
    if contact_case.state in _ACTIONABLE_STATES:
        return 0
    if contact_case.state == "handoff_pending" and contact_case.owner_user_id is None:
        return 4
    return {
        "blocked_no_phone": 1,
        "unassigned": 2,
        "awaiting_capacity": 3,
        "cooldown": 5,
    }.get(contact_case.state, 6)


def _oversight_sort_at(contact_case: CandidateContactCase) -> datetime:
    value = (
        contact_case.due_at or contact_case.cooldown_until or contact_case.created_at
    )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _encode_oversight_cursor(contact_case: CandidateContactCase) -> str:
    raw = json.dumps(
        {
            "id": contact_case.id,
            "priority": _oversight_priority_value(contact_case),
            "sort_at": _oversight_sort_at(contact_case).isoformat(),
        },
        separators=(",", ":"),
    ).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_oversight_cursor(
    value: str | None,
) -> tuple[int, datetime, int] | None:
    if not value:
        return None
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded).decode())
        priority = int(payload["priority"])
        sort_at = datetime.fromisoformat(payload["sort_at"])
        case_id = int(payload["id"])
        if priority < 0 or priority > 6 or case_id < 1:
            raise ValueError
        if sort_at.tzinfo is None:
            sort_at = sort_at.replace(tzinfo=timezone.utc)
        return priority, sort_at.astimezone(timezone.utc), case_id
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        raise HTTPException(status_code=422, detail="Invalid cursor")


def _reassignment_event_clause():
    return or_(
        CandidateContactEvent.event_type == _OVERSIGHT_REASSIGNMENT_EVENTS[0],
        and_(
            CandidateContactEvent.event_type == _OVERSIGHT_REASSIGNMENT_EVENTS[1],
            CandidateContactEvent.details["new_owner_user_id"].astext.is_not(None),
        ),
    )


def _accessible_case_clause(user: User, *, include_closed: bool = False):
    conditions = [
        CandidateContactOpportunity.case_id == CandidateContactCase.id,
        job_scope_clause(user, CandidateContactOpportunity.job_id),
    ]
    if not include_closed:
        conditions.append(CandidateContactOpportunity.closed_at.is_(None))
    return exists(
        select(CandidateContactOpportunity.id).where(
            *conditions,
        )
    )


async def _load_case_dtos(
    db: AsyncSession,
    cases: list[CandidateContactCase],
    *,
    viewer: User,
    oversight: bool = False,
) -> list[ContactCaseDTO]:
    if not cases:
        return []
    case_ids = [case.id for case in cases]
    candidate_ids = [case.candidate_id for case in cases]
    owner_ids = {case.owner_user_id for case in cases if case.owner_user_id is not None}
    candidates = {
        row.id: row
        for row in (
            (await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids))))
            .scalars()
            .all()
        )
    }
    owners = (
        {
            row.id: row
            for row in (
                (await db.execute(select(User).where(User.id.in_(owner_ids))))
                .scalars()
                .all()
            )
        }
        if owner_ids
        else {}
    )

    recruitment_owner = aliased(User)
    opportunity_query = (
        select(
            CandidateContactOpportunity,
            Job.title,
            Client.name,
            recruitment_owner.id,
            recruitment_owner.name,
        )
        .join(Job, Job.id == CandidateContactOpportunity.job_id)
        .outerjoin(Client, Client.id == Job.client_id)
        .outerjoin(recruitment_owner, recruitment_owner.id == Job.recruiter_id)
        .where(
            CandidateContactOpportunity.case_id.in_(case_ids),
            CandidateContactOpportunity.closed_at.is_(None),
        )
        .order_by(
            CandidateContactOpportunity.linked_at,
            CandidateContactOpportunity.id,
        )
    )
    if not oversight:
        owner_case_ids = {case.id for case in cases if case.owner_user_id == viewer.id}
        visible_opportunities = job_scope_clause(
            viewer, CandidateContactOpportunity.job_id
        )
        if owner_case_ids:
            # The global contact owner must see every open offer they are
            # expected to present and record an outcome for.  Other viewers
            # keep the existing recruitment-membership boundary.
            visible_opportunities = or_(
                CandidateContactOpportunity.case_id.in_(owner_case_ids),
                visible_opportunities,
            )
        opportunity_query = opportunity_query.where(visible_opportunities)
    opportunity_rows = (await db.execute(opportunity_query)).all()
    opportunities_by_case: dict[int, list[ContactOpportunityDTO]] = {
        case_id: [] for case_id in case_ids
    }
    for opportunity, title, client_name, owner_id, owner_name in opportunity_rows:
        opportunities_by_case[opportunity.case_id].append(
            ContactOpportunityDTO(
                id=opportunity.id,
                job_id=opportunity.job_id,
                job_title=title,
                client_name=client_name,
                outcome=opportunity.outcome,
                meeting_status=(
                    "scheduled" if opportunity.meeting_scheduled_at else None
                ),
                owner=(
                    ContactOwnerDTO(id=owner_id, name=owner_name)
                    if owner_id is not None and owner_name
                    else None
                ),
            )
        )

    output: list[ContactCaseDTO] = []
    for case in cases:
        candidate = candidates.get(case.candidate_id)
        # A deleted candidate cascades the case; this only covers a concurrent
        # delete between the two SELECTs.
        if candidate is None:
            continue
        owner = owners.get(case.owner_user_id)
        output.append(
            ContactCaseDTO(
                id=case.id,
                status=case.state,
                owner=(
                    ContactOwnerDTO(id=owner.id, name=owner.name)
                    if owner is not None
                    else None
                ),
                due_at=case.due_at,
                callback_at=case.due_at if case.state == "callback_due" else None,
                attempts_in_cycle=case.attempt_count,
                version=case.version,
                candidate=ContactPersonDTO(
                    id=candidate.id,
                    name=candidate.name,
                    lastname=candidate.lastname,
                    phone=candidate.phone,
                    email=candidate.email,
                    current_role=candidate.linkedin_current_title,
                ),
                opportunities=opportunities_by_case.get(case.id, []),
            )
        )
    return output


async def _single_case_dto(
    db: AsyncSession,
    case: CandidateContactCase,
    *,
    viewer: User,
    oversight: bool = False,
) -> ContactCaseDTO:
    rows = await _load_case_dtos(db, [case], viewer=viewer, oversight=oversight)
    if not rows:
        raise HTTPException(status_code=404, detail="Contact case not found")
    return rows[0]


def _translate_domain_error(exc: Exception) -> None:
    if isinstance(exc, ContactCaseNotFound):
        raise HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ContactCaseOwnershipError):
        raise HTTPException(status_code=403, detail=str(exc))
    if isinstance(
        exc,
        (
            ContactCaseVersionConflict,
            ContactIdempotencyConflict,
            ContactCapacityError,
            # Rywalizacja o wiersz właściciela jest ponawialna, więc 409 jak
            # reszta konfliktów — nie 422, które sugeruje błędne żądanie.
            ContactContentionError,
        ),
    ):
        raise HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (ContactOpportunityNotFound, CandidateContactError)):
        raise HTTPException(status_code=422, detail=str(exc))
    raise exc


@router.get("/status", response_model=ContactFeatureStatusDTO)
async def get_candidate_contact_status(
    current_user: OperationalUser,
) -> ContactFeatureStatusDTO:
    """Expose rollout state without candidate PII."""

    return ContactFeatureStatusDTO(
        enabled=settings.CANDIDATE_CONTACT_ENABLED,
        assignment_enabled=(
            settings.CANDIDATE_CONTACT_ENABLED
            and settings.CANDIDATE_CONTACT_ASSIGNMENT_ENABLED
        ),
        traffit_intake_enabled=(
            settings.CANDIDATE_CONTACT_ENABLED
            and settings.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED
        ),
    )


@router.get("/queue", response_model=ContactQueueResponseDTO)
async def get_my_contact_queue(
    current_user: ContactCaller,
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ContactQueueResponseDTO:
    if not settings.CANDIDATE_CONTACT_ENABLED:
        return _disabled_queue()
    after = _decode_cursor(cursor)
    priority_expression = _queue_priority_expression()
    sort_expression = func.coalesce(
        CandidateContactCase.due_at,
        CandidateContactCase.created_at,
    )
    query = (
        select(CandidateContactCase)
        .where(
            CandidateContactCase.owner_user_id == current_user.id,
            CandidateContactCase.state.in_(_OWNER_QUEUE_STATES),
            _accessible_case_clause(current_user),
        )
        .order_by(
            priority_expression,
            sort_expression,
            CandidateContactCase.id,
        )
        .limit(limit + 1)
    )
    if after is not None:
        after_priority, after_sort_at, after_id = after
        query = query.where(
            or_(
                priority_expression > after_priority,
                and_(
                    priority_expression == after_priority,
                    sort_expression > after_sort_at,
                ),
                and_(
                    priority_expression == after_priority,
                    sort_expression == after_sort_at,
                    CandidateContactCase.id > after_id,
                ),
            )
        )
    cases = list((await db.execute(query)).scalars().all())
    has_more = len(cases) > limit
    page = cases[:limit]
    items = await _load_case_dtos(db, page, viewer=current_user)
    used = await db.scalar(
        select(func.count(CandidateContactCase.id)).where(
            CandidateContactCase.owner_user_id == current_user.id,
            CandidateContactCase.state.in_(_ACTIONABLE_STATES),
            CandidateContactCase.queue_slot.is_not(None),
        )
    )
    return ContactQueueResponseDTO(
        items=items,
        utilization=ContactQueueUtilizationDTO(used=int(used or 0)),
        next_cursor=_encode_cursor(page[-1]) if has_more and page else None,
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=Optional[ContactCaseDTO],
)
async def get_candidate_contact_case(
    candidate_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ContactCaseDTO | None:
    if not settings.CANDIDATE_CONTACT_ENABLED:
        return None
    case = await db.scalar(
        select(CandidateContactCase).where(
            CandidateContactCase.candidate_id == candidate_id,
            _accessible_case_clause(current_user, include_closed=True),
        )
    )
    if case is None:
        return None
    oversight = current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)
    return await _single_case_dto(db, case, viewer=current_user, oversight=oversight)


@router.get("/oversight", response_model=ContactOversightResponseDTO)
async def get_contact_oversight(
    current_user: ContactOversight,
    cursor: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> ContactOversightResponseDTO:
    if not settings.CANDIDATE_CONTACT_ENABLED:
        return ContactOversightResponseDTO(
            counters=ContactOversightCountersDTO(), items=[]
        )
    now = datetime.now(timezone.utc)
    after = _decode_oversight_cursor(cursor)
    priority_expression = _oversight_priority_expression()
    sort_expression = func.coalesce(
        CandidateContactCase.due_at,
        CandidateContactCase.cooldown_until,
        CandidateContactCase.created_at,
    )
    query = (
        select(CandidateContactCase)
        .where(_oversight_exception_clause(now))
        .order_by(
            priority_expression,
            sort_expression,
            CandidateContactCase.id,
        )
        .limit(limit + 1)
    )
    if after is not None:
        after_priority, after_sort_at, after_id = after
        query = query.where(
            or_(
                priority_expression > after_priority,
                and_(
                    priority_expression == after_priority,
                    sort_expression > after_sort_at,
                ),
                and_(
                    priority_expression == after_priority,
                    sort_expression == after_sort_at,
                    CandidateContactCase.id > after_id,
                ),
            )
        )
    cases = list((await db.execute(query)).scalars().all())
    has_more = len(cases) > limit
    page = cases[:limit]
    items = await _load_case_dtos(db, page, viewer=current_user, oversight=True)

    aggregate = (
        await db.execute(
            select(
                func.count(CandidateContactCase.id)
                .filter(
                    CandidateContactCase.state.in_(_ACTIONABLE_STATES),
                    CandidateContactCase.due_at < now,
                )
                .label("overdue"),
                func.count(CandidateContactCase.id)
                .filter(CandidateContactCase.state == "unassigned")
                .label("unassigned"),
                func.count(CandidateContactCase.id)
                .filter(CandidateContactCase.state == "awaiting_capacity")
                .label("awaiting_capacity"),
                func.count(CandidateContactCase.id)
                .filter(CandidateContactCase.state == "blocked_no_phone")
                .label("blocked_no_phone"),
                func.count(CandidateContactCase.id)
                .filter(
                    CandidateContactCase.state == "handoff_pending",
                    CandidateContactCase.owner_user_id.is_(None),
                )
                .label("ownerless_handoff"),
            )
        )
    ).one()
    day = local_day_bounds(now, settings.BUSINESS_TZ)
    reassigned_today = await db.scalar(
        select(func.count(CandidateContactEvent.id)).where(
            _reassignment_event_clause(),
            CandidateContactEvent.occurred_at >= day.start_utc,
            CandidateContactEvent.occurred_at <= day.end_utc,
        )
    )
    intake_cursor = await db.get(CandidateContactTraffitCursor, _TRAFFIT_STREAM)
    intake_exception_count = await db.scalar(
        select(func.count(CandidateContactTraffitLedger.id)).where(
            CandidateContactTraffitLedger.status == "exception"
        )
    )
    lag_seconds: int | None = None
    if intake_cursor and intake_cursor.last_success_at:
        last_success_at = intake_cursor.last_success_at
        if last_success_at.tzinfo is None:
            last_success_at = last_success_at.replace(tzinfo=timezone.utc)
        lag_seconds = max(0, int((now - last_success_at).total_seconds()))

    return ContactOversightResponseDTO(
        counters=ContactOversightCountersDTO(
            overdue=int(aggregate.overdue or 0),
            unassigned=int(aggregate.unassigned or 0),
            awaiting_capacity=int(aggregate.awaiting_capacity or 0),
            blocked_no_phone=int(aggregate.blocked_no_phone or 0),
            ownerless_handoff=int(aggregate.ownerless_handoff or 0),
            reassigned_today=int(reassigned_today or 0),
            traffit_lag_seconds=lag_seconds,
            traffit_status=intake_cursor.status if intake_cursor else None,
            traffit_last_error=(intake_cursor.last_error if intake_cursor else None),
            traffit_exception_count=int(intake_exception_count or 0),
        ),
        items=items,
        next_cursor=(_encode_oversight_cursor(page[-1]) if has_more and page else None),
    )


async def _caller_may_act_on_case(
    db: AsyncSession, *, case: CandidateContactCase, user: User
) -> None:
    if case.owner_user_id != user.id:
        raise HTTPException(
            status_code=403,
            detail="Only the current contact owner may log an attempt",
        )
    await _require_case_scope(db, case=case, user=user, include_closed=False)


async def _require_case_scope(
    db: AsyncSession,
    *,
    case: CandidateContactCase,
    user: User,
    include_closed: bool,
) -> None:
    conditions = [
        CandidateContactOpportunity.case_id == case.id,
        job_scope_clause(user, CandidateContactOpportunity.job_id),
    ]
    if not include_closed:
        conditions.append(CandidateContactOpportunity.closed_at.is_(None))
    permitted = await db.scalar(
        select(
            exists(
                select(CandidateContactOpportunity.id).where(
                    *conditions,
                )
            )
        )
    )
    if not permitted:
        raise HTTPException(
            status_code=403,
            detail="No accessible recruitment exists in this contact case",
        )


@router.post("/cases/{case_id}/attempts", response_model=ContactCaseDTO)
async def create_contact_attempt(
    case_id: int,
    body: ContactAttemptCreate,
    current_user: ContactCaller,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=8, max_length=160)
    ],
    db: AsyncSession = Depends(get_db),
) -> ContactCaseDTO:
    if not settings.CANDIDATE_CONTACT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate contact queue is disabled",
        )
    case = await db.get(CandidateContactCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Contact case not found")
    replay_call = await db.scalar(
        select(Call).where(Call.contact_idempotency_key == idempotency_key)
    )
    is_authorized_replay = bool(
        replay_call is not None
        and replay_call.contact_case_id == case_id
        and replay_call.user_id == current_user.id
    )
    if not is_authorized_replay:
        await _caller_may_act_on_case(db, case=case, user=current_user)
    else:
        # Idempotency is independent of current ownership, but never of the
        # current recruitment/PII boundary.  A former owner may replay only
        # while they still have scope to at least one linked job; closed
        # opportunities count so all-not-interested replays remain usable.
        await _require_case_scope(
            db,
            case=case,
            user=current_user,
            include_closed=True,
        )
    try:
        result = await record_contact_attempt(
            db,
            case_id=case_id,
            actor_user_id=current_user.id,
            outcome=body.outcome,
            opportunity_outcomes=[
                item.model_dump() for item in body.opportunity_outcomes
            ],
            expected_version=body.expected_version,
            idempotency_key=idempotency_key,
            callback_at=body.callback_at,
            occurred_at=datetime.now(timezone.utc),
            notes=body.notes,
        )
    except CandidateContactError as exc:
        _translate_domain_error(exc)
        raise AssertionError("unreachable")
    await db.commit()
    refreshed = await db.get(CandidateContactCase, result.case.id)
    assert refreshed is not None
    return await _single_case_dto(db, refreshed, viewer=current_user)


@router.post("/cases/{case_id}/reassign", response_model=ContactCaseDTO)
async def reassign_contact_owner(
    case_id: int,
    body: ContactReassignRequest,
    current_user: ContactOversight,
    db: AsyncSession = Depends(get_db),
) -> ContactCaseDTO:
    if not settings.CANDIDATE_CONTACT_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Candidate contact queue is disabled",
        )
    case = await db.get(CandidateContactCase, case_id)
    if case is None:
        raise HTTPException(status_code=404, detail="Contact case not found")

    if body.target_user_id is not None:
        target = await db.get(User, body.target_user_id)
        if (
            target is None
            or not target.is_active
            or not target.has_any_role(
                UserRole.recruiter,
                UserRole.sourcer,
                UserRole.tac,
                UserRole.talent_community_manager,
            )
        ):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Target must be an active recruiter, sourcer, TAC or "
                    "Talent Community Manager"
                ),
            )
        target_has_scope = await db.scalar(
            select(
                exists(
                    select(CandidateContactOpportunity.id).where(
                        CandidateContactOpportunity.case_id == case.id,
                        CandidateContactOpportunity.closed_at.is_(None),
                        job_scope_clause(target, CandidateContactOpportunity.job_id),
                    )
                )
            )
        )
        if not target_has_scope:
            raise HTTPException(
                status_code=422,
                detail="Target has no access to an open linked recruitment",
            )
    try:
        changed = await reassign_contact_case(
            db,
            case_id=case_id,
            actor_user_id=current_user.id,
            reason=body.reason,
            expected_version=body.expected_version,
            target_user_id=body.target_user_id,
            occurred_at=datetime.now(timezone.utc),
        )
    except CandidateContactError as exc:
        _translate_domain_error(exc)
        raise AssertionError("unreachable")
    await db.commit()
    refreshed = await db.get(CandidateContactCase, changed.id)
    assert refreshed is not None
    return await _single_case_dto(db, refreshed, viewer=current_user, oversight=True)


__all__ = ["router"]
