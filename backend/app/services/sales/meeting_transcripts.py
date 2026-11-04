"""Transkrypty Teams spotkań handlowców (decyzje Artura 02.11.2026).

Spotkanie trafia do kolejki z synchronizacji kalendarza, gdy handlowiec jest jego
organizatorem. Adres spotkania czytamy jego tokenem podczas synchronizacji, bo
aplikacja „NEXUS Teams Prep” nie ma dostępu do kalendarzy handlowców, tylko do
transkryptów: osobna grupa bez automatycznego nagrywania
(``docs/teams-prep-setup.md``). Handlowiec sam włącza transkrypcję, więc brak
transkryptu to zwykły stan, a nie błąd. Podsumowanie modelu jest dodatkiem.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.concurrency import run_in_threadpool

from app.core.config import settings
from app.models.ai_feature import AIFeatureKey
from app.models.sales import SalesActivity, SalesMeetingTranscript
from app.services import teams_vtt
from app.services.ai_quota import ai_feature
from app.services.llm_prompts import SALES_MEETING_SUMMARY
from app.services.m365 import teams_prep_auth, teams_prep_graph
from app.services.m365.graph_client import GraphClient, GraphRequestError
from app.services.prep_transcripts import backoff, parse_contents

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.sales_meeting_summary
BATCH = 20
JOIN_URL_BATCH = 25
MAX_SUMMARY_ATTEMPTS = 3
MAX_SUMMARY_CHARS = 200_000
FORBIDDEN_RETRY = timedelta(hours=6)
# Spotkanie cykliczne ma jeden adres i wspólną listę transkryptów, więc do tego
# wystąpienia należą tylko te, które powstały w jego czasie.
WINDOW_BEFORE = timedelta(hours=1)
WINDOW_AFTER = timedelta(hours=12)


def enabled() -> bool:
    return (
        settings.SALES_TEAMS_TRANSCRIPTS_ENABLED
        and teams_prep_auth.credentials_configured()
    )


def _give_up_at(ends_at: datetime) -> datetime:
    return ends_at + timedelta(hours=settings.TEAMS_PREP_FETCH_GIVE_UP_HOURS)


def _ready_at(ends_at: datetime) -> datetime:
    return ends_at + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)


async def enqueue(
    db: AsyncSession,
    *,
    ical_uid: str,
    graph_event_id: str,
    organizer_user_id: int,
    organizer_upn: str,
    starts_at: datetime,
    ends_at: datetime,
    now: Optional[datetime] = None,
) -> None:
    """Dopisz spotkanie albo odśwież termin. Bez starych spotkań: tylko nowe nagrania."""

    now = now or datetime.now(timezone.utc)
    if not enabled() or now >= _give_up_at(ends_at):
        return
    ready = _ready_at(ends_at)
    statement = pg_insert(SalesMeetingTranscript).values(
        ical_uid=ical_uid,
        organizer_user_id=organizer_user_id,
        organizer_upn=organizer_upn,
        graph_event_id=graph_event_id,
        starts_at=starts_at,
        ends_at=ends_at,
        next_fetch_at=ready,
    )
    await db.execute(
        statement.on_conflict_do_update(
            index_elements=["ical_uid"],
            set_={
                "graph_event_id": graph_event_id,
                "starts_at": starts_at,
                "ends_at": ends_at,
                "next_fetch_at": ready,
                "updated_at": now,
            },
            where=SalesMeetingTranscript.status == "waiting",
        )
    )


async def resolve_join_urls(db: AsyncSession, gc: GraphClient, user_id: int) -> None:
    """Adres spotkania z kalendarza organizatora, jego tokenem z synchronizacji."""

    if not enabled():
        return
    rows = (
        await db.scalars(
            select(SalesMeetingTranscript)
            .where(
                SalesMeetingTranscript.organizer_user_id == user_id,
                SalesMeetingTranscript.status == "waiting",
                SalesMeetingTranscript.join_url.is_(None),
            )
            .order_by(SalesMeetingTranscript.id)
            .limit(JOIN_URL_BATCH)
        )
    ).all()
    for row in rows:
        try:
            event = await gc.get(
                f"/me/events/{row.graph_event_id}",
                params={"$select": "isOrganizer,isOnlineMeeting,onlineMeeting"},
            )
        except GraphRequestError as exc:
            if exc.status in (404, 410):
                row.status = "not_online"
                row.next_fetch_at = None
                continue
            logger.warning("sales_transcripts: join url stopped, Graph %s", exc.status)
            break
        except Exception as exc:  # noqa: BLE001 - transkrypt nie może zatrzymać synchronizacji poczty
            logger.warning(
                "sales_transcripts: join url stopped (%s)", type(exc).__name__
            )
            break
        online = (event or {}).get("onlineMeeting") or {}
        join_url = online.get("joinUrl") if isinstance(online, dict) else None
        if not (event or {}).get("isOrganizer") or not join_url:
            row.status = "not_online"
            row.next_fetch_at = None
            continue
        row.join_url = str(join_url)[:2000]
    await db.commit()


def _utc(value: str) -> Optional[datetime]:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def within_meeting(
    created: Optional[str], starts_at: datetime, ends_at: datetime
) -> bool:
    """Czy transkrypt należy do tego wystąpienia; bez daty przyjmujemy, że tak."""

    moment = _utc(created) if created else None
    if moment is None:
        return True
    return starts_at - WINDOW_BEFORE <= moment <= ends_at + WINDOW_AFTER


def _stop(row: SalesMeetingTranscript, status: str, error: Optional[str]) -> None:
    row.status = status
    row.next_fetch_at = None
    row.last_error = error


async def _fetch_one(row: SalesMeetingTranscript, now: datetime) -> bool:
    if now < _ready_at(row.ends_at):
        row.next_fetch_at = _ready_at(row.ends_at)
        return False
    if not row.organizer_aad_id:
        row.organizer_aad_id = await teams_prep_graph.resolve_user_id(row.organizer_upn)
    if row.organizer_aad_id and not row.online_meeting_id:
        row.online_meeting_id = await teams_prep_graph.find_online_meeting(
            row.organizer_aad_id, row.join_url or ""
        )
    refs = []
    if row.organizer_aad_id and row.online_meeting_id:
        refs = [
            ref
            for ref in await teams_prep_graph.list_transcripts(
                row.organizer_aad_id, row.online_meeting_id
            )
            if within_meeting(ref.created, row.starts_at, row.ends_at)
        ]
    if not refs:
        row.fetch_attempts += 1
        if now >= _give_up_at(row.ends_at):
            _stop(row, "missing", None)
        else:
            row.status = "waiting"
            row.next_fetch_at = now + backoff(row.fetch_attempts)
        return False
    contents = [
        await teams_prep_graph.transcript_vtt(
            row.organizer_aad_id, row.online_meeting_id, ref.id
        )
        for ref in refs
    ]
    cues, _ = parse_contents(contents)
    if not cues:
        _stop(row, "missing", "empty_transcript")
        return False
    row.plain_text = teams_vtt.render_plain_text(cues)
    row.graph_transcript_ids = [ref.id for ref in refs]
    row.fetched_at = now
    _stop(row, "fetched", None)
    return True


def _note_failure(row: SalesMeetingTranscript, now: datetime, code: int) -> None:
    row.fetch_attempts += 1
    row.last_error = f"http_{code}"
    if code == 404:
        _stop(row, "missing", row.last_error)
        return
    row.status = "forbidden" if code == 403 else "error"
    retry = FORBIDDEN_RETRY if code == 403 else backoff(row.fetch_attempts)
    row.next_fetch_at = None if now >= _give_up_at(row.ends_at) else now + retry


async def fetch_due(db: AsyncSession, now: Optional[datetime] = None) -> int:
    """Pobierz należne transkrypty; dzierżawa wiersza jak przy follow-upach."""

    now = now or datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(SalesMeetingTranscript)
            .where(
                SalesMeetingTranscript.status.in_(("waiting", "error", "forbidden")),
                SalesMeetingTranscript.join_url.is_not(None),
                SalesMeetingTranscript.next_fetch_at <= now,
            )
            .order_by(SalesMeetingTranscript.next_fetch_at)
            .limit(BATCH)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for row in rows:
        row.next_fetch_at = now + timedelta(minutes=15)
    ids = [row.id for row in rows]
    await db.commit()
    fetched = 0
    for row_id in ids:
        row = await db.get(SalesMeetingTranscript, row_id, populate_existing=True)
        if row is None:
            continue
        try:
            fetched += int(await _fetch_one(row, now))
            await db.commit()
        except GraphRequestError as exc:
            # Do logu sam kod: treść odpowiedzi Graph może nieść dane spotkania.
            _note_failure(row, now, exc.status)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - jedno spotkanie nie zatrzymuje reszty
            await db.rollback()
            logger.warning(
                "sales_transcripts %s: fetch failed (%s)", row_id, type(exc).__name__
            )
            retry = await db.get(SalesMeetingTranscript, row_id)
            if retry is not None:
                retry.fetch_attempts += 1
                retry.status = "error"
                retry.last_error = type(exc).__name__[:120]
                retry.next_fetch_at = (
                    None
                    if now >= _give_up_at(retry.ends_at)
                    else now + backoff(retry.fetch_attempts)
                )
                await db.commit()
    return fetched


def _call_model(prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""
    from app.services.ai_models import fallbacks_for, model_for  # noqa: PLC0415
    from app.services.claude_client import call_claude_text  # noqa: PLC0415

    return call_claude_text(
        model=model_for(FEATURE),
        fallback_models=fallbacks_for(FEATURE),
        max_tokens=400,
        thinking={"type": "disabled"},
        system=SALES_MEETING_SUMMARY.system_prompt or "",
        messages=[{"role": "user", "content": prompt}],
    )


async def summarize_pending(db: AsyncSession, *, limit: int = 10) -> int:
    """Podsumowania pobranych transkryptów. Awaria modelu zostawia sam transkrypt."""

    from app.services.ai_models import model_for  # noqa: PLC0415
    from app.services.llm_providers import api_key_configured  # noqa: PLC0415

    if not api_key_configured(model_for(FEATURE)):
        return 0
    ids = (
        await db.scalars(
            select(SalesMeetingTranscript.id)
            .where(
                SalesMeetingTranscript.status == "fetched",
                SalesMeetingTranscript.summary.is_(None),
                SalesMeetingTranscript.summary_attempts < MAX_SUMMARY_ATTEMPTS,
            )
            .order_by(SalesMeetingTranscript.id)
            .limit(limit)
        )
    ).all()
    done = 0
    for row_id in ids:
        row = await db.get(SalesMeetingTranscript, row_id, populate_existing=True)
        if row is None or not row.plain_text:
            continue
        row.summary_attempts += 1
        user_id = row.organizer_user_id
        text = row.plain_text
        subject = await db.scalar(
            select(SalesActivity.subject)
            .where(
                SalesActivity.external_source == "msgraph-event",
                SalesActivity.external_id == row.ical_uid,
            )
            .limit(1)
        )
        if len(text) > MAX_SUMMARY_CHARS:
            row.summary_attempts = MAX_SUMMARY_ATTEMPTS
            await db.commit()
            continue
        prompt = SALES_MEETING_SUMMARY.render(
            subject=subject or "(bez tematu)", transcript=text
        )
        try:
            async with ai_feature(db, FEATURE, user_id=user_id):
                await db.commit()  # połączenie wraca do puli na czas modelu
                summary = (await run_in_threadpool(_call_model, prompt)).strip()
        except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
            await db.rollback()
            logger.warning(
                "sales_transcripts %s: summary failed (%s)", row_id, type(exc).__name__
            )
            continue
        row = await db.get(SalesMeetingTranscript, row_id, populate_existing=True)
        if row is not None and summary:
            row.summary = summary
            await db.commit()
            done += 1
    return done


async def run_once(db: AsyncSession) -> None:
    """Jeden obieg pętli ``teams_prep_transcripts``."""

    fetched = await fetch_due(db)
    summarized = await summarize_pending(db)
    if fetched or summarized:
        logger.info("sales_transcripts: fetched=%s summarized=%s", fetched, summarized)
