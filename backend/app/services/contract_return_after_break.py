"""„Powrót po przerwie" — konsultant naprawdę zakończył współpracę i wraca.

W odróżnieniu od „Cofnij zakończenie" (pomyłka, wszystko wraca) tu powstaje
NOWY kontrakt w statusie Szkic, wskazujący poprzedni
(``contracts.returned_from_contract_id``). Poprzedni zostaje zakończony bez
zmian: jego zużycie MD, alerty Delivery Leada i dane w Finansach są historią,
a nowy kontrakt liczy się od własnej daty startu.

Na zamówieniach konsultant trafia jako NOWE przypisanie w statusie Szkic, tak
jak przy nowym kontrakcie — z nową datą startu i danymi do uzupełnienia
(budżet MD, stawki). Poprzednie przypisanie zostaje w „Zakończonych" razem ze
swoim zużyciem:

* zamówienie MD/kosztowe, na którym osoba była (i które nadal jest otwarte) —
  szkic linii w tym zamówieniu;
* zamówienie okresowe — szkic zamówienia okresowego (bez numeru), jeśli osoba
  nie wraca na żadną linię zamówienia MD/kosztowego (ta sama reguła co przy
  zatrudnieniu: dwa zapisy jednej współpracy rozjeżdżają się przy zakończeniu).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.activity import Activity
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_SCHEDULED,
    ClientOrderGroup,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.client_access import assert_client_assignable
from app.services.client_order_lines import consultant_display_name, record_event
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ADDED,
    is_multi_consultant_client,
)

RETURN_REASON = "return_after_break"
RETURN_HISTORY_TEXT = "Powrót po przerwie – utworzono nowy kontrakt"

# Pola kontraktu przenoszone na nowy — opis współpracy, nie jej wynik
# finansowy. Stawki, daty, harmonogramy i pola zakończenia są „do
# uzupełnienia" (ticket: nowy kontrakt jest traktowany jak nowy kontrakt).
_COPIED_FIELDS: tuple[str, ...] = (
    "candidate_id",
    "client_id",
    "job_id",
    "contract_type",
    "rate_unit",
    "billing_hours_per_month",
    "orders_in_md",
    "currency",
    "rate_client_currency",
    "rate_candidate_currency",
    "engagement_model",
    "work_mode",
    "office_location",
    "team_name",
    "project_name",
    "line_manager",
    "client_pm_name",
    "client_pm_email",
    "client_pm_contact_id",
    "candidate_email",
    "candidate_phone",
    "candidate_subject_ref",
    # Okres wypowiedzenia z umowy (0367) — podpowiedź w oknie zakończenia.
    "notice_period_months",
)


@dataclass
class ReturnResult:
    contract: Contract
    group_line_ids: list[int] = field(default_factory=list)
    periodic_order_id: Optional[int] = None
    orders: list[dict[str, Any]] = field(default_factory=list)


def _conflict(message: str, code: str, **extra: Any) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={"code": code, "message": message, **extra},
    )


async def existing_return(db: AsyncSession, contract_id: int) -> Optional[Contract]:
    """Nowy kontrakt z „Powrotu po przerwie", który jeszcze żyje."""
    return await db.scalar(
        select(Contract)
        .where(
            Contract.returned_from_contract_id == contract_id,
            Contract.status != ContractStatus.void,
        )
        .order_by(Contract.id.desc())
        .limit(1)
    )


async def create_return_after_break(
    db: AsyncSession,
    previous: Contract,
    *,
    start_date: date,
    actor_id: Optional[int],
) -> ReturnResult:
    """Załóż kontrakt powrotu i szkice przypisań. Wołający commituje."""

    if previous.status != ContractStatus.ended:
        raise _conflict(
            "Powrót po przerwie dotyczy zakończonego kontraktu. Ten kontrakt "
            "nie jest zakończony — jeśli zakończono go przez pomyłkę, użyj "
            "„Cofnij zakończenie”.",
            "contract_not_ended",
        )
    # Runda 8 (R8-V1-1): nowy kontrakt u klienta usuniętego albo scalonego
    # byłby niewidoczny w każdym rejestrze, a liczyłby się do MRR.
    await assert_client_assignable(db, previous.client_id)
    already = await existing_return(db, previous.id)
    if already is not None:
        raise _conflict(
            f"Powrót po przerwie już utworzono — kontrakt #{already.id}.",
            "return_already_created",
            contract_id=already.id,
        )
    ended_on = previous.end_date or previous.terminated_at
    if ended_on is not None and start_date <= ended_on:
        raise HTTPException(
            status_code=422,
            detail=(
                "Data startu po przerwie musi być późniejsza niż koniec "
                f"poprzedniej współpracy ({ended_on.strftime('%d.%m.%Y')})."
            ),
        )

    contract = Contract(
        **{name: getattr(previous, name) for name in _COPIED_FIELDS},
        status=ContractStatus.draft,
        start_date=start_date,
        end_date=None,
        returned_from_contract_id=previous.id,
    )
    if contract.rate_unit is None:
        contract.rate_unit = RateUnit.hourly
    db.add(contract)
    await db.flush()

    result = ReturnResult(contract=contract)
    previous_orders = list(
        (
            await db.scalars(
                select(ClientOrder)
                .options(
                    selectinload(ClientOrder.order_group),
                    selectinload(ClientOrder.contract).selectinload(Contract.candidate),
                )
                .where(
                    ClientOrder.contract_id == previous.id,
                    ClientOrder.client_id == previous.client_id,
                    ClientOrder.status != ClientOrderStatus.cancelled,
                )
                .order_by(ClientOrder.id)
            )
        )
        .unique()
        .all()
    )

    seen_groups: set[int] = set()
    for old in previous_orders:
        group: Optional[ClientOrderGroup] = old.order_group
        if group is None or group.id in seen_groups:
            continue
        seen_groups.add(group.id)
        if group.status not in (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED):
            continue
        who = consultant_display_name(old)
        line = ClientOrder(
            client_id=group.client_id,
            contract_id=contract.id,
            job_id=old.job_id,
            order_group_id=group.id,
            order_type=group.order_type,
            title=f"Zamówienie {group.order_number} — {who}"[:255],
            status=ClientOrderStatus.draft,
            start_date=start_date,
            end_date=group.end_date,
            rate_unit=RateUnit.daily,
            billing_hours_per_month=old.billing_hours_per_month,
            currency=old.currency or "PLN",
            rate_client_currency=old.rate_client_currency or "PLN",
            rate_candidate_currency=old.rate_candidate_currency or "PLN",
            md_manual_adjustment=Decimal("0"),
            executive_contract_id=group.executive_contract_id,
            project_part=old.project_part,
            created_by_user_id=actor_id,
        )
        db.add(line)
        await db.flush()
        result.group_line_ids.append(line.id)
        description = (
            f"{RETURN_HISTORY_TEXT} #{contract.id} (poprzedni #{previous.id}). "
            f"{who} wraca na zamówienie od {start_date.strftime('%d.%m.%Y')} "
            "jako szkic — uzupełnij budżet i stawki. Poprzednie przypisanie "
            "zostaje w „Zakończonych” razem ze swoim zużyciem."
        )
        record_event(
            db,
            group_id=group.id,
            order_id=line.id,
            event_type=EVENT_CONSULTANT_ADDED,
            description=description,
            payload={
                "origin": "manual",
                "reason": RETURN_REASON,
                "contract_id": contract.id,
                "returned_from_contract_id": previous.id,
                "previous_order_id": old.id,
                "start_date": start_date.isoformat(),
            },
            user_id=actor_id,
        )
        result.orders.append(
            {"order_id": line.id, "order_label": group.order_number, "kind": "group"}
        )

    periodic = [old for old in previous_orders if old.order_group_id is None]
    if periodic and not result.group_line_ids:
        old = periodic[-1]
        who = consultant_display_name(old)
        multi = is_multi_consultant_client(previous.client_id)
        order = ClientOrder(
            client_id=previous.client_id,
            contract_id=contract.id,
            job_id=old.job_id,
            title=("(bez numeru)" if multi else f"{who} — powrót po przerwie")[:255],
            order_type=old.order_type,
            status=ClientOrderStatus.draft,
            start_date=start_date,
            rate_unit=old.rate_unit,
            billing_hours_per_month=old.billing_hours_per_month,
            currency=old.currency or "PLN",
            rate_client_currency=old.rate_client_currency or "PLN",
            rate_candidate_currency=old.rate_candidate_currency or "PLN",
            # Runda 8 (R8-N6-5): zakończona umowa wykonawcza nie przechodzi.
            executive_contract_id=await inheritable_executive_contract_id(
                db, old.executive_contract_id
            ),
            project_part=old.project_part,
            created_by_user_id=actor_id,
            notes=(
                f"{RETURN_HISTORY_TEXT} (poprzedni kontrakt #{previous.id}). "
                "Uzupełnij numer, stawki, daty i wgraj PDF zamówienia."
            ),
        )
        db.add(order)
        await db.flush()
        result.periodic_order_id = order.id
        db.add(
            Activity(
                entity_type="client_order",
                entity_id=order.id,
                action=RETURN_REASON,
                user_id=actor_id,
                details={
                    "message": RETURN_HISTORY_TEXT,
                    "contract_id": contract.id,
                    "returned_from_contract_id": previous.id,
                    "previous_order_id": old.id,
                    "start_date": start_date.isoformat(),
                },
            )
        )
        result.orders.append(
            {"order_id": order.id, "order_label": order.title, "kind": "periodic"}
        )

    details = {
        "message": RETURN_HISTORY_TEXT,
        "contract_id": contract.id,
        "returned_from_contract_id": previous.id,
        "start_date": start_date.isoformat(),
        "order_ids": [item["order_id"] for item in result.orders],
    }
    db.add(
        Activity(
            entity_type="contract",
            entity_id=previous.id,
            action=RETURN_REASON,
            user_id=actor_id,
            details=details,
        )
    )
    db.add(
        Activity(
            entity_type="contract",
            entity_id=contract.id,
            action=RETURN_REASON,
            user_id=actor_id,
            details=details,
        )
    )
    # Generator umów B2B: nowa umowa dla powrotu po przerwie (0367).
    from app.services.contract_termination_sync import (
        on_contract_returned_after_break,
    )

    await on_contract_returned_after_break(
        db, previous, contract, actor_id=actor_id, today=start_date
    )
    await db.flush()
    return result
