"""Atomic, idempotent Contract -> ClientOrder offboarding effects.

Every contract-ending entry point must call this service instead of assigning
``ClientOrder.status`` directly.  A future termination clips the engagement
period now but materializes type-specific effects only on its effective date.
The caller owns the transaction and commit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_order_offboarding import (
    OFFBOARDING_STATUS_PENDING,
    ClientOrderOffboardingCase,
)
from app.models.contract import Contract
from app.models.order_type import OrderType
from app.services.client_order_lines import (
    consultant_display_name,
    recompute_remaining,
    record_event,
)
from app.services.dl_alerts import emit_md_consultant_ended
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ENDED,
    EVENT_MD_OFFBOARDING_PENDING,
    quantize_md,
)
from app.services.order_types import (
    effective_group_order_type,
    effective_standalone_order_type,
)


_OPEN_ORDER_STATUSES: tuple[ClientOrderStatus, ...] = (
    ClientOrderStatus.draft,
    ClientOrderStatus.active,
    ClientOrderStatus.paused,
)
_ZERO_MD = Decimal("0.000000")


@dataclass(frozen=True)
class ContractOrderOffboardingResult:
    """Observable result for Activity logs and focused integration tests."""

    affected_orders: int
    cancelled_future: int
    periodic_completed: int
    cost_completed: int
    md_cases_created: int
    md_cases_pending: int
    alerts_created: int
    case_ids: tuple[int, ...]


async def _pending_cases(
    db: AsyncSession, *, contract_id: int, effective_date: date
) -> list[ClientOrderOffboardingCase]:
    result = await db.execute(
        select(ClientOrderOffboardingCase)
        .options(
            selectinload(ClientOrderOffboardingCase.order)
            .selectinload(ClientOrder.contract)
            .selectinload(Contract.candidate),
            selectinload(ClientOrderOffboardingCase.order_group),
        )
        .where(
            ClientOrderOffboardingCase.contract_id == contract_id,
            ClientOrderOffboardingCase.effective_date == effective_date,
            ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
        )
        .order_by(ClientOrderOffboardingCase.id.asc())
        .with_for_update()
    )
    return list(result.scalars().unique().all())


async def _open_orders(db: AsyncSession, contract_id: int) -> list[ClientOrder]:
    result = await db.execute(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.order_group),
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
        )
        .where(
            ClientOrder.contract_id == contract_id,
            ClientOrder.status.in_(_OPEN_ORDER_STATUSES),
        )
        .order_by(ClientOrder.id.asc())
        .with_for_update()
    )
    return list(result.scalars().unique().all())


def _effective_order_type(order: ClientOrder) -> OrderType:
    if order.order_group is not None:
        return effective_group_order_type(order.order_group)
    return effective_standalone_order_type(order.client_id, order.order_type)


def _snapshot_currency(order: ClientOrder) -> Optional[str]:
    if order.currency:
        return order.currency.strip().upper()
    contract = order.contract
    if contract is None:
        return None
    return contract.resolved_rate_client_currency


async def _ensure_md_case(
    db: AsyncSession,
    *,
    order: ClientOrder,
    group: Optional[ClientOrderGroup],
    effective_date: date,
    remaining_md: Decimal,
    uses_shared_md_pool: bool,
    actor_id: Optional[int],
) -> tuple[ClientOrderOffboardingCase, bool]:
    """Insert one episode atomically or return the row won by another retry."""

    values = {
        "contract_id": order.contract_id,
        "order_id": order.id,
        "order_group_id": group.id if group else None,
        "client_id": order.client_id,
        "effective_date": effective_date,
        "status": OFFBOARDING_STATUS_PENDING,
        "version": 1,
        "uses_shared_md_pool": uses_shared_md_pool,
        "remaining_md_snapshot": quantize_md(remaining_md),
        "rate_cost_snapshot": order.md_rate_cost,
        "rate_revenue_snapshot": order.md_rate_revenue,
        "currency_snapshot": _snapshot_currency(order),
        "order_number_snapshot": group.order_number if group else None,
        "created_by_user_id": actor_id,
    }
    case_id = await db.scalar(
        pg_insert(ClientOrderOffboardingCase)
        .values(**values)
        .on_conflict_do_nothing(
            constraint="uq_client_order_offboarding_order_effective"
        )
        .returning(ClientOrderOffboardingCase.id)
    )
    created = case_id is not None
    if case_id is not None:
        case = await db.get(ClientOrderOffboardingCase, case_id)
    else:
        case = await db.scalar(
            select(ClientOrderOffboardingCase)
            .where(
                ClientOrderOffboardingCase.order_id == order.id,
                ClientOrderOffboardingCase.effective_date == effective_date,
            )
            .with_for_update()
        )
    if case is None:  # pragma: no cover - database invariant / defensive guard
        raise RuntimeError("Nie udało się utworzyć sprawy zakończenia współpracy")
    return case, created


def _record_cost_completion(
    db: AsyncSession,
    *,
    order: ClientOrder,
    group: ClientOrderGroup,
    effective_date: date,
    actor_id: Optional[int],
) -> None:
    who = consultant_display_name(order)
    record_event(
        db,
        group_id=group.id,
        order_id=order.id,
        event_type=EVENT_CONSULTANT_ENDED,
        description=(
            f"{who} zakończył(a) współpracę {effective_date.isoformat()}. "
            "Linia została przeniesiona do zakończonych; historia faktur "
            "pozostała bez zmian."
        ),
        payload={
            "contract_id": order.contract_id,
            "order_id": order.id,
            "effective_date": effective_date.isoformat(),
            "order_number": group.order_number,
        },
        user_id=actor_id,
    )


def _record_md_pending(
    db: AsyncSession,
    *,
    case: ClientOrderOffboardingCase,
    order: ClientOrder,
    group: Optional[ClientOrderGroup],
    actor_id: Optional[int],
) -> None:
    if group is None:
        return
    who = consultant_display_name(order)
    shared = case.uses_shared_md_pool
    pool = (
        "wspólna pula zamówienia pozostała bez zmian"
        if shared
        else f"pozostało {case.remaining_md_snapshot} MD"
    )
    record_event(
        db,
        group_id=group.id,
        order_id=order.id,
        event_type=EVENT_MD_OFFBOARDING_PENDING,
        description=(
            f"{who} zakończył(a) współpracę {case.effective_date.isoformat()}; "
            f"{pool}. Wymagana decyzja Delivery Leada."
        ),
        payload={
            "offboarding_case_id": case.id,
            "contract_id": order.contract_id,
            "order_id": order.id,
            "effective_date": case.effective_date.isoformat(),
            "remaining_md": str(case.remaining_md_snapshot),
            "uses_shared_md_pool": shared,
            "rate_cost": (
                None
                if case.rate_cost_snapshot is None
                else str(case.rate_cost_snapshot)
            ),
            "rate_revenue": (
                None
                if case.rate_revenue_snapshot is None
                else str(case.rate_revenue_snapshot)
            ),
            "currency": case.currency_snapshot,
        },
        user_id=actor_id,
    )


async def apply_contract_order_offboarding(
    db: AsyncSession,
    *,
    contract_id: int,
    effective_date: date,
    actor_id: Optional[int] = None,
    today: Optional[date] = None,
) -> ContractOrderOffboardingResult:
    """Apply all type-specific order effects for one ended Contract.

    The function intentionally does not commit.  Contract status, order
    effects, cases, events and alerts must succeed or roll back together.
    """

    materialization_day = today or business_today()
    existing_cases = (
        await _pending_cases(db, contract_id=contract_id, effective_date=effective_date)
        if effective_date <= materialization_day
        else []
    )
    case_context: dict[
        int,
        tuple[
            ClientOrderOffboardingCase,
            ClientOrder,
            Optional[ClientOrderGroup],
        ],
    ] = {
        case.id: (case, case.order, case.order_group)
        for case in existing_cases
        if case.order is not None
    }
    existing_by_order = {case.order_id: case for case in existing_cases}

    orders = await _open_orders(db, contract_id)
    cancelled_future = 0
    periodic_completed = 0
    cost_completed = 0
    md_cases_created = 0

    for order in orders:
        if order.start_date is not None and order.start_date > effective_date:
            order.status = ClientOrderStatus.cancelled
            cancelled_future += 1
            continue

        if order.end_date is None or order.end_date > effective_date:
            order.end_date = effective_date

        # Requested now, effective later: keep the consultant operational until
        # the shared business-day boundary materializes the termination.
        if effective_date > materialization_day:
            continue

        order_type = _effective_order_type(order)
        group = order.order_group

        if order_type == OrderType.periodic:
            order.status = ClientOrderStatus.completed
            periodic_completed += 1
            continue

        if order_type == OrderType.cost:
            order.status = ClientOrderStatus.completed
            cost_completed += 1
            if group is not None:
                _record_cost_completion(
                    db,
                    order=order,
                    group=group,
                    effective_date=effective_date,
                    actor_id=actor_id,
                )
            continue

        # MD always becomes non-matchable for future imports immediately.  A
        # separate pending case keeps it visible until the DL decides what to
        # do with the remaining budget.
        if group is None:
            # A detached historical line is no longer part of an actionable
            # multi-consultant order.  Creating a case without a group would
            # leave an alert that has no resolve route or UI destination.
            order.status = ClientOrderStatus.completed
            continue
        uses_shared_pool = bool(group and group.is_md_budget_based)
        if uses_shared_pool:
            remaining = _ZERO_MD
        elif order.md_total is not None:
            # Over-consumption is historical usage, never a negative pool to
            # transfer.  Snapshot only the still-unused MD.
            remaining = max(_ZERO_MD, await recompute_remaining(db, order))
        else:
            # Defensive support for an unmaterialized explicit MD draft.  It
            # has no per-line budget to guess, so fail closed at zero.
            remaining = _ZERO_MD
        order.status = ClientOrderStatus.completed

        case = existing_by_order.get(order.id)
        created = False
        if case is None:
            case, created = await _ensure_md_case(
                db,
                order=order,
                group=group,
                effective_date=effective_date,
                remaining_md=remaining,
                uses_shared_md_pool=uses_shared_pool,
                actor_id=actor_id,
            )
            existing_by_order[order.id] = case
        if created:
            md_cases_created += 1
            _record_md_pending(
                db,
                case=case,
                order=order,
                group=group,
                actor_id=actor_id,
            )
        case_context[case.id] = (case, order, group)

    alerts_created = 0
    for case_id in sorted(case_context):
        case, order, group = case_context[case_id]
        alerts = await emit_md_consultant_ended(
            db,
            case_id=case.id,
            client_id=case.client_id,
            order_id=case.order_id,
            order_group_id=case.order_group_id,
            order_number=case.order_number_snapshot,
            consultant_name=consultant_display_name(order),
            effective_date=case.effective_date,
            remaining_md=Decimal(str(case.remaining_md_snapshot)),
            uses_shared_md_pool=case.uses_shared_md_pool,
        )
        alerts_created += len(alerts)

    case_ids = tuple(sorted(case_context))
    return ContractOrderOffboardingResult(
        affected_orders=len(orders),
        cancelled_future=cancelled_future,
        periodic_completed=periodic_completed,
        cost_completed=cost_completed,
        md_cases_created=md_cases_created,
        md_cases_pending=len(case_ids),
        alerts_created=alerts_created,
        case_ids=case_ids,
    )


async def reconcile_pending_md_offboarding_alerts(db: AsyncSession) -> int:
    """Re-emit missing case-scoped alerts after DL assignment/config changes.

    Emission is deduplicated per case and recipient.  A daily replay therefore
    fills the gap when no Delivery Lead was assigned (or alerts were disabled)
    at the exact moment the contract ended, without creating duplicates.
    """

    result = await db.execute(
        select(ClientOrderOffboardingCase)
        .options(
            selectinload(ClientOrderOffboardingCase.order)
            .selectinload(ClientOrder.contract)
            .selectinload(Contract.candidate),
            selectinload(ClientOrderOffboardingCase.order_group),
        )
        .where(ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING)
        .order_by(ClientOrderOffboardingCase.id.asc())
        .with_for_update(skip_locked=True)
    )
    created = 0
    for case in result.scalars().unique().all():
        order = case.order
        if order is None or case.order_group is None:
            continue
        alerts = await emit_md_consultant_ended(
            db,
            case_id=case.id,
            client_id=case.client_id,
            order_id=case.order_id,
            order_group_id=case.order_group_id,
            order_number=case.order_number_snapshot,
            consultant_name=consultant_display_name(order),
            effective_date=case.effective_date,
            remaining_md=Decimal(str(case.remaining_md_snapshot)),
            uses_shared_md_pool=case.uses_shared_md_pool,
        )
        created += len(alerts)
    return created
