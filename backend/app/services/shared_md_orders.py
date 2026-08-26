"""Wspólna pula MD całego zamówienia Cyfrowego Polsatu i Lotte Wedel.

To nie jest istniejący wariant MD per konsultant. Tutaj miesięczna konsumpcja
jest agregowana na grupie, a pozostałość jest zawsze przeliczana od zera, dzięki
czemu ponowny zapis tego samego miesiąca nie odejmuje MD drugi raz.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from decimal import Decimal
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_EXHAUSTED,
    ClientOrderGroup,
    ClientOrderGroupMdConsumption,
)
from app.services.cost_orders import lock_group_for_settlement
from app.services.multi_consultant_orders import quantize_md


ZERO = Decimal("0.000000")
_PERIOD_MONTH_RE = re.compile(r"^[0-9]{4}-(0[1-9]|1[0-2])$")


async def shared_md_used_total(db: AsyncSession, group_id: int) -> Decimal:
    """Pełna narastająca suma wykorzystanych MD, także ponad limit."""

    return (await shared_md_used_totals(db, (group_id,)))[group_id]


async def shared_md_used_totals(
    db: AsyncSession, group_ids: Iterable[int]
) -> dict[int, Decimal]:
    """Narastające wykorzystanie wielu grup w jednym zapytaniu agregującym."""

    ids = tuple(dict.fromkeys(group_ids))
    if not ids:
        return {}
    rows = await db.execute(
        select(
            ClientOrderGroupMdConsumption.group_id,
            func.coalesce(func.sum(ClientOrderGroupMdConsumption.md_reported), 0),
        )
        .where(ClientOrderGroupMdConsumption.group_id.in_(ids))
        .group_by(ClientOrderGroupMdConsumption.group_id)
    )
    totals = {group_id: ZERO for group_id in ids}
    for group_id, value in rows:
        totals[group_id] = quantize_md(value or 0)
    return totals


async def settle_shared_md_group(db: AsyncSession, group: ClientOrderGroup) -> Decimal:
    """Przelicz wspólną pulę i zsynchronizuj status grupy.

    Pozostałość ma podłogę zero. Pełne wykorzystanie pozostaje osobną sumą,
    więc przekroczenie nie znika informacyjnie. Ręcznie zakończonego zamówienia
    import/korekta nie otwiera; wyłącznie status ``exhausted`` może wrócić do
    ``active`` po zwiększeniu puli.

    Tak jak rozliczenie kosztowe, każda ścieżka serializuje się na wierszu
    grupy przed odczytem konsumpcji. Dzięki temu równoległy import i ręczna
    korekta budżetu nie zapiszą pozostałości policzonej ze starego stanu.
    """

    group = await lock_group_for_settlement(db, group, flush_local_changes=True)

    if not group.is_md_budget_based or group.md_budget_total is None:
        group.md_budget_remaining = None
        return ZERO

    budget = quantize_md(group.md_budget_total)
    adjustment = quantize_md(group.md_budget_manual_adjustment or 0)
    available = quantize_md(budget + adjustment)
    if available < ZERO:
        available = ZERO

    used = await shared_md_used_total(db, group.id)
    remaining = quantize_md(available - used)
    if remaining < ZERO:
        remaining = ZERO
    group.md_budget_remaining = remaining

    if group.status == GROUP_STATUS_ACTIVE and remaining <= ZERO:
        group.status = GROUP_STATUS_EXHAUSTED
    elif group.status == GROUP_STATUS_EXHAUSTED and remaining > ZERO:
        group.status = GROUP_STATUS_ACTIVE
    return remaining


async def upsert_shared_md_consumption(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    period_month: str,
    md_reported: Decimal,
    source: str = "import",
    user_id: Optional[int] = None,
) -> tuple[ClientOrderGroupMdConsumption, Decimal]:
    """Idempotentnie zapisz miesiąc grupy i od razu przelicz pozostałość."""

    if not group.is_md_budget_based:
        raise ValueError("Konsumpcję wspólnej puli MD można zapisać tylko dla typu MD")
    if not _PERIOD_MONTH_RE.fullmatch(period_month):
        raise ValueError("Miesiąc musi mieć format YYYY-MM")
    if source not in {"import", "manual"}:
        raise ValueError("Źródło konsumpcji musi być 'import' albo 'manual'")
    value = quantize_md(md_reported)
    if value < ZERO:
        raise ValueError("Wykorzystanie MD nie może być ujemne")

    # Wszyscy writerzy zachowują kolejność grupa → konsumpcja. Bez tego
    # bezpośredni caller mógłby zablokować wiersz miesiąca i czekać na grupę,
    # podczas gdy równoległy import trzyma grupę i czeka na ten sam miesiąc.
    group = await lock_group_for_settlement(db, group, flush_local_changes=False)

    stmt = (
        pg_insert(ClientOrderGroupMdConsumption)
        .values(
            group_id=group.id,
            period_month=period_month,
            md_reported=value,
            source=source,
            created_by_user_id=user_id,
        )
        .on_conflict_do_update(
            index_elements=[
                ClientOrderGroupMdConsumption.group_id,
                ClientOrderGroupMdConsumption.period_month,
            ],
            set_={
                "md_reported": value,
                "source": source,
                "created_by_user_id": user_id,
                "updated_at": func.now(),
            },
        )
        .returning(ClientOrderGroupMdConsumption.id)
    )
    row_id = await db.scalar(stmt)
    row = await db.get(ClientOrderGroupMdConsumption, row_id)
    if row is None:
        raise RuntimeError(
            f"upsert_shared_md_consumption: brak wiersza po zapisie (id={row_id})"
        )
    remaining = await settle_shared_md_group(db, group)
    return row, remaining
