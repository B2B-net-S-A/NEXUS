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
from datetime import datetime, time, timezone
from typing import Any, AsyncIterator, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import client_ip_key, limiter, user_or_ip_key
from app.core.scheduling import business_today
from app.models.ai_feature import AIFeatureKey
from app.models.jarvis import JarvisAction, JarvisConversation, JarvisMessage
from app.services.ai_models import model_for
from app.services.jarvis import actions as jarvis_actions
from app.services.jarvis import agent, store
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


class JarvisChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: Optional[uuid.UUID] = None
    screen: Optional[JarvisScreen] = None


class JarvisStatusResponse(BaseModel):
    available: bool
    reason: Optional[str] = None
    used_today: int = 0
    soft_limit: int
    busy: bool = False


class JarvisConversationSummary(BaseModel):
    id: uuid.UUID
    title: str
    updated_at: datetime


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
    today = business_today()
    return datetime.combine(today, time.min).replace(tzinfo=timezone.utc)


async def _used_today(db: AsyncSession, user_id: int) -> int:
    marker = JarvisMessage.content[0]["text"].astext
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
                marker.like("[Kontekst%"),
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
    )


@router.post("/chat")
@limiter.limit("20/minute", key_func=user_or_ip_key)
async def jarvis_chat(
    request: Request,
    payload: JarvisChatRequest,
    current_user: CurrentUser,
):
    _require_available(request)
    prefs = effective_prefs(current_user.jarvis_prefs)
    turn = agent.TurnInput(
        user_id=current_user.id,
        user_name=current_user.name,
        roles=_roles(current_user),
        message=payload.message.strip(),
        conversation_id=payload.conversation_id,
        screen=payload.screen.model_dump() if payload.screen else None,
        assistant_name=prefs.name,
        allowed_tools=tools_for_user(_section_map(current_user)),
        identity=_identity(request),
        today=business_today(),
    )
    try:
        conversation_id = await agent.claim(turn)
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
        _stream(agent.run_turn(turn, conversation_id)),
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


def _conversation_items(
    messages: list[tuple[str, list[dict[str, Any]]]], actions: list[JarvisAction]
) -> list[dict[str, Any]]:
    by_tool_use: dict[str, list[JarvisAction]] = {}
    for action in actions:
        by_tool_use.setdefault(action.tool_use_id, []).append(action)
    items: list[dict[str, Any]] = []
    for role, blocks in messages:
        for block in blocks or []:
            if not isinstance(block, dict):
                continue
            kind = block.get("type")
            if kind == "text":
                text = str(block.get("text") or "")
                if role == "user" and (
                    text.startswith("[Kontekst") or text.startswith("[Wynik akcji]")
                ):
                    continue
                if text.strip():
                    items.append({"kind": "message", "role": role, "markdown": text})
            elif kind == "tool_use" and role == "assistant":
                name = block.get("name")
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
