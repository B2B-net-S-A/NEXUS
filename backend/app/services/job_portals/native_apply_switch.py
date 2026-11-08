"""Jednorazowo: wiszące ogłoszenia JustJoin.IT na formularz portalu (08.11.2026).

Pięć ogłoszeń z 05–06.11 poszło przed ``JJIT_APPLY_EMAIL``, więc „Apply” prowadzi
na stronę kariery. Decyzja Artura: przełączyć je zwykłą aktualizacją, którą robi
worker. Aktualizacja nie zużywa kredytu. Bez ustawionego formularza krok nic nie
robi i nie zostawia znacznika, żeby nie wysłać znowu linku do strony kariery.

Znacznik w ``app_settings`` + advisory lock: drugi start kończy się od razu.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_setting import AppSetting
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.services.job_portals import jjit_payload
from app.services.job_portals.service import ACTION_UPDATE, _queue

REPAIR_MARKER = "jjit_native_apply_switch_2026_11"
POSTING_IDS = (17, 18, 19, 20, 21)


async def run_native_apply_switch(
    db: AsyncSession, *, posting_ids: Iterable[int] = POSTING_IDS
) -> Optional[dict[str, Any]]:
    """Kolejkuje aktualizację. ``None`` = wykonane albo brak formularza.

    Wołający commituje.
    """
    if not jjit_payload.native_apply_enabled():
        return None
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": REPAIR_MARKER}
    )
    if await db.get(AppSetting, REPAIR_MARKER) is not None:
        return None
    rows = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.id.in_(tuple(posting_ids)),
                JobPosting.portal == Portal.justjoinit,
                JobPosting.status == PostingStatus.published,
                JobPosting.pending_action.is_(None),
            )
            .with_for_update()
        )
    ).all()
    for posting in rows:
        _queue(posting, ACTION_UPDATE)
    summary = {"queued": len(rows)}
    db.add(AppSetting(key=REPAIR_MARKER, value=summary))
    await db.flush()
    return summary


__all__ = ["POSTING_IDS", "REPAIR_MARKER", "run_native_apply_switch"]
