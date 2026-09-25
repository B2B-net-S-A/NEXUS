"""Jarvis — asystent-agent w shellu aplikacji (0330, zastępuje MINDY).

Trasy są dostępne dla KAŻDEJ zalogowanej osoby (decyzja 21.09.2026) i nie
mają własnej bramki sekcji: narzędzia Jarvisa wracają do aplikacji przez
istniejące trasy z ICH bramkami, tokenem pytającego
(``app/services/jarvis/transport.py``). Rozmowy i akcje są zawsze zawężone do
właściciela — cudza rozmowa odpowiada 404, jak nieistniejąca.

Tryb „podgląd jako” (impersonacja) wyłącza Jarvisa w całości: czat działałby
na cudzych uprawnieniach i pisałby do cudzej historii.

BEZ ``from __future__ import annotations`` — moduł niesie ``@limiter.limit``,
a PEP 563 + slowapi #579 zamieniają guardy ``Annotated`` w wymagane parametry
QUERY (ten sam trap co w ``candidate_activity_summary``).
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Any, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.rate_limit import client_ip_key, limiter, user_or_ip_key
from app.core.scheduling import DEFAULT_TZ, business_today, local_now
from app.models.ai_feature import AIFeatureKey
from app.models.jarvis import (
    JARVIS_UI_EVENTS,
    JarvisAction,
    JarvisConversation,
    JarvisMessage,
    JarvisUiEvent,
)
from app.services.ai_models import model_for
from app.services.jarvis import actions as jarvis_actions
from app.services.jarvis import agent, store
from app.services.jarvis import web as jarvis_web
from app.services.jarvis.prefs import effective_prefs
from app.services.jarvis.tools import build_screen_link, tools_for_user
from app.services.jarvis.transport import CallerIdentity
from app.services.llm_providers import api_key_configured
from app.services.section_permissions import ProductSection, section_access_for_user

logger = logging.getLogger(__name__)

router = APIRouter()

# Zadania tur uruchomione w tle — silne referencje, żeby GC nie zebrał
# zadania, którego klient się rozłączył (tura i tak dokończy się i zapisze).
_RUNNING: set[asyncio.Task] = set()
_HEARTBEAT_SECONDS = 10.0


# ── schematy ───────────────────────────────────────────────────────────────


class JarvisEntity(BaseModel):
    type: Literal["candidate", "job", "client", "contract"]
    id: int = Field(ge=1)


class JarvisScreen(BaseModel):
    path: str = Field(default="", max_length=300)
    entity: Optional[JarvisEntity] = None
    # Klucz przewodnika ekranu (``app/data/screen_guides``); nieznany klucz
    # jest ignorowany w kontekście, więc stary front nie psuje niczego.
    key: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_.]{1,60}$")


class JarvisChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[uuid.UUID] = None
    screen: Optional[JarvisScreen] = None
    # Przełącznik „Szukaj w internecie” — działa tylko w tej jednej turze.
    web: bool = False


class JarvisStatusResponse(BaseModel):
    available: bool
    reason: Optional[str] = None
    used_today: int = 0
    soft_limit: int
    busy: bool = False
    web_enabled: bool = False
    web_used_today: int = 0
    web_limit: int = 0


class JarvisConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime


class JarvisUiEventIn(BaseModel):
    """Telemetria pomocy na ekranie — klucz ekranu i kod, nigdy dane rekordu."""

    event: Literal[
        "bubble_shown",
        "bubble_clicked",
        "bubble_dismissed",
        "guide_opened",
        "guide_task",
        "highlight_shown",
        "highlight_missing",
        "stuck_shown",
        "stuck_clicked",
    ]
    screen_key: Optional[str] = Field(default=None, pattern=r"^[a-z0-9_.]{1,60}$")
    detail: Optional[str] = Field(default=None, pattern=r"^[A-Za-z0-9_.:-]{1,60}$")


class JarvisActionOutcomeResponse(BaseModel):
    action: dict[str, Any]
    message: str
    follow_up: Optional[dict[str, Any]] = None
    invalidates: list[list[str]] = []


# ── pomocniki ──────────────────────────────────────────────────────────────


def _impersonating(request: Request) -> bool:
    return getattr(request.state, "impersonator_id", None) is not None


def _require_available(request: Request) -> None:
    if _impersonating(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Jarvis jest niedostępny w trybie podglądu jako inny użytkownik.",
        )
    if not settings.JARVIS_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Jarvis jest chwilowo wyłączony.",
        )


def _identity(request: Request) -> CallerIdentity:
    authorization = request.headers.get("authorization") or ""
    return CallerIdentity(
        authorization=authorization,
        forwarded_for=client_ip_key(request),
        operation_id=str(uuid.uuid4()),
    )


def _section_map(user: Any) -> dict[ProductSection, int]:
    return {
        section: int(section_access_for_user(user, section))
        for section in ProductSection
    }


def _roles(user: Any) -> list[str]:
    try:
        return sorted(
            getattr(role, "value", str(role)) for role in user.get_all_roles()
        )
    except Exception:  # noqa: BLE001
        return [getattr(user.role, "value", str(user.role))]


def _today_start_utc() -> datetime:
    """Warszawska północ „dziś", przeliczona na UTC (kolumny są w UTC).

    Do 22.09.2026 północ warszawskiej daty była OZNACZANA jako UTC, więc między
    22:00 a 24:00 UTC (00:00–02:00 w Warszawie) początek doby leżał w
    przyszłości: licznik dzienny i limit wyszukiwań w internecie pokazywały 0,
    a testy licznika padały w nocnych biegach kolejki merge'ów.
    """
    today = business_today()
    return datetime.combine(today, time.min, tzinfo=ZoneInfo(DEFAULT_TZ)).astimezone(
        timezone.utc
    )


async def _used_today(db: AsyncSession, user_id: int, *, web: bool = False) -> int:
    # Blok 0 to zawsze kontekst; tura z internetem ma notatkę trybu w bloku 1.
    marker = (
        JarvisMessage.content[1]["text"].astext
        if web
        else JarvisMessage.content[0]["text"].astext
    )
    pattern = f"{jarvis_web.WEB_MARKER}%" if web else "[Kontekst%"
    return int(
        await db.scalar(
            select(func.count())
            .select_from(JarvisMessage)
            .join(
                JarvisConversation,
                JarvisConversation.id == JarvisMessage.conversation_id,
            )
            .where(
                JarvisConversation.user_id == user_id,
                JarvisMessage.role == "user",
                JarvisMessage.created_at >= _today_start_utc(),
                marker.like(pattern),
            )
        )
        or 0
    )


def _sse(event: dict[str, Any]) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"


async def _stream(events: AsyncIterator[dict[str, Any]]) -> AsyncIterator[str]:
    """Tura w osobnym zadaniu + kolejka: heartbeat co 10 s, a rozłączenie
    klienta NIE przerywa tury (dokończy się i zapisze w historii)."""
    queue: asyncio.Queue = asyncio.Queue()

    async def produce() -> None:
        try:
            async for event in events:
                await queue.put(event)
        except Exception:  # noqa: BLE001
            logger.exception("jarvis: tura przerwana błędem")
            await queue.put(
                {
                    "type": "error",
                    "message": agent.UNAVAILABLE_MESSAGE,
                    "code": "internal",
                }
            )
        finally:
            await queue.put(None)

    task = asyncio.create_task(produce())
    _RUNNING.add(task)
    task.add_done_callback(_RUNNING.discard)
    while True:
        try:
            event = await asyncio.wait_for(queue.get(), timeout=_HEARTBEAT_SECONDS)
        except asyncio.TimeoutError:
            yield ": ping\n\n"
            continue
        if event is None:
            return
        yield _sse(event)


_SSE_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
    "Connection": "keep-alive",
}


# ── trasy ──────────────────────────────────────────────────────────────────


@router.get("/status", response_model=JarvisStatusResponse)
async def jarvis_status(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    soft_limit = settings.JARVIS_DAILY_SOFT_LIMIT
    if _impersonating(request):
        return JarvisStatusResponse(
            available=False, reason="impersonation", soft_limit=soft_limit
        )
    if not settings.JARVIS_ENABLED:
        return JarvisStatusResponse(
            available=False, reason="disabled", soft_limit=soft_limit
        )
    if not api_key_configured(model_for(AIFeatureKey.jarvis)):
        return JarvisStatusResponse(
            available=False, reason="not_configured", soft_limit=soft_limit
        )
    busy = await db.scalar(
        select(func.count())
        .select_from(JarvisConversation)
        .where(
            JarvisConversation.user_id == current_user.id,
            JarvisConversation.busy_until > func.now(),
        )
    )
    return JarvisStatusResponse(
        available=True,
        used_today=await _used_today(db, current_user.id),
        soft_limit=soft_limit,
        busy=bool(busy),
        web_enabled=settings.JARVIS_WEB_ENABLED,
        web_used_today=await _used_today(db, current_user.id, web=True),
        web_limit=settings.JARVIS_WEB_DAILY_LIMIT,
    )


@router.post("/chat")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def jarvis_chat(
    request: Request,
    payload: JarvisChatRequest,
    current_user: CurrentUser,
):
    _require_available(request)
    if payload.web:
        if not settings.JARVIS_WEB_ENABLED:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Wyszukiwanie w internecie jest wyłączone.",
            )
        async with AsyncSessionLocal() as count_db:
            used = await _used_today(count_db, current_user.id, web=True)
        if used >= settings.JARVIS_WEB_DAILY_LIMIT:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Dzisiejszy limit wyszukiwań w internecie ({settings.JARVIS_WEB_DAILY_LIMIT}) "
                    "jest wyczerpany. Pytania o dane w NEXUSIE działają dalej."
                ),
            )
    prefs = effective_prefs(current_user.jarvis_prefs)
    turn = agent.TurnInput(
        user_id=current_user.id,
        user_name=current_user.name,
        roles=_roles(current_user),
        message=payload.message.strip(),
        conversation_id=payload.conversation_id,
        # W trybie internetu nie podajemy nawet ID rekordu z ekranu.
        screen=None
        if payload.web
        else (payload.screen.model_dump() if payload.screen else None),
        assistant_name=prefs.name,
        allowed_tools=tools_for_user(_section_map(current_user)),
        identity=_identity(request),
        today=business_today(),
        now=local_now(),
        notes=[] if payload.web else list(prefs.notes),
        sections={s.value: v for s, v in _section_map(current_user).items()},
        web=payload.web,
    )
    try:
        claimed = await agent.claim(turn)
    except store.TurnBusy:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Jarvis jeszcze odpowiada na poprzednie pytanie — poczekaj chwilę.",
        )
    except store.ConversationNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Nie ma takiej rozmowy."
        )
    return StreamingResponse(
        _stream(agent.run_turn(turn, claimed)),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )


@router.get("/conversations", response_model=list[JarvisConversationSummary])
async def list_conversations(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    if _impersonating(request):
        return []
    rows = (
        await db.execute(
            select(
                JarvisConversation.id,
                JarvisConversation.title,
                JarvisConversation.updated_at,
            )
            .where(JarvisConversation.user_id == current_user.id)
            .order_by(JarvisConversation.updated_at.desc())
            .limit(30)
        )
    ).all()
    return [
        JarvisConversationSummary(id=r.id, title=r.title, updated_at=r.updated_at)
        for r in rows
    ]


def _anchor_label(anchor_id: str) -> str:
    from app.data.screen_guides import load_guides

    for guide in load_guides().values():
        for anchor in guide.anchors:
            if anchor.id == anchor_id:
                return anchor.label
    return "Element ekranu"


def _conversation_items(
    messages: list[tuple[str, list[dict[str, Any]]]], actions: list[JarvisAction]
) -> list[dict[str, Any]]:
    by_tool_use: dict[str, list[JarvisAction]] = {}
    for action in actions:
        by_tool_use.setdefault(action.tool_use_id, []).append(action)
    items: list[dict[str, Any]] = []
    for role, blocks in messages:
        # Kolejne bloki tekstu jednej wiadomości asystenta to jeden akapit
        # (odpowiedź z cytatami przychodzi pocięta) — jeden dymek, nie 24.
        pending: list[str] = []

        def flush() -> None:
            text = jarvis_web.join_text(pending)
            pending.clear()
            if text:
                items.append({"kind": "message", "role": role, "markdown": text})

        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                text = str(block.get("text") or "")
                if role == "user" and (
                    text.startswith("[Kontekst")
                    or text.startswith("[Wynik akcji]")
                    or text.startswith(jarvis_web.WEB_MARKER)
                ):
                    continue
                if text.strip():
                    pending.append(text)
                continue
            flush()
            if kind == jarvis_web.SOURCES_BLOCK and role == "assistant":
                sources = [i for i in block.get("items") or [] if isinstance(i, dict)]
                if sources:
                    items.append({"kind": "sources", "items": sources})
            elif kind == "tool_use" and role == "assistant":
                name = block.get("name")
                if name == "show_on_screen":
                    anchor = str((block.get("input") or {}).get("anchor") or "")
                    if anchor:
                        items.append(
                            {
                                "kind": "highlight",
                                "anchor": anchor,
                                "label": _anchor_label(anchor),
                                "reason": str(
                                    (block.get("input") or {}).get("reason") or ""
                                )[:200],
                            }
                        )
                if name == "open_screen":
                    try:
                        items.append(
                            {
                                "kind": "link",
                                **build_screen_link(dict(block.get("input") or {})),
                            }
                        )
                    except (ValueError, TypeError):
                        continue
                for action in by_tool_use.get(str(block.get("id") or ""), []):
                    items.append(
                        {
                            "kind": "action",
                            "action": jarvis_actions.serialize_action(action),
                        }
                    )
        flush()
    return items


@router.get("/conversations/{conversation_id}")
async def get_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    _require_available(request)
    conversation = await db.scalar(
        select(JarvisConversation).where(
            JarvisConversation.id == conversation_id,
            JarvisConversation.user_id == current_user.id,
        )
    )
    if conversation is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rozmowy.")
    await store.expire_stale_actions(settings.JARVIS_ACTION_TTL_MINUTES)
    messages = (
        await db.execute(
            select(JarvisMessage.role, JarvisMessage.content)
            .where(JarvisMessage.conversation_id == conversation_id)
            .order_by(JarvisMessage.id)
        )
    ).all()
    actions = list(
        (
            await db.execute(
                select(JarvisAction)
                .where(JarvisAction.conversation_id == conversation_id)
                .order_by(JarvisAction.created_at)
            )
        ).scalars()
    )
    return {
        "id": str(conversation.id),
        "title": conversation.title,
        "updated_at": conversation.updated_at,
        "items": _conversation_items([(r.role, r.content) for r in messages], actions),
    }


@router.delete(
    "/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_conversation(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    if _impersonating(request):
        raise HTTPException(
            status_code=403, detail="Tryb podglądu jest tylko do odczytu."
        )
    result = await db.execute(
        delete(JarvisConversation).where(
            JarvisConversation.id == conversation_id,
            JarvisConversation.user_id == current_user.id,
        )
    )
    if not result.rowcount:
        raise HTTPException(status_code=404, detail="Nie ma takiej rozmowy.")
    await db.commit()


@router.post(
    "/conversations/{conversation_id}/cancel",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def cancel_turn(
    conversation_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """„Zatrzymaj” — tura kończy się po bieżącym kroku (model w wątku nie
    daje się przerwać w połowie odpowiedzi)."""
    _require_available(request)
    owned = await db.scalar(
        select(JarvisConversation.id).where(
            JarvisConversation.id == conversation_id,
            JarvisConversation.user_id == current_user.id,
        )
    )
    if owned is None:
        raise HTTPException(status_code=404, detail="Nie ma takiej rozmowy.")
    agent.request_cancel(conversation_id)


def _outcome_response(
    outcome: jarvis_actions.ActionOutcome,
) -> JarvisActionOutcomeResponse:
    return JarvisActionOutcomeResponse(
        action=outcome.action,
        message=outcome.message,
        follow_up=outcome.follow_up,
        invalidates=[list(key) for key in outcome.invalidates],
    )


def _action_error(exc: Exception) -> HTTPException:
    if isinstance(exc, jarvis_actions.ActionNotFound):
        return HTTPException(status_code=404, detail="Nie ma takiej akcji.")
    assert isinstance(exc, jarvis_actions.ActionNotPending)
    label = {
        "confirmed": "Ta akcja jest już wykonywana.",
        "executed": "Ta akcja została już wykonana.",
        "failed": "Ta akcja już się nie powiodła — poproś Jarvisa o nową.",
        "rejected": "Ta akcja została anulowana.",
        "expired": "Ta propozycja wygasła — poproś Jarvisa o nową.",
    }.get(exc.status, "Tej akcji nie można już zmienić.")
    return HTTPException(status_code=409, detail=label)


@router.post("/actions/{action_id}/confirm", response_model=JarvisActionOutcomeResponse)
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def confirm_action(
    action_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
):
    _require_available(request)
    try:
        outcome = await jarvis_actions.confirm_action(
            action_id, user_id=current_user.id, identity=_identity(request)
        )
    except (jarvis_actions.ActionNotFound, jarvis_actions.ActionNotPending) as exc:
        raise _action_error(exc)
    return _outcome_response(outcome)


@router.post("/actions/{action_id}/reject", response_model=JarvisActionOutcomeResponse)
async def reject_action(
    action_id: uuid.UUID,
    request: Request,
    current_user: CurrentUser,
):
    _require_available(request)
    try:
        outcome = await jarvis_actions.reject_action(action_id, user_id=current_user.id)
    except (jarvis_actions.ActionNotFound, jarvis_actions.ActionNotPending) as exc:
        raise _action_error(exc)
    return _outcome_response(outcome)


# ── telemetria pomocy na ekranie (0355) ────────────────────────────────────


@router.post("/ui-events", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def record_ui_event(
    request: Request,
    payload: JarvisUiEventIn,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Dymek pokazany/kliknięty, przewodnik otwarty, element podświetlony.

    W trybie podglądu nic nie zapisujemy (to nie są kliknięcia tej osoby)."""
    if _impersonating(request):
        return
    db.add(
        JarvisUiEvent(
            user_id=current_user.id,
            event=payload.event,
            screen_key=payload.screen_key,
            detail=payload.detail,
        )
    )
    await db.commit()


@router.get("/ui-events/summary")
async def ui_events_summary(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    days: int = 14,
) -> dict[str, Any]:
    """Liczniki per zdarzenie × ekran — do decyzji, co wyłączyć (admin)."""
    window = max(1, min(int(days), 90))
    since = datetime.now(timezone.utc) - timedelta(days=window)
    rows = (
        await db.execute(
            select(
                JarvisUiEvent.event,
                JarvisUiEvent.screen_key,
                func.count().label("n"),
                func.count(func.distinct(JarvisUiEvent.user_id)).label("people"),
            )
            .where(JarvisUiEvent.created_at >= since)
            .group_by(JarvisUiEvent.event, JarvisUiEvent.screen_key)
            .order_by(JarvisUiEvent.screen_key, JarvisUiEvent.event)
        )
    ).all()
    return {
        "days": window,
        "events": list(JARVIS_UI_EVENTS),
        "rows": [
            {
                "event": r.event,
                "screen_key": r.screen_key,
                "count": int(r.n),
                "people": int(r.people),
            }
            for r in rows
        ],
    }
