"""Date-driven lifecycle for multi-consultant order continuations.

Future extensions are persisted as ``scheduled`` groups with draft lines. On
their start date the newest due continuation becomes current, while the
previous current group and any skipped due continuation move to history.

Wyjątek — rodziny rozliczane w MD: tam data startu następcy jest warunkiem
KONIECZNYM, ale nie wystarczającym. Zamówienie MD kończy budżet, nie
kalendarz (ta sama reguła co w ``client_order_lines.sync_md_line_status``),
więc dopóki poprzednik ma niewykorzystane MD, kontynuacja zostaje
zaplanowana. Bez tego następca przejmował zamówienie w dniu swojego startu i
niewykorzystane dni po prostu przepadały — a poprzednik trafiał do historii
z dodatnią pozostałością, której nie dało się już zafakturować.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_today
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_SCHEDULED,
    ClientOrderGroup,
)
from app.models.contract import Contract
from app.services.client_order_lines import record_event
from app.services.contract_lifecycle import sync_contract_to_live_order
from app.services.multi_consultant_orders import EVENT_ORDER_CLOSED
from app.services.shared_md_orders import (
    normalize_empty_generic_explicit_md_group,
    uses_shared_md_pool,
)


def _family_root(group: ClientOrderGroup, by_id: dict[int, ClientOrderGroup]) -> int:
    current = group
    seen = {group.id}
    while current.predecessor_group_id in by_id:
        parent = by_id[current.predecessor_group_id]  # type: ignore[index]
        if parent.id in seen:
            break
        seen.add(parent.id)
        current = parent
    return current.id


async def _md_budget_left(db: AsyncSession, group_id: int) -> Optional[Decimal]:
    """Suma pozostałych MD linii zamówienia. ``None`` = to nie jest zamówienie MD.

    Linie ``cancelled`` są poza sumą: konsultant zdjęty z zamówienia nie
    wykorzysta już swojego budżetu, a wliczanie go trzymałoby kontynuację
    zablokowaną w nieskończoność.
    """
    lines = list(
        (
            await db.execute(
                select(ClientOrder).where(ClientOrder.order_group_id == group_id)
            )
        ).scalars()
    )
    md_lines = [
        line
        for line in lines
        if line.md_total is not None and line.status != ClientOrderStatus.cancelled
    ]
    if not md_lines:
        return None
    return sum(
        (Decimal(str(line.md_remaining or 0)) for line in md_lines), Decimal("0")
    )


async def _predecessor_still_has_md(
    db: AsyncSession,
    group: ClientOrderGroup,
    by_id: dict[int, ClientOrderGroup],
) -> bool:
    """Czy poprzednik tej kontynuacji wciąż ma budżet MD do wykorzystania.

    Pytamy WYŁĄCZNIE o poprzednika w stanie ``active``: zamówienie zakończone
    ręcznie albo wyczerpane już oddało pole, a wstrzymywanie kontynuacji
    zostawiłoby rodzinę bez ani jednego bieżącego zamówienia.

    Rodziny kosztowe i rodziny bez budżetu MD zachowują dotychczasowe,
    czysto datowe zachowanie. Wspólna pula MD także mieszka na grupie, ale —
    tak jak wariant per linia — blokuje następcę do wyczerpania.
    """
    predecessor = by_id.get(group.predecessor_group_id)  # type: ignore[arg-type]
    if predecessor is None or predecessor.status != GROUP_STATUS_ACTIVE:
        return False
    if predecessor.is_cost_based:
        return False
    if uses_shared_md_pool(predecessor):
        return Decimal(str(predecessor.md_budget_remaining or 0)) > Decimal("0")
    left = await _md_budget_left(db, predecessor.id)
    return left is not None and left > Decimal("0")


async def materialize_scheduled_order_groups(
    db: AsyncSession,
    *,
    client_id: Optional[int] = None,
    today: Optional[date] = None,
) -> int:
    """Promote due future groups and close their predecessors idempotently.

    The function only flushes; transaction ownership stays with the caller.
    Returns the number of groups whose stored status changed.
    """

    # `business_today()`, nie `date.today()`: kontener chodzi w UTC, więc
    # między północą warszawską a UTC (1 h zimą, 2 h latem) `date.today()`
    # zwraca WCZORAJ. W tym oknie zamówienie startujące „dziś" zostawało
    # `scheduled` z liniami w `draft` — czyli poza `active_md_lines` i poza
    # licznikiem konsultantów — a bliźniaczy cron kontraktów
    # (`contract_alerts._promote_statuses`) był już na nowym dniu. Dwa
    # mechanizmy tego samego modułu datowały się różnymi dobami.
    boundary_day = today or business_today()
    stmt = select(ClientOrderGroup)
    if client_id is not None:
        stmt = stmt.where(ClientOrderGroup.client_id == client_id)
    groups = list((await db.execute(stmt)).scalars().all())
    if not groups:
        return 0

    # A predecessor never crosses clients, but grouping by (client, root)
    # makes the invariant explicit and fail-safe for legacy bad data.
    by_client: dict[int, dict[int, ClientOrderGroup]] = defaultdict(dict)
    for group in groups:
        by_client[group.client_id][group.id] = group

    families: dict[tuple[int, int], list[ClientOrderGroup]] = defaultdict(list)
    for group in groups:
        root = _family_root(group, by_client[group.client_id])
        families[(group.client_id, root)].append(group)

    changed = 0
    now = datetime.now(timezone.utc)
    for family in families.values():
        due: list[ClientOrderGroup] = []
        for group in family:
            if (
                group.status != GROUP_STATUS_SCHEDULED
                or group.start_date > boundary_day
            ):
                continue
            if await _predecessor_still_has_md(db, group, by_client[group.client_id]):
                continue
            due.append(group)
        if not due:
            continue

        # Gdy proces nie działał przez kilka dat startu, aktywujemy najnowszą
        # już obowiązującą wersję. Starsze due trafiają wprost do historii.
        current = max(due, key=lambda item: (item.start_date, item.id))
        await normalize_empty_generic_explicit_md_group(db, current)
        current.status = GROUP_STATUS_ACTIVE
        current.closure_date = None
        current.closure_reason = None
        current.closed_at = None
        current.closed_by_user_id = None
        changed += 1

        current_lines = list(
            (
                await db.execute(
                    select(ClientOrder).where(ClientOrder.order_group_id == current.id)
                )
            ).scalars()
        )
        for line in current_lines:
            if line.status == ClientOrderStatus.draft:
                line.status = ClientOrderStatus.active
                if line.filled_at is None:
                    line.filled_at = now
                contract = await db.get(Contract, line.contract_id)
                if contract is not None:
                    await sync_contract_to_live_order(
                        db,
                        contract,
                        order_start=line.start_date,
                        order_end=line.end_date,
                        actor_id=None,
                        today=boundary_day,
                    )

        history_boundary = current.start_date - timedelta(days=1)
        for previous in family:
            if previous.id == current.id:
                continue
            should_close = previous.status == GROUP_STATUS_ACTIVE or (
                previous.status == GROUP_STATUS_SCHEDULED
                and previous.start_date <= boundary_day
            )
            if not should_close:
                continue
            await normalize_empty_generic_explicit_md_group(db, previous)
            previous.status = GROUP_STATUS_COMPLETED
            previous.closure_date = history_boundary
            previous.closure_reason = (
                f"Automatycznie zastąpione zamówieniem {current.order_number}"
            )
            previous.closed_at = now
            # `end_date` dociągane jak w ręcznym `close_order_group`: bez tego
            # karta zakończonego zamówienia dalej głosi „do 31.12", podczas gdy
            # jego linie są już przycięte do `history_boundary`.
            #
            # Dolne ograniczenie datą startu jest OBOWIĄZKOWE, nie ostrożnością:
            # `ck_client_order_groups_dates` wymaga `end_date >= start_date`, a
            # następca startujący tego samego dnia co poprzednik daje
            # `history_boundary < previous.start_date`. Materializacja jest
            # wołana z `list_order_groups`, więc naruszenie CHECK-a wywaliłoby
            # 500 przy KAŻDYM otwarciu zakładki, nie tylko w nocnym skanerze.
            previous_end = max(history_boundary, previous.start_date)
            if previous.end_date is None or previous.end_date > previous_end:
                previous.end_date = previous_end
            # Historia zamówienia JEST raportem: bez tego wpisu dialog
            # „Historia statusów" nie pokazuje nic między `przedluzenie`
            # a stanem obecnym, więc nie da się odpowiedzieć, kiedy i czym
            # zamówienie zostało zastąpione. `closure_reason` przepada przy
            # pierwszym `przywroceniu`, które je czyści — dziennik zostaje.
            # `user_id=None` jest poprawne: to przejście systemowe, nie decyzja
            # człowieka, i z tego samego powodu `closed_by_user_id` zostaje puste.
            record_event(
                db,
                group_id=previous.id,
                event_type=EVENT_ORDER_CLOSED,
                description=(
                    f"Zakończono zamówienie {previous.order_number} "
                    f"z dniem {previous_end.isoformat()} — automatycznie "
                    f"zastąpione zamówieniem {current.order_number}"
                ),
                payload={
                    "closure_date": history_boundary.isoformat(),
                    "end_date": previous_end.isoformat(),
                    "successor_group_id": current.id,
                    "successor_order_number": current.order_number,
                    "automatic": True,
                },
            )
            changed += 1

            previous_lines = list(
                (
                    await db.execute(
                        select(ClientOrder).where(
                            ClientOrder.order_group_id == previous.id
                        )
                    )
                ).scalars()
            )
            for line in previous_lines:
                if line.status in (
                    ClientOrderStatus.active,
                    ClientOrderStatus.draft,
                ):
                    line.status = ClientOrderStatus.completed
                if line.end_date is None or line.end_date > history_boundary:
                    line.end_date = history_boundary

    if changed:
        await db.flush()
    return changed
