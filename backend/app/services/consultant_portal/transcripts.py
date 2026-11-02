"""Po rozmowie: transkrypt z Teams, podsumowanie AI do sprawy, retencja.

Wzór: ``services/prep_transcripts.py``. Rozmowa bez wideo: spotkanie nagrywa się tylko
tyle, ile wymaga transkrypcja, a trwałe wideo zamyka polityka Teams (wygasanie nagrań),
czego w kodzie nie widać. NEXUS pobiera i trzyma wyłącznie tekst.

Do logu idzie klasa błędu albo kod HTTP, nigdy treść. Podsumowanie jest dodatkiem:
awaria modelu zostawia transkrypt i sprawę bez podsumowania, nic nie blokuje.
Transkrypt widzą prowadzący, kierownik i osoba prowadząca sprawę; konsultant nie.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import httpx
from fastapi.concurrency import run_in_threadpool
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.admin_case import AdminCaseComment
from app.models.ai_feature import AIFeatureKey
from app.models.consultant_portal import CpMeeting
from app.services import teams_vtt
from app.services.consultant_portal import meetings, portal_settings
from app.services.llm_prompts import PORTAL_MEETING_SUMMARY
from app.services.m365 import teams_prep_graph
from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

BATCH = 20
FEATURE = AIFeatureKey.portal_meeting_summary
_BACKOFF_MINUTES = (10, 20, 40, 60, 120, 240, 480, 720)
_FORBIDDEN_RETRY = timedelta(hours=6)
MAX_SUMMARY_CHARS = 200_000
#: Termin do potwierdzenia z IOD (plan, „Poza kodem”).
TRANSCRIPT_RETENTION = timedelta(days=365)
MAX_ACTION_ITEMS = 5
_NETWORK_ERRORS = (GraphRequestError, AppOnlyTokenUnavailable, httpx.HTTPError)


def backoff(attempt: int) -> timedelta:
    index = min(max(attempt, 1), len(_BACKOFF_MINUTES)) - 1
    return timedelta(minutes=_BACKOFF_MINUTES[index])


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def arm_pending(db: AsyncSession, *, now: datetime) -> int:
    """Włącza transkrypcję w spotkaniach, które Graph już opublikował."""

    rows = (
        await db.scalars(
            select(CpMeeting)
            .where(
                CpMeeting.status == "booked",
                CpMeeting.online_meeting_id.is_(None),
                CpMeeting.join_url.is_not(None),
                CpMeeting.end_at > now,
            )
            .limit(BATCH)
        )
    ).all()
    armed = 0
    for meeting in rows:
        try:
            if not meeting.organizer_aad_id:
                meeting.organizer_aad_id = await teams_prep_graph.resolve_user_id(
                    meeting.organizer_upn or ""
                )
            if not meeting.organizer_aad_id:
                meeting.last_error = "no_organizer"
                continue
            online_id = await teams_prep_graph.find_online_meeting(
                meeting.organizer_aad_id, meeting.join_url or ""
            )
            if not online_id:
                continue
            await teams_prep_graph.enable_auto_transcription(
                meeting.organizer_aad_id, online_id
            )
            meeting.online_meeting_id = online_id
            meeting.last_error = None
            armed += 1
        except _NETWORK_ERRORS as exc:
            status = getattr(exc, "status", None)
            meeting.last_error = f"arm:{status or type(exc).__name__}"[:200]
            logger.warning("consultant_portal_transcripts: arm failed %s", status)
    await db.commit()
    return armed


async def process_meeting(
    db: AsyncSession, meeting: CpMeeting, *, now: datetime
) -> str:
    """Jeden krok rozmowy; zwraca stan. Commit robi wołający."""

    end = _aware(meeting.end_at)
    give_up = end + timedelta(hours=settings.TEAMS_PREP_FETCH_GIVE_UP_HOURS)
    ready_at = end + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)
    if ready_at > now:
        meeting.next_fetch_at = ready_at
        return "waiting"
    try:
        if not meeting.organizer_aad_id:
            meeting.organizer_aad_id = await teams_prep_graph.resolve_user_id(
                meeting.organizer_upn or ""
            )
        if (
            meeting.organizer_aad_id
            and not meeting.online_meeting_id
            and meeting.join_url
        ):
            meeting.online_meeting_id = await teams_prep_graph.find_online_meeting(
                meeting.organizer_aad_id, meeting.join_url
            )
        refs = []
        if meeting.organizer_aad_id and meeting.online_meeting_id:
            refs = await teams_prep_graph.list_transcripts(
                meeting.organizer_aad_id, meeting.online_meeting_id
            )
        if not refs:
            meeting.fetch_attempts += 1
            if now >= give_up:
                meeting.transcript_status = "missing"
                meeting.next_fetch_at = None
                meeting.summary_status = "skipped"
                return "missing"
            meeting.transcript_status = "waiting"
            meeting.next_fetch_at = now + backoff(meeting.fetch_attempts)
            return "waiting"
        contents = [
            await teams_prep_graph.transcript_vtt(
                meeting.organizer_aad_id or "", meeting.online_meeting_id or "", ref.id
            )
            for ref in refs
        ]
    except GraphRequestError as exc:
        if exc.status == 403:
            meeting.transcript_status = "forbidden"
            meeting.next_fetch_at = now + _FORBIDDEN_RETRY
            meeting.last_error = "http_403"
            return "forbidden"
        meeting.transcript_status = "error"
        meeting.fetch_attempts += 1
        meeting.next_fetch_at = (
            None if now >= give_up else now + backoff(meeting.fetch_attempts)
        )
        meeting.last_error = f"http_{exc.status}"
        return "error"
    except (AppOnlyTokenUnavailable, httpx.HTTPError) as exc:
        meeting.transcript_status = "error"
        meeting.fetch_attempts += 1
        meeting.next_fetch_at = (
            None if now >= give_up else now + backoff(meeting.fetch_attempts)
        )
        meeting.last_error = type(exc).__name__[:200]
        return "error"
    cues = []
    for raw in contents:
        cues.extend(teams_vtt.parse_vtt(raw))
    if not cues:
        meeting.transcript_status = "missing"
        meeting.next_fetch_at = None
        meeting.summary_status = "skipped"
        meeting.last_error = "empty_transcript"
        return "missing"
    meeting.transcript_text = teams_vtt.render_plain_text(cues)
    meeting.transcript_fetched_at = now
    meeting.transcript_status = "fetched"
    meeting.next_fetch_at = None
    meeting.last_error = None
    return "fetched"


def parse_summary(raw: str) -> tuple[Optional[str], list[dict[str, str]]]:
    """Odpowiedź modelu → podsumowanie i zadania; śmieci dają ``(None, [])``."""

    text = (raw or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except ValueError:
        return None, []
    if not isinstance(data, dict):
        return None, []
    summary = data.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None, []
    items: list[dict[str, str]] = []
    for item in data.get("action_items") or []:
        if (
            isinstance(item, dict)
            and isinstance(item.get("what"), str)
            and item["what"].strip()
        ):
            items.append(
                {
                    "who": str(item.get("who") or "").strip()[:120],
                    "what": item["what"].strip()[:300],
                }
            )
    return summary.strip()[:2000], items[:MAX_ACTION_ITEMS]


def _call_model(chain: list[str], system: str, prompt: str) -> str:
    """Jedno wywołanie modelu (w wątku). Osobna funkcja: testy ją podmieniają."""
    from app.services.claude_client import call_claude_text

    return call_claude_text(
        model=chain[0],
        fallback_models=chain[1:] or None,
        max_tokens=800,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )


def comment_body(summary: str, items: list[dict[str, str]]) -> str:
    lines = [f"Podsumowanie rozmowy z portalu (AI):\n{summary}"]
    if items:
        lines.append("Do zrobienia:")
        lines += [
            f"- {item['who']}: {item['what']}" if item["who"] else f"- {item['what']}"
            for item in items
        ]
    return "\n".join(lines)


async def summarize(db: AsyncSession, meeting_id: int) -> str:
    """Podsumowanie do sprawy. Nie rzuca; wynik modelu jest dodatkiem."""

    from app.services.ai_models import model_chain_for
    from app.services.ai_quota import ai_feature
    from app.services.llm_providers import api_key_configured

    meeting = await db.get(CpMeeting, meeting_id)
    if meeting is None or not meeting.transcript_text:
        return "skipped"
    chain = list(model_chain_for(FEATURE))
    text = meeting.transcript_text
    if not api_key_configured(chain[0]) or len(text) > MAX_SUMMARY_CHARS:
        meeting.summary_status = "skipped"
        await db.commit()
        return "skipped"
    prompt = PORTAL_MEETING_SUMMARY.render(reason=meeting.reason or "", transcript=text)
    summary: Optional[str] = None
    items: list[dict[str, str]] = []
    try:
        async with ai_feature(db, FEATURE):
            await db.commit()  # połączenie wraca do puli na czas modelu
            raw = await run_in_threadpool(
                _call_model, chain, PORTAL_MEETING_SUMMARY.system_prompt or "", prompt
            )
        summary, items = parse_summary(raw)
    except Exception as exc:  # noqa: BLE001 — AI to dodatek, nigdy bramka
        logger.warning(
            "consultant_portal_transcripts: summary failed (%s)", type(exc).__name__
        )
        await db.rollback()
    meeting = await db.get(CpMeeting, meeting_id)
    if meeting is None:
        return "skipped"
    if summary is None:
        meeting.summary_status = "failed"
        await db.commit()
        return "failed"
    meeting.summary = summary
    meeting.action_items = items
    meeting.summary_status = "done"
    if meeting.case_id:
        db.add(
            AdminCaseComment(
                case_id=meeting.case_id,
                author_user_id=None,
                body=comment_body(summary, items),
            )
        )
    await db.commit()
    return "done"


async def purge_expired(db: AsyncSession, *, now: datetime) -> int:
    result = await db.execute(
        update(CpMeeting)
        .where(
            CpMeeting.transcript_text.is_not(None),
            CpMeeting.end_at < now - TRANSCRIPT_RETENTION,
        )
        .values(transcript_text=None, summary=None, transcript_purged_at=now)
    )
    await db.commit()
    return result.rowcount or 0


async def run_once(
    db: AsyncSession, *, now: Optional[datetime] = None
) -> dict[str, Any]:
    moment = now or datetime.now(timezone.utc)
    state = await portal_settings.load(db)
    if not state.is_on or not meetings.booking_ready():
        return {"status": "disabled"}
    armed = await arm_pending(db, now=moment)
    ids = (
        await db.scalars(
            select(CpMeeting.id)
            .where(
                CpMeeting.status == "booked",
                CpMeeting.next_fetch_at.is_not(None),
                CpMeeting.next_fetch_at <= moment,
            )
            .order_by(CpMeeting.next_fetch_at)
            .limit(BATCH)
        )
    ).all()
    stats: dict[str, int] = {}
    for meeting_id in ids:
        meeting = await db.get(CpMeeting, meeting_id)
        if meeting is None:
            continue
        outcome = await process_meeting(db, meeting, now=moment)
        stats[outcome] = stats.get(outcome, 0) + 1
        await db.commit()
        if outcome == "fetched":
            await summarize(db, meeting_id)
    return {
        "status": "ok",
        "armed": armed,
        "meetings": stats,
        "purged": await purge_expired(db, now=moment),
    }
