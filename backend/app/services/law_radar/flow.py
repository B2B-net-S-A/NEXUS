"""Kolejność kroków radaru: Zbieracz → bramka → Analityk → sondy.

Boty nie rozmawiają ze sobą: po przyjęciu raportu Zbieracza NEXUS sam sprawdza
numery (``gate.verify_pending``), a Analityk startuje dopiero z pozycjami po
bramce. Sondy liczy NEXUS po raporcie Analityka (trasa przyjęcia) i raz dziennie
(pętla).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date
from app.models.law_radar import LawChange, LawRadarItem, LawRadarRun
from app.services.law_radar import analyze, collect, gate, runs, schema

logger = logging.getLogger(__name__)

#: Pozycja czeka na Analityka najwyżej tyle; starsza nie trafia do zlecenia.
ANALYZE_WINDOW = timedelta(days=14)


async def last_received_collect(db: AsyncSession) -> Optional[datetime]:
    return await db.scalar(
        select(func.max(LawRadarRun.started_at)).where(
            LawRadarRun.kind == collect.KIND, LawRadarRun.status == "received"
        )
    )


async def open_run(db: AsyncSession, kind: str) -> Optional[LawRadarRun]:
    """Bieg rodzaju, który wciąż czeka na raport."""

    return await db.scalar(
        select(LawRadarRun)
        .where(LawRadarRun.kind == kind, LawRadarRun.status == "started")
        .order_by(LawRadarRun.id.desc())
        .limit(1)
    )


async def collect_request(db: AsyncSession, *, now: datetime) -> dict[str, Any]:
    """``since`` = dzień startu ostatniego przyjętego biegu, domyślnie dziś − 3 dni."""

    last = await last_received_collect(db)
    since = (
        business_date(last)
        if last is not None
        else business_date(now) - timedelta(days=collect.DEFAULT_LOOKBACK_DAYS)
    )
    return collect.build_request(since)


async def start_collect(
    db: AsyncSession,
    *,
    now: datetime,
    client: Optional[httpx.AsyncClient] = None,
    requested_by_user_id: Optional[int] = None,
) -> Optional[LawRadarRun]:
    if not runs.configured(collect.KIND):
        return None
    request = await collect_request(db, now=now)
    return await runs.start_run(
        db,
        collect.KIND,
        request,
        now=now,
        client=client,
        requested_by_user_id=requested_by_user_id,
    )


async def analyze_request(
    db: AsyncSession, *, now: datetime
) -> Optional[dict[str, Any]]:
    """Zlecenie Analityka z pozycji po bramce, jeszcze nieanalizowanych."""

    items = (
        (
            await db.execute(
                select(LawRadarItem)
                .where(
                    LawRadarItem.gate.in_(("verified", "unverified")),
                    LawRadarItem.analyzed_at.is_(None),
                    LawRadarItem.created_at >= now - ANALYZE_WINDOW,
                )
                .order_by(LawRadarItem.id)
                .limit(analyze.MAX_REQUEST_ITEMS)
            )
        )
        .scalars()
        .all()
    )
    if not items:
        return None
    open_changes = (
        await db.execute(
            select(LawChange.id, LawChange.title, LawChange.legal_ref)
            .where(LawChange.status.in_(schema.OPEN_STATUSES))
            .order_by(LawChange.updated_at.desc())
            .limit(analyze.MAX_OPEN_CHANGES)
        )
    ).all()
    return analyze.build_request(
        [analyze.item_payload(item) for item in items],
        [
            {"id": cid, "title": title, "legal_ref": legal_ref}
            for cid, title, legal_ref in open_changes
        ],
        topics=collect.PROFILE_TOPICS,
    )


async def start_analyze(
    db: AsyncSession,
    *,
    now: datetime,
    parent_run_id: Optional[int] = None,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[LawRadarRun]:
    """Bieg Analityka, gdy są pozycje po bramce i żaden bieg nie czeka."""

    if not runs.configured(analyze.KIND):
        return None
    if await open_run(db, analyze.KIND) is not None:
        return None
    request = await analyze_request(db, now=now)
    if request is None:
        return None
    return await runs.start_run(
        db,
        analyze.KIND,
        request,
        now=now,
        client=client,
        parent_run_id=parent_run_id,
    )


async def record_gate(db: AsyncSession, run_id: int, checked: dict[str, int]) -> None:
    """Wynik bramki w raporcie biegu Zbieracza (ekran „Boty dziś”): same liczby."""

    run = await db.get(LawRadarRun, run_id)
    if run is None:
        return
    counts = {
        key: int(checked.get(key, 0)) for key in ("verified", "unverified", "rejected")
    }
    run.report = {**(run.report or {}), "gate": counts}
    await db.commit()


async def after_collect(
    db: AsyncSession,
    run_id: int,
    *,
    gate_client: Optional[httpx.AsyncClient] = None,
    bot_client: Optional[httpx.AsyncClient] = None,
) -> dict[str, Any]:
    """Bramka dla pozycji biegu, potem Analityk, gdy coś przeszło."""

    checked = await gate.verify_pending(db, run_id=run_id, client=gate_client)
    await record_gate(db, run_id, checked)
    passed = checked["verified"] + checked["unverified"]
    started = None
    if passed:
        started = await start_analyze(
            db,
            now=datetime.now(timezone.utc),
            parent_run_id=run_id,
            client=bot_client,
        )
    return {
        **checked,
        "analyze_run_id": started.id if started is not None else None,
    }


async def after_collect_in_background(run_id: int) -> None:
    """Wersja dla ``spawn`` z trasy przyjęcia: własna sesja."""

    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await after_collect(db, run_id)
