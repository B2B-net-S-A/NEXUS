"""Rezerwacje przebiegów w ``hr_job_runs`` dla zadań dziennych Microsoft 365.

Wzór jak w ``reconcile.py``: wiersz (rodzaj, klucz okresu) wstawiany raz;
przebieg nieudany albo porzucony (rezerwacja bez końca dłużej niż
``STALE_CLAIM``) można przejąć ponownie, zakończony — nie.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Optional

from sqlalchemy import func, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_ops import HrJobRun

#: Rezerwacja starsza niż tyle bez zakończenia = przebieg przerwany.
STALE_CLAIM = timedelta(hours=1)


async def claim(
    db: AsyncSession, kind: str, period_key: str, now: datetime
) -> Optional[int]:
    row = await db.execute(
        text(
            "INSERT INTO hr_job_runs (kind, period_key, status) "
            "VALUES (:kind, :period, 'claimed') "
            "ON CONFLICT (kind, period_key) DO UPDATE "
            "SET status = 'claimed', claimed_at = now(), error = NULL, finished_at = NULL "
            "WHERE hr_job_runs.status = 'failed' "
            "OR (hr_job_runs.status = 'claimed' AND hr_job_runs.claimed_at < :stale) "
            "RETURNING id"
        ),
        {"kind": kind, "period": period_key, "stale": now - STALE_CLAIM},
    )
    claimed = row.scalar_one_or_none()
    await db.commit()
    return claimed


async def finish(
    db: AsyncSession,
    run_id: int,
    *,
    status: str,
    counts: dict[str, Any],
    error: Optional[str] = None,
) -> None:
    await db.execute(
        update(HrJobRun)
        .where(HrJobRun.id == run_id)
        .values(status=status, counts=counts, error=error, finished_at=func.now())
    )
    await db.commit()
