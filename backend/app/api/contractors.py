"""Contractor module — read-only view of hired candidates with live contracts.

A "contractor" in this codebase is not a separate entity: it's a Candidate
with a Contract in status IN (draft, active, ending). This router aggregates
the join and exposes it as a dedicated listing so backoffice can:

- See drafts that still need rates / dates ("Do uzupełnienia")
- See active engagements (the real contractor roster)
- See contracts ending soon (live contract with end_date within the next 30 days —
  a date window shared with the register, not the raw stored ContractStatus.ending)

Role scoping:
- admin / delivery_lead / tac / head_of_recruitment → sees everyone
- recruiter / sourcer → sees only candidates they added (Candidate.created_by)
- user (read-only viewer) → 403 (the roster carries candidate PII + rates)

The "incomplete drafts" subcount drives the dashboard widget
("Drafty do uzupełnienia (N)").
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.contract import Contract, ContractStatus
from app.models.user import UserRole
from app.schemas.contract import (
    ContractorCandidateRef,
    ContractorList,
    ContractorListItem,
    ContractorStats,
)
from app.services.contract_service import (
    ending_soon_clause,
    is_ending_soon,
    live_not_ending_clause,
    validate_ready_for_activation,
)

router = APIRouter()


# Roles that see every contractor. Anyone else gets scoped to their own
# Candidate.created_by set (matches the "recruiter ownership" convention
# used across the candidates module).
_FULL_VISIBILITY_ROLES = {
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
    UserRole.tac,
}


_LIST_STATUSES = (
    ContractStatus.draft,
    ContractStatus.active,
    ContractStatus.ending,
)


# Roles allowed to reach the contractor roster at all. Everyone else — notably
# UserRole.user (the read-only viewer / QC / client persona) — is refused: the
# payload carries candidate PII + rates/margins, so the FE hiding the operations
# mode must not be the only gate. recruiter/sourcer pass here but are further
# scoped to their own candidates (Candidate.created_by) in the query below.
_CONTRACTOR_ALLOWED_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
)


def _require_contractor_access(current_user) -> None:  # type: ignore[no-untyped-def]
    """Fail closed for passive viewer accounts while preserving multi-role."""
    if not current_user.has_any_role(*_CONTRACTOR_ALLOWED_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Contractor data requires an operational role",
        )


def _to_item(contract: Contract) -> ContractorListItem:
    """Serialize a Contract (with eager-loaded relations) to the list row."""
    missing = (
        validate_ready_for_activation(contract)
        if contract.status == ContractStatus.draft
        else []
    )
    candidate = contract.candidate
    candidate_ref = ContractorCandidateRef(
        id=candidate.id if candidate else contract.candidate_id,
        name=candidate.name if candidate else "",
        lastname=candidate.lastname if candidate else "",
        email=candidate.email if candidate else None,
    )
    return ContractorListItem(
        contract_id=contract.id,
        candidate=candidate_ref,
        client_name=contract.client.name if contract.client else None,
        job_title=contract.job.title if contract.job else None,
        status=contract.status,
        start_date=contract.start_date,
        end_date=contract.end_date,
        rate_candidate=contract.rate_candidate,
        rate_client=contract.rate_client,
        rate_unit=contract.rate_unit,
        currency=contract.currency,
        margin=contract.margin,
        contract_type=contract.contract_type,
        work_mode=contract.work_mode,
        missing_fields=missing,
    )


@router.get("", response_model=ContractorList)
async def list_contractors(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[ContractStatus] = Query(None, alias="status"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """List contractors (Contracts with status in draft/active/ending).

    `status` query param narrows to a single status; default is all three.
    Role-scoped: non-privileged roles see only candidates they added.
    """
    _require_contractor_access(current_user)

    query = select(Contract).options(
        selectinload(Contract.candidate),
        selectinload(Contract.client),
        selectinload(Contract.job),
    )

    # "ending"/"active" are date-window buckets (see contract_service), NOT the
    # raw stored status, so the tab counts agree with the register's date-based
    # filter and don't lag the promotion cron. "draft" stays a plain status match.
    if status_filter == ContractStatus.draft:
        query = query.where(Contract.status == ContractStatus.draft)
    elif status_filter == ContractStatus.ending:
        query = query.where(ending_soon_clause())
    elif status_filter == ContractStatus.active:
        query = query.where(live_not_ending_clause())
    else:
        query = query.where(Contract.status.in_(_LIST_STATUSES))

    if current_user.role not in _FULL_VISIBILITY_ROLES:
        # Join Candidate for ownership scoping. Using join (not selectinload
        # chain) so the WHERE can reference Candidate.created_by.
        query = query.join(Candidate, Contract.candidate_id == Candidate.id).where(
            Candidate.created_by == current_user.id
        )

    # Ordering: drafts first (they need attention), then by start_date desc
    # so newest active contractors surface at the top.
    query = query.order_by(
        case(
            (Contract.status == ContractStatus.draft, 0),
            (Contract.status == ContractStatus.ending, 1),
            else_=2,
        ),
        Contract.start_date.desc(),
    )

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0

    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    contracts = list(result.scalars().all())
    items = [_to_item(c) for c in contracts]
    # P0.12: stawki/marża tylko dla VIEW_FINANCE (admin + delivery_lead) —
    # kanoniczna polityka NEXUS. recruiter/sourcer/tac zachowują listę
    # kontraktorów (operacyjnie), ale bez kwot.
    from app.analytics.capabilities import AnalyticsCapability, user_has_capability

    if not user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE):
        for item in items:
            item.rate_candidate = None
            item.rate_client = None
            item.margin = None
    return ContractorList(items=items, total=total, page=page, page_size=page_size)


@router.get("/stats", response_model=ContractorStats)
async def contractor_stats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Aggregate counts for the contractors tab headers + dashboard widget.

    `drafts_incomplete` counts drafts missing ANY of the activation-required
    fields. Computed in Python (not SQL) so it matches the validator
    exactly — one source of truth for "ready to activate".
    """
    _require_contractor_access(current_user)

    query = select(Contract).options(
        selectinload(Contract.candidate),
    )
    query = query.where(Contract.status.in_(_LIST_STATUSES))

    if current_user.role not in _FULL_VISIBILITY_ROLES:
        query = query.join(Candidate, Contract.candidate_id == Candidate.id).where(
            Candidate.created_by == current_user.id
        )

    result = await db.execute(query)
    contracts = list(result.scalars().all())

    stats = ContractorStats()
    for c in contracts:
        if c.status == ContractStatus.draft:
            stats.draft += 1
            if validate_ready_for_activation(c):
                stats.drafts_incomplete += 1
        elif is_ending_soon(c):
            stats.ending += 1
        else:
            # Live but not in the ending window (active, or expired-but-not-yet-
            # demoted). Mirrors live_not_ending_clause so tab counts == list rows.
            stats.active += 1
    return stats
