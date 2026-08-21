"""Date-driven lifecycle for multi-consultant order continuations.

Future extensions are persisted as ``scheduled`` groups with draft lines. On
their start date the newest due continuation becomes current, while the
previous current group and any skipped due continuation move to history.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_SCHEDULED,
    ClientOrderGroup,
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

    boundary_day = today or date.today()
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
        due = [
            group
            for group in family
            if group.status == GROUP_STATUS_SCHEDULED
            and group.start_date <= boundary_day
        ]
        if not due:
            continue

        # Gdy proces nie działał przez kilka dat startu, aktywujemy najnowszą
        # już obowiązującą wersję. Starsze due trafiają wprost do historii.
        current = max(due, key=lambda item: (item.start_date, item.id))
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
            previous.status = GROUP_STATUS_COMPLETED
            previous.closure_date = history_boundary
            previous.closure_reason = (
                f"Automatycznie zastąpione zamówieniem {current.order_number}"
            )
            previous.closed_at = now
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
