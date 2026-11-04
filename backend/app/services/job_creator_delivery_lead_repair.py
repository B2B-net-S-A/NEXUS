"""Jednorazowo: rekrutacja założona przez Delivery Leada wraca do niego (08.10.2026).

Do 08.10.2026 `create_job_core` wpisywał głównego DL-a klienta także wtedy,
gdy rekrutację zakładał inny Delivery Lead — przegląd DL i alerty takiej
rekrutacji szły do głównego DL-a, nie do osoby, która ją prowadzi. Pomiar na
produkcji 08.10.2026: 4 z 62 rekrutacji założonych przez Delivery Leadów od
17.09.

Warunek, nie lista ID: otwarta rekrutacja spoza Traffita, której DL-a wpisał
automat (`delivery_lead_auto_filled`), a twórca jest aktywnym kontem z rolą
Delivery Leada i nie jest tym DL-em. DL wpisany przez człowieka zostaje.

Marker w ``app_settings`` + advisory lock: drugi start kończy się od razu.
Paragon niesie same ID (rekrutacja, poprzedni DL, twórca) — po nich da się
korektę odwrócić.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

REPAIR_MARKER = "job_creator_delivery_lead_2026_10"

_REASSIGN = text(
    """
    WITH target AS (
        SELECT j.id, j.delivery_lead_id AS previous_id, j.created_by AS creator_id
          FROM jobs j
          JOIN users u ON u.id = j.created_by AND u.is_active
               AND (CAST(u.role AS text) = 'delivery_lead'
                    OR u.roles @> CAST('["delivery_lead"]' AS jsonb))
         WHERE j.delivery_lead_auto_filled
           AND j.delivery_lead_id IS DISTINCT FROM j.created_by
           AND j.status IN ('draft', 'published')
           AND COALESCE(j.external_source, 'manual') <> 'traffit'
           FOR UPDATE OF j
    )
    UPDATE jobs j
       SET delivery_lead_id = t.creator_id, delivery_lead_auto_filled = false
      FROM target t
     WHERE j.id = t.id
    RETURNING j.id, t.previous_id, t.creator_id
    """
)


async def reassign_to_creators(db: AsyncSession) -> list[dict[str, Optional[int]]]:
    """Przepina rekrutacje na twórcę-DL-a. Zwraca zmiany; wołający commituje."""
    rows = (await db.execute(_REASSIGN)).all()
    return sorted(
        (
            {"job_id": job_id, "previous_dl_id": previous_id, "dl_id": creator_id}
            for job_id, previous_id, creator_id in rows
        ),
        key=lambda change: change["job_id"],
    )


async def run_job_creator_delivery_lead_repair(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """``None`` = już wykonane. Wołający commituje."""
    now = now or datetime.now(timezone.utc)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": REPAIR_MARKER}
    )
    if await db.get(AppSetting, REPAIR_MARKER) is not None:
        return None

    changes = await reassign_to_creators(db)
    summary = {"done_at": now.isoformat(), "total": len(changes), "changes": changes}
    db.add(AppSetting(key=REPAIR_MARKER, value=summary))
    await db.flush()
    return summary


__all__ = [
    "REPAIR_MARKER",
    "reassign_to_creators",
    "run_job_creator_delivery_lead_repair",
]
