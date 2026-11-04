"""Jednorazowe wygaszenie propozycji w zamkniętych rekrutacjach (06.10.2026).

Audyt 06.10.2026 (R6): zamknięcie rekrutacji nie ruszało jej skrzynki „Do
przejrzenia” — 172 propozycje wisiały w zamkniętych rekrutacjach. Od 0422
robi to ``job_lifecycle.close_job_core``; ten krok domyka stan sprzed
wdrożenia. Nic nie jest kasowane — status ``proposed`` → ``expired``.

Marker w ``app_settings`` + advisory lock: drugi start kończy się od razu.
Paragon niesie wyłącznie liczby.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting

REPAIR_MARKER = "job_proposals_closed_jobs_expired_2026_10"

_EXPIRE_SQL = text(
    """
    WITH expired AS (
        UPDATE job_proposals AS p
           SET status = 'expired'
          FROM jobs AS j
         WHERE j.id = p.job_id
           AND j.status = 'closed'
           AND p.status = 'proposed'
        RETURNING p.job_id
    )
    SELECT count(*) AS rows, count(DISTINCT job_id) AS jobs FROM expired
    """
)


async def run_closed_job_proposal_expiry(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> Optional[dict[str, Any]]:
    """Wygasza otwarte propozycje zamkniętych rekrutacji. ``None`` = już wykonane.

    Wołający commituje.
    """
    now = now or datetime.now(timezone.utc)
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": REPAIR_MARKER}
    )
    if await db.get(AppSetting, REPAIR_MARKER) is not None:
        return None
    row = (await db.execute(_EXPIRE_SQL)).one()
    summary = {
        "done_at": now.isoformat(),
        "expired_rows": int(row.rows or 0),
        "jobs": int(row.jobs or 0),
    }
    db.add(AppSetting(key=REPAIR_MARKER, value=summary))
    await db.flush()
    return summary


__all__ = ["REPAIR_MARKER", "run_closed_job_proposal_expiry"]
