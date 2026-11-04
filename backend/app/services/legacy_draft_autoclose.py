"""Stare szkice rekrutacji zamykają się same 7 dni po wdrożeniu (04.10.2026).

Od decyzji Artura z 04.10.2026 rekrutacja nigdy nie jest szkicem — utworzenie
= przekazanie do searchu = publikacja. Szkice założone wcześniej (14 z 40
rekrutacji z NEXUSA od 25.09) mają tydzień na dokończenie („Dokończ
i opublikuj” na pulpicie), potem zamykają się same:

- start okna = ``app_settings['legacy_draft_autoclose:deployed_at']``
  (zakłada go ``entrypoint.sh`` i migracja 0415 przy pierwszym starcie),
- zamknięcie tą samą drogą co ręczne (``job_lifecycle.close_job_core``):
  ``close_reason=other`` z notatką, bez autora, bez nowej wartości enuma,
- **nic nie jest kasowane** — zamkniętą rekrutację da się otworzyć ponownie
  (``POST /api/jobs/{id}/publish`` przez bramkę przekazania),
- jednorazowo: paragon ``legacy_draft_autoclose:receipt`` z samymi ID; jego
  obecność kończy każdy kolejny przebieg od razu.

Woła to dobowa pętla alertów terminów (``tasks/job_deadline_alerts.run_once``)
pod blokadą doradczą — dwa kontenery przy deployu nie zamkną tego samego.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.models.job import Job, JobCloseReason, JobStatus

logger = logging.getLogger(__name__)

DEPLOYED_KEY = "legacy_draft_autoclose:deployed_at"
RECEIPT_KEY = "legacy_draft_autoclose:receipt"
GRACE = timedelta(days=7)
CLOSE_NOTE = (
    "Zamknięta automatycznie: szkic niedokończony po przejściu na rekrutacje "
    "bez szkiców"
)
# Stały klucz blokady doradczej (jedna instancja przebiegu naraz).
_LOCK_ID = 414_0410_04


def _parse_moment(value: Any) -> Optional[datetime]:
    raw = value.get("deployed_at") if isinstance(value, dict) else value
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        moment = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
    except ValueError:
        logger.warning("legacy_draft_autoclose: nieczytelny znacznik startu okna")
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment


async def deployed_at(db: AsyncSession) -> Optional[datetime]:
    """Start okna (moment wdrożenia) albo ``None`` bez znacznika."""
    value = await db.scalar(
        select(AppSetting.value).where(AppSetting.key == DEPLOYED_KEY)
    )
    return _parse_moment(value)


async def legacy_draft_autoclose_on(db: AsyncSession) -> Optional[date]:
    """Dzień (kalendarz firmy), od którego stare szkice zamykają się same.

    ``None`` = brak znacznika startu albo przebieg już się odbył (paragon) —
    pulpit nie pokazuje wtedy odliczania.
    """
    if await db.scalar(select(AppSetting.key).where(AppSetting.key == RECEIPT_KEY)):
        return None
    start = await deployed_at(db)
    if start is None:
        return None
    return (start + GRACE).astimezone(ZoneInfo(settings.BUSINESS_TZ)).date()


async def run_legacy_draft_autoclose(
    db: AsyncSession,
    effects: Any,
    *,
    now: Optional[datetime] = None,
) -> Optional[dict]:
    """Zamknij stare szkice, gdy minęło 7 dni od wdrożenia — bez commitu.

    Zwraca paragon (``closed_ids``, ``count``, ``at``) albo ``None``, gdy nic
    nie było do zrobienia (blokada zajęta, paragon już jest, brak znacznika,
    okno jeszcze trwa). Wołający commituje i uruchamia ``effects``.
    """
    from app.services.job_lifecycle import close_job_core

    acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(:lock_id)"), {"lock_id": _LOCK_ID}
    )
    if not acquired:
        return None
    if await db.scalar(select(AppSetting.key).where(AppSetting.key == RECEIPT_KEY)):
        return None
    start = await deployed_at(db)
    if start is None:
        return None
    moment = now or datetime.now(timezone.utc)
    if moment < start + GRACE:
        return None

    drafts = (
        await db.scalars(
            select(Job)
            .where(Job.status == JobStatus.draft)
            .order_by(Job.id)
            .with_for_update()
        )
    ).all()
    closed_ids: list[int] = []
    for job in drafts:
        await close_job_core(
            db,
            job,
            reason=JobCloseReason.other,
            notes=CLOSE_NOTE,
            actor_id=None,
            effects=effects,
        )
        # Szkic nigdy nie był w pracy — nie może trafić do mianownika hit
        # ratio Ligi DL, celu DL i Portfeli DL (rekrutacje zamknięte w oknie
        # po `closed_at`). Ta sama reguła co przy archiwum
        # (`job_archive_cutover`): `closed_at` zostaje pusty. Audyt 05.10.2026.
        job.closed_at = None
        closed_ids.append(job.id)
    receipt = {
        "closed_ids": closed_ids,
        "count": len(closed_ids),
        "at": moment.isoformat(),
    }
    db.add(AppSetting(key=RECEIPT_KEY, value=receipt))
    await db.flush()
    logger.info("legacy_draft_autoclose: zamknięto %s szkiców", len(closed_ids))
    return receipt


async def run_once_safely() -> Optional[dict]:
    """Własna sesja, commit, efekty po commicie; nigdy nie rzuca."""
    from app.core.database import AsyncSessionLocal
    from app.services.job_lifecycle import PostCommit, run_post_commit

    effects = PostCommit()
    try:
        async with AsyncSessionLocal() as db:
            receipt = await run_legacy_draft_autoclose(db, effects)
            await db.commit()
    except Exception:  # noqa: BLE001 — pętla alertów nie może przez to stanąć
        logger.exception("legacy_draft_autoclose: przebieg nie powiódł się")
        return None
    if receipt is not None:
        await run_post_commit(effects)
    return receipt
