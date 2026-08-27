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
from app.services.client_identity import client_display_name
from app.services.contractor_identity import count_unique_contractors

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


_PENDING_STATUSES = (
    ContractStatus.draft,
    ContractStatus.ready_for_signature,
)


_LIST_STATUSES = (
    *_PENDING_STATUSES,
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
    UserRole.finance,
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
        if contract.status in _PENDING_STATUSES
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
        client_id=contract.client_id,
        client_name=client_display_name(contract.client) if contract.client else None,
        job_title=contract.job.title if contract.job else None,
        status=contract.status,
        start_date=contract.start_date,
        end_date=contract.end_date,
        rate_candidate=contract.rate_candidate,
        rate_client=contract.rate_client,
        rate_unit=contract.rate_unit,
        currency=contract.resolved_rate_client_currency,
        rate_client_currency=contract.resolved_rate_client_currency,
        rate_candidate_currency=contract.resolved_rate_candidate_currency,
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

    # Umowy odpięte od usuniętego kandydata (`candidate_id IS NULL`, migracja
    # 0225) NIE są kontraktorami — nie ma osoby, której ta lista dotyczy, więc
    # wiersz bez nazwiska i maila nie jest tu do niczego użyteczny. Sam dokument
    # zostaje w pełni widoczny w rejestrze umów (`/api/contracts`), razem
    # z fakturami i podpisami; to ta lista jest o LUDZIACH, nie o dokumentach.
    #
    # Filtr jest też jedyną barierą przed 500: `ContractorCandidateRef.id` to
    # `int`, więc pojedyncza odpięta umowa wywracała walidację odpowiedzi i tym
    # samym CAŁĄ listę kontraktorów dla wszystkich użytkowników.
    query = query.where(Contract.candidate_id.is_not(None))

    # "ending"/"active" are date-window buckets (see contract_service), NOT the
    # raw stored status, so the tab counts agree with the register's date-based
    # filter and don't lag the promotion cron. "draft" stays a plain status match.
    if status_filter == ContractStatus.draft:
        # The existing "Do uzupełnienia" tab is the pending bucket: both an
        # editable draft and a finalized-but-not-yet-active contract belong
        # here. Items keep their real status for an accurate badge.
        query = query.where(Contract.status.in_(_PENDING_STATUSES))
    elif status_filter == ContractStatus.ready_for_signature:
        query = query.where(Contract.status == ContractStatus.ready_for_signature)
    elif status_filter == ContractStatus.ending:
        query = query.where(ending_soon_clause())
    elif status_filter == ContractStatus.active:
        query = query.where(live_not_ending_clause())
    else:
        query = query.where(Contract.status.in_(_LIST_STATUSES))

    if not current_user.has_any_role(*_FULL_VISIBILITY_ROLES):
        # Join Candidate for ownership scoping. Using join (not selectinload
        # chain) so the WHERE can reference Candidate.created_by.
        query = query.join(Candidate, Contract.candidate_id == Candidate.id).where(
            Candidate.created_by == current_user.id
        )

    # Ordering: drafts first (they need attention), then by start_date desc
    # so newest active contractors surface at the top.
    query = query.order_by(
        case(
            (Contract.status.in_(_PENDING_STATUSES), 0),
            (Contract.status == ContractStatus.ending, 1),
            else_=2,
        ),
        Contract.start_date.desc(),
        # Unikalny tie-breaker na końcu. Kubełek statusu i `start_date` NIE
        # rozstrzygają remisów (w bazie harnessu 76 grup o identycznej parze),
        # a stronicowanie bez rozstrzygnięcia gubi i dubluje wiersze dokładnie
        # tak samo jak brak ORDER BY — tylko rzadziej, więc trudniej to złapać.
        Contract.id.desc(),
    )

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0

    result = await db.execute(query.offset((page - 1) * page_size).limit(page_size))
    contracts = list(result.scalars().all())
    items = [_to_item(c) for c in contracts]
    # Stawki, marża i parametry interpretacji kwoty tylko dla VIEW_FINANCE.
    # Pozostali zachowują listę operacyjną bez finansów.
    from app.analytics.capabilities import AnalyticsCapability, user_has_capability

    if not user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE):
        for item in items:
            item.rate_candidate = None
            item.rate_client = None
            item.margin = None
            item.rate_unit = None
            item.currency = None
            item.rate_client_currency = None
            item.rate_candidate_currency = None
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
    # Patrz komentarz przy pierwszej kwerendzie: odpięta umowa nie ma
    # kontraktora, a `ContractorCandidateRef.id` jest nienullowalne.
    query = query.where(Contract.candidate_id.is_not(None))
    query = query.where(Contract.status.in_(_LIST_STATUSES))

    if not current_user.has_any_role(*_FULL_VISIBILITY_ROLES):
        query = query.join(Candidate, Contract.candidate_id == Candidate.id).where(
            Candidate.created_by == current_user.id
        )

    result = await db.execute(query)
    contracts = list(result.scalars().all())

    stats = ContractorStats()
    active_candidates: list[Candidate] = []
    for c in contracts:
        if c.status in _PENDING_STATUSES:
            stats.draft += 1
            if validate_ready_for_activation(c):
                stats.drafts_incomplete += 1
        elif is_ending_soon(c):
            stats.ending += 1
        else:
            # Live but not in the ending window (active, or expired-but-not-yet-
            # demoted). Mirrors live_not_ending_clause so tab counts == list rows.
            stats.active_contracts += 1
            if c.candidate is not None:
                active_candidates.append(c.candidate)
    stats.active = count_unique_contractors(active_candidates)
    return stats
