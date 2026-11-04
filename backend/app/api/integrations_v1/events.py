"""Zdarzenia w API v1: kanał zdarzeń i webhooki konta serwisowego.

Scope ``events:read`` (kanał) i ``webhooks:manage`` (subskrypcje). Zdarzenie niesie
wyłącznie typ, identyfikatory i czas — dane pobiera się osobnymi trasami z ich
scope'ami, więc webhook nie wynosi danych osobowych poza NEXUSA.

* ``GET /events?after=<id>&types=a,b&limit=`` — zdarzenia po kursorze, tylko
  te, których scope klucz ma (``integration_events.EVENT_TYPES``). Kursor
  ``next_after`` przeskakuje także zdarzenia niewidoczne dla klucza.
* ``GET/POST/DELETE /webhooks``, ``POST /webhooks/{id}/test`` — webhooki
  WŁASNEGO konta (cudzy webhook = 404). Nowy webhook dostaje zdarzenia od
  chwili założenia; zaległości są w kanale. Sekret podpisu jest w odpowiedzi
  na utworzenie RAZ — paragon idempotencji przechowuje odpowiedź bez niego.

Wysyłkę robi pętla w tle (``tasks/integration_webhooks.py``), zasady adresu,
podpisu i ponowień: ``services/integration_webhooks.py``.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_v1.common import (
    EventsRead,
    IdPath,
    IntegrationRoute,
    WebhooksManage,
    idempotent_write,
    principal_of,
    principal_rate_key,
    read_rate_limit,
    write_rate_limit,
)
from app.api.deps import Caller
from app.core.database import get_db
from app.core.encryption import TokenCipherNotConfigured
from app.core.rate_limit import limiter
from app.models.integration_event import IntegrationWebhook
from app.models.service_account import ServiceScope
from app.services import integration_events, integration_receipts
from app.services import integration_webhooks as webhooks
from app.services.oauth_route_scopes import route_template
from app.tasks.integration_webhooks import request_wakeup

router = APIRouter(route_class=IntegrationRoute)

MAX_FEED_LIMIT = 500
BIGINT_MAX = 2**63 - 1
MAX_EVENT_TYPES = len(integration_events.EVENT_TYPES)


# ── Schematy ─────────────────────────────────────────────────────────────────


class EventOut(BaseModel):
    id: int = Field(description="Kursor zdarzenia (rośnie w kolejności publikacji).")
    type: str
    occurred_at: datetime
    refs: dict[str, Any] = Field(
        description="Identyfikatory obiektów, których dotyczy zdarzenie."
    )


class EventFeed(BaseModel):
    items: list[EventOut]
    next_after: int = Field(description="Wartość `after` dla następnego odpytania.")
    has_more: bool


class WebhookOut(BaseModel):
    id: int
    url: str
    event_types: list[str] = Field(description="Pusta lista = wszystkie widoczne typy.")
    is_active: bool
    last_event_id: int
    failure_count: int
    next_attempt_at: Optional[datetime]
    disabled_reason: Optional[str]
    last_delivery_at: Optional[datetime]
    last_status: Optional[int]
    last_error: Optional[str]
    test_pending: bool
    created_at: datetime


class WebhookCreateIn(BaseModel):
    url: str = Field(min_length=1, max_length=webhooks.MAX_URL_LENGTH)
    event_types: list[str] = Field(default_factory=list, max_length=MAX_EVENT_TYPES)


class WebhookCreated(BaseModel):
    webhook: WebhookOut
    secret: Optional[str] = Field(
        description="Sekret podpisu (`whsec_…`) — tylko w pierwszej odpowiedzi; "
        "w powtórce z tym samym Idempotency-Key jest `null`."
    )
    secret_redacted: bool


class WebhookDeleted(BaseModel):
    id: int
    deleted: bool


class WebhookTestQueued(BaseModel):
    id: int
    queued: bool


def webhook_out(hook: IntegrationWebhook) -> WebhookOut:
    return WebhookOut(
        id=hook.id,
        url=hook.url,
        event_types=[t for t in (hook.event_types or []) if isinstance(t, str)],
        is_active=bool(hook.is_active),
        last_event_id=int(hook.last_event_id or 0),
        failure_count=int(hook.failure_count or 0),
        next_attempt_at=hook.next_attempt_at,
        disabled_reason=hook.disabled_reason,
        last_delivery_at=hook.last_delivery_at,
        last_status=hook.last_status,
        last_error=hook.last_error,
        test_pending=hook.test_requested_at is not None,
        created_at=hook.created_at,
    )


# ── Pomocnicze ───────────────────────────────────────────────────────────────


def _event_types(raw: list[str]) -> list[str]:
    """Nazwy typów bez duplikatów, w kolejności; nieznany typ = 422."""
    names = list(dict.fromkeys(name.strip() for name in raw if name and name.strip()))
    unknown = [name for name in names if name not in integration_events.EVENT_TYPES]
    if unknown:
        raise HTTPException(
            422,
            detail={
                "error": "unknown_event_type",
                "message": "Nieznany typ zdarzenia.",
                "unknown": unknown,
                "known": sorted(integration_events.EVENT_TYPES),
            },
        )
    return names


async def _own_webhook(
    db: AsyncSession, account_id: int, webhook_id: int
) -> IntegrationWebhook:
    hook = await db.scalar(
        select(IntegrationWebhook).where(
            IntegrationWebhook.id == webhook_id,
            IntegrationWebhook.service_account_id == account_id,
        )
    )
    if hook is None:
        raise HTTPException(404, detail="Webhook nie istnieje.")
    return hook


async def _write_with_secret(
    request: Request,
    db: AsyncSession,
    caller: Caller,
    *,
    payload: Any,
    run: Callable[[], Awaitable[tuple[int, Any, str]]],
) -> Response:
    """``idempotent_write`` z sekretem tylko w odpowiedzi na żywo.

    Paragon zapisuje odpowiedź BEZ sekretu: inaczej jawny sekret leżałby
    w ``integration_write_receipts`` przez 90 dni, a powtórka pokazywałaby go
    drugi raz.
    """
    principal = principal_of(caller)
    route = route_template(request) or request.url.path
    receipt, replay = await integration_receipts.begin(
        db,
        principal,
        raw_key=request.headers.get(integration_receipts.IDEMPOTENCY_HEADER),
        method=request.method,
        route=route,
        payload=payload,
    )
    if replay is not None:
        return JSONResponse(
            status_code=replay.status_code,
            content=replay.body,
            headers={integration_receipts.REPLAYED_HEADER: "true"},
        )
    status_code, stored, secret = await run()
    encoded = jsonable_encoder(stored)
    await integration_receipts.finish(
        db, receipt, status_code=status_code, body=encoded
    )
    await db.commit()
    return JSONResponse(
        status_code=status_code,
        content={**encoded, "secret": secret, "secret_redacted": False},
    )


# ── Kanał ────────────────────────────────────────────────────────────────────


@router.get("/events", response_model=EventFeed, summary="Kanał zdarzeń")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_events(
    request: Request,
    caller: EventsRead,
    db: AsyncSession = Depends(get_db),
    after: int = Query(0, ge=0, le=BIGINT_MAX, description="Kursor (`next_after`)."),
    types: Optional[str] = Query(
        None, max_length=2000, description="Typy po przecinku, np. `card.moved`."
    ),
    limit: int = Query(100, ge=1, le=MAX_FEED_LIMIT),
) -> dict:
    """Zdarzenia z ``id > after`` rosnąco — tylko typy, których scope ma klucz.

    Pełna strona = ``has_more: true``; odpytuj dalej z ``after = next_after``.
    Zdarzenia są przechowywane 30 dni. Opóźnienie od zmiany do kanału: kilka sekund.
    """
    requested = _event_types(types.split(",")) if types else None
    rows, next_after, has_more = await integration_events.read_feed(
        db,
        after=after,
        scopes=principal_of(caller).scopes,
        types=requested,
        limit=limit,
    )
    return {
        "items": [integration_events.event_payload(row) for row in rows],
        "next_after": next_after,
        "has_more": has_more,
    }


# ── Webhooki ─────────────────────────────────────────────────────────────────


@router.get("/webhooks", response_model=list[WebhookOut], summary="Webhooki konta")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_webhooks(
    request: Request,
    caller: WebhooksManage,
    db: AsyncSession = Depends(get_db),
) -> list:
    """Webhooki konta klucza ze stanem dostarczeń (bez sekretów)."""
    account_id = principal_of(caller).account_id
    rows = await db.scalars(
        select(IntegrationWebhook)
        .where(IntegrationWebhook.service_account_id == account_id)
        .order_by(IntegrationWebhook.id)
    )
    return [webhook_out(hook) for hook in rows]


@router.post(
    "/webhooks",
    response_model=WebhookCreated,
    status_code=201,
    summary="Dodaj webhook",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def create_webhook(
    request: Request,
    body: WebhookCreateIn,
    caller: WebhooksManage,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Webhook na adres ``https://`` (port 443, wyłącznie adresy publiczne).

    Zdarzenia przychodzą jako ``POST`` z treścią ``{"webhook_id", "sent_at",
    "events": [...]}`` (zdarzenia jak w ``GET /events``) i nagłówkiem
    ``X-Nexus-Signature: sha256=<HMAC-SHA256 treści sekretem>``. Sekret jest
    w odpowiedzi tylko raz. Wymaga też ``events:read``; typy spoza scope'ów
    klucza = 422. Najwyżej 5 webhooków na konto.
    """
    principal = principal_of(caller)
    if ServiceScope.events_read.value not in principal.scopes:
        raise HTTPException(
            403,
            detail={
                "error": "insufficient_scope",
                "message": "Webhook wymaga też scope'u events:read.",
                "required": [
                    ServiceScope.events_read.value,
                    ServiceScope.webhooks_manage.value,
                ],
                "missing": [ServiceScope.events_read.value],
            },
        )
    types = _event_types(body.event_types)
    hidden = [
        t for t in types if integration_events.EVENT_TYPES[t] not in principal.scopes
    ]
    if hidden:
        raise HTTPException(
            422,
            detail={
                "error": "event_type_not_visible",
                "message": "Klucz nie ma scope'u potrzebnego do tych typów zdarzeń.",
                "event_types": hidden,
                "required_scopes": sorted(
                    {integration_events.EVENT_TYPES[t] for t in hidden}
                ),
            },
        )
    payload = {"url": body.url, "event_types": types}

    async def run() -> tuple[int, Any, str]:
        try:
            url = await webhooks.validate_webhook_url(body.url)
        except webhooks.WebhookUrlError as exc:
            raise HTTPException(
                422, detail={"error": exc.code, "message": exc.message}
            ) from None
        count = await db.scalar(
            select(func.count(IntegrationWebhook.id)).where(
                IntegrationWebhook.service_account_id == principal.account_id
            )
        )
        if (count or 0) >= webhooks.MAX_WEBHOOKS_PER_ACCOUNT:
            raise HTTPException(
                409,
                detail={
                    "error": "webhook_limit",
                    "message": f"Konto ma już {webhooks.MAX_WEBHOOKS_PER_ACCOUNT} "
                    "webhooków — usuń nieużywany.",
                },
            )
        secret = webhooks.new_secret()
        try:
            secret_ct = webhooks.encrypt_secret(secret)
        except TokenCipherNotConfigured:
            raise HTTPException(
                503,
                detail={
                    "error": "unavailable",
                    "message": "Webhooki są chwilowo niedostępne (szyfrowanie "
                    "sekretów nie jest skonfigurowane). Skontaktuj się "
                    "z administratorem NEXUSA.",
                },
            ) from None
        hook = IntegrationWebhook(
            service_account_id=principal.account_id,
            url=url,
            secret_ct=secret_ct,
            event_types=types,
            is_active=True,
            # Od teraz — zaległości są w kanale ``GET /events``.
            last_event_id=await integration_events.current_cursor(db),
        )
        db.add(hook)
        await db.flush()
        await db.refresh(hook)
        stored = {
            "webhook": webhook_out(hook),
            "secret": None,
            "secret_redacted": True,
        }
        return 201, stored, secret

    return await _write_with_secret(request, db, caller, payload=payload, run=run)


@router.delete(
    "/webhooks/{webhook_id}", response_model=WebhookDeleted, summary="Usuń webhook"
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def delete_webhook(
    request: Request,
    webhook_id: IdPath,
    caller: WebhooksManage,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Usuwa webhook konta; zdarzenia zostają w kanale."""
    account_id = principal_of(caller).account_id

    async def run() -> tuple[int, Any]:
        hook = await _own_webhook(db, account_id, webhook_id)
        await db.delete(hook)
        await db.flush()
        return 200, {"id": webhook_id, "deleted": True}

    return await idempotent_write(
        request, db, caller, payload={"webhook_id": webhook_id}, run=run
    )


@router.post(
    "/webhooks/{webhook_id}/test",
    response_model=WebhookTestQueued,
    status_code=202,
    summary="Wyślij zdarzenie próbne",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def test_webhook(
    request: Request,
    webhook_id: IdPath,
    caller: WebhooksManage,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Zamawia zdarzenie ``webhook.test`` (``id = 0``) — wychodzi w ciągu kilku sekund.

    Wynik widać w ``GET /webhooks`` (``last_status``, ``last_error``). Udana
    próba włącza webhook wyłączony po serii porażek; dostarczanie wraca od
    zapamiętanego kursora.
    """
    account_id = principal_of(caller).account_id

    async def run() -> tuple[int, Any]:
        hook = await _own_webhook(db, account_id, webhook_id)
        hook.test_requested_at = datetime.now(timezone.utc)
        await db.flush()
        return 202, {"id": hook.id, "queued": True}

    response = await idempotent_write(
        request, db, caller, payload={"webhook_id": webhook_id}, run=run
    )
    request_wakeup()
    return response
