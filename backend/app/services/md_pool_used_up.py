"""Decyzja o puli MD nie jest potrzebna, gdy pula osoby wynosi 0 MD.

Ticket 4500030067 (BIK, 24.09.2026): sprawę offboardingu założono 11.09, gdy
zostawało jeszcze 13,75 MD (import sierpnia przyszedł 23.09). Import wyzerował
pulę i migawka sprawy spadła do 0, ale sprawa została „do decyzji” — a otwarta
sprawa trzyma zamówienie w „Aktywnych” (``order_md_exhaustion``) i blokuje
„Zakończ zamówienie”. Nie ma czego przenosić ani przywracać, więc taka sprawa
zamyka się sama jako „usunięto 0 MD”, z wpisem w historii zamówienia.

Dotyczy wyłącznie puli PER OSOBA — sprawa wspólnej puli ma migawkę zerową
z definicji (pula mieszka na grupie) i nadal wymaga decyzji o obsadzie.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder
from app.models.client_order_offboarding import (
    OFFBOARDING_RESOLUTION_REMOVE,
    OFFBOARDING_STATUS_PENDING,
    OFFBOARDING_STATUS_RESOLVED,
    ClientOrderOffboardingCase,
)

POOL_USED_UP_REASON = "pool_used_up"

_ZERO = Decimal("0")


def _used_up(case: ClientOrderOffboardingCase, line: Optional[ClientOrder]) -> bool:
    if case.uses_shared_md_pool:
        return False
    if Decimal(str(case.remaining_md_snapshot or 0)) > _ZERO:
        return False
    # Migawka mogła nie nadążyć za linią — decyduje realna pozostałość.
    if line is not None and line.md_remaining is not None:
        return Decimal(str(line.md_remaining)) <= _ZERO
    return True


def close_used_up_case(
    db: AsyncSession,
    case: ClientOrderOffboardingCase,
    line: Optional[ClientOrder],
) -> bool:
    """Zamknij sprawę bez przenoszenia MD. Zmienia obiekty w sesji; zwraca, czy zamknęła."""
    from app.services.client_order_lines import record_event
    from app.services.multi_consultant_orders import EVENT_MD_OFFBOARDING_REMOVED

    if case.status != OFFBOARDING_STATUS_PENDING or not _used_up(case, line):
        return False
    case.status = OFFBOARDING_STATUS_RESOLVED
    case.resolution = OFFBOARDING_RESOLUTION_REMOVE
    case.resolved_at = datetime.now(timezone.utc)
    case.resolved_by_user_id = None
    case.remaining_md_snapshot = _ZERO
    case.resolution_payload = {
        "automatic": True,
        "reason": POOL_USED_UP_REASON,
        "remaining_md": "0",
    }
    case.version = (case.version or 1) + 1
    record_event(
        db,
        group_id=case.order_group_id,
        order_id=case.order_id,
        event_type=EVENT_MD_OFFBOARDING_REMOVED,
        description=(
            "Zakończenie współpracy obsłużone automatycznie — pula MD "
            "wykorzystana w całości (0 MD), decyzja o puli nie jest potrzebna."
        ),
        payload={"automatic": True, "reason": POOL_USED_UP_REASON, "case_id": case.id},
    )
    return True


async def resolve_used_up_offboarding_cases(
    db: AsyncSession, *, group_id: Optional[int] = None
) -> int:
    """Siatka dla spraw założonych przed tą regułą albo wyzerowanych importem."""
    stmt = select(ClientOrderOffboardingCase).where(
        ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
        ClientOrderOffboardingCase.uses_shared_md_pool.is_(False),
        ClientOrderOffboardingCase.remaining_md_snapshot <= 0,
    )
    if group_id is not None:
        stmt = stmt.where(ClientOrderOffboardingCase.order_group_id == group_id)
    cases = list((await db.execute(stmt.with_for_update())).scalars())
    closed = 0
    for case in cases:
        line = await db.get(ClientOrder, case.order_id) if case.order_id else None
        if close_used_up_case(db, case, line):
            closed += 1
    if closed:
        await db.flush()
    return closed
