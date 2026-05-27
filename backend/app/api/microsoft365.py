"""Microsoft 365 OAuth + connection management endpoints.

Routes:
    GET    /api/microsoft365/authorize    → returns Microsoft login URL
    GET    /api/microsoft365/callback     → OAuth redirect target (unauth)
    GET    /api/microsoft365/connection   → current user's status
    DELETE /api/microsoft365/connection   → disconnect
    POST   /api/microsoft365/sync/trigger → manual sync (202)
    POST   /api/microsoft365/free-busy    → look up attendee availability
    POST   /api/microsoft365/webhooks     → Graph push-notification endpoint
"""

# NOTE: deliberately NOT using `from __future__ import annotations` here.
# FastAPI 0.115 + Pydantic 2.10 cannot resolve the `FreeBusyRequest`
# ForwardRef in the POST /free-busy route signature when annotations are
# lazy strings — it either mis-classifies the body as a query param
# (HTTP 422 loc=query.payload) or crashes with PydanticUserError
# "TypeAdapter ... is not fully defined" (HTTP 500). Eager annotations
# avoid the whole class of bug. Python 3.12 supports every type used in
# this file (PEP 585 built-in generics, `Optional`) without the future
# import, so removing it is purely a fix, not a downgrade.

import asyncio
import hmac
import logging
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Literal, Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, status
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from jose import JWTError
from pydantic import BaseModel, ConfigDict, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.core.database import AsyncSessionLocal, get_db
from app.core.encryption import TokenCipherNotConfigured, get_token_cipher
from app.core.rate_limit import limiter
from app.models.m365 import GraphSubscription, M365Connection, M365SyncStatus
from app.models.user import User
from app.services.m365 import oauth as m365_oauth
from app.services.m365 import webhooks as m365_webhooks
from app.services.m365.calendar import get_free_busy
from app.services.m365.graph_client import GraphClient, GraphRequestError
from app.services.m365.sync import sync_connection, trigger_backfill

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────


class AuthorizeResponse(BaseModel):
    authorize_url: str


class FreeBusyRequest(BaseModel):
    start: datetime
    end: datetime
    # Graph caps at 20 schedules per call (incl. the requester's mailbox).
    attendees: list[EmailStr] = Field(..., min_length=1, max_length=20)


class FreeBusySlotSchema(BaseModel):
    start: datetime
    end: datetime
    status: Literal["free", "tentative", "busy", "oof", "workingElsewhere", "unknown"]


class FreeBusyResponse(BaseModel):
    # `attendees[email] = [slots]`. Email keys are returned exactly as Graph
    # echoes them — usually the requested form, sometimes case-folded.
    attendees: dict[str, list[FreeBusySlotSchema]]
    requested_window: dict[str, datetime]


class ConnectionStatus(BaseModel):
    connected: bool
    mailbox_upn: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    synced_through: Optional[datetime] = None
    last_sync_status: Optional[str] = None
    last_error: Optional[str] = None
    backfill_in_progress: bool = False
    # True when a previously-connected mailbox needs the user to re-run OAuth
    # (e.g. encryption key rotated server-side, or Microsoft revoked the
    # refresh token). Frontend renders an amber banner with a CTA.
    requires_reconnect: bool = False
    max_attachment_mb: int = settings.M365_MAX_ATTACHMENT_MB

    model_config = ConfigDict(from_attributes=True)


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _get_connection_for_user(
    db: AsyncSession, user_id: int
) -> Optional[M365Connection]:
    return await db.scalar(
        select(M365Connection).where(M365Connection.user_id == user_id)
    )


def _frontend_callback_url(status_param: str, message: Optional[str] = None) -> str:
    """Build a URL on the frontend's /microsoft365/callback page."""
    base = settings.PUBLIC_BASE_URL.rstrip("/")
    query = {"status": status_param}
    if message:
        query["message"] = message[:300]
    return f"{base}/microsoft365/callback?{urlencode(query)}"


# ── Routes ──────────────────────────────────────────────────────────────────


@router.get("/authorize", response_model=AuthorizeResponse)
@limiter.limit("10/minute")
async def authorize(
    request: Request,
    current_user: User = Depends(get_current_user),
) -> AuthorizeResponse:
    """Return the Microsoft login URL. Frontend does `window.location = url`."""
    if not settings.M365_INTEGRATION_ENABLED:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft 365 integration is currently disabled.",
        )
    try:
        verifier, _ = m365_oauth.generate_pkce_pair()
        state = m365_oauth.sign_state(current_user.id, verifier)
        url = m365_oauth.build_authorize_url(state, verifier)
    except m365_oauth.M365NotConfigured as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return AuthorizeResponse(authorize_url=url)


@router.get("/callback", response_class=RedirectResponse)
@limiter.limit("20/minute")
async def callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    error_description: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """OAuth redirect endpoint — unauthenticated; identity comes from signed state.

    Exchanges code → tokens, upserts M365Connection, kicks off backfill.

    Note: `response_class=RedirectResponse` (not return-type annotation) —
    Pydantic 2 cannot generate JSON schema from a Starlette Response subclass,
    which would crash `/openapi.json` for the whole app.
    """
    if error:
        logger.warning("m365 callback error: %s — %s", error, error_description)
        return RedirectResponse(
            _frontend_callback_url("error", error_description or error),
            status_code=302,
        )
    if not code or not state:
        return RedirectResponse(
            _frontend_callback_url("error", "Missing code/state"),
            status_code=302,
        )

    try:
        user_id, pkce_verifier = m365_oauth.verify_state(state)
    except JWTError:
        return RedirectResponse(
            _frontend_callback_url("error", "State expired or invalid — try again"),
            status_code=302,
        )

    try:
        bundle = await m365_oauth.exchange_code(code, pkce_verifier)
    except Exception as exc:  # noqa: BLE001
        logger.exception("m365 code exchange failed")
        return RedirectResponse(
            _frontend_callback_url("error", f"Token exchange failed: {exc!r}"),
            status_code=302,
        )

    try:
        cipher = get_token_cipher()
    except TokenCipherNotConfigured:
        return RedirectResponse(
            _frontend_callback_url("error", "Server encryption key not configured"),
            status_code=302,
        )

    # Upsert connection row.
    existing = await _get_connection_for_user(db, user_id)
    datetime.now(timezone.utc)
    if existing is None:
        existing = M365Connection(
            user_id=user_id,
            tenant_id=bundle.tenant_id,
            mailbox_upn=bundle.mailbox_upn,
            access_token_ct=cipher.encrypt(bundle.access_token),
            refresh_token_ct=cipher.encrypt(bundle.refresh_token),
            expires_at=bundle.expires_at,
            scopes_granted=bundle.scopes,
            is_active=True,
            last_sync_status=M365SyncStatus.idle,
        )
        db.add(existing)
    else:
        existing.tenant_id = bundle.tenant_id
        existing.mailbox_upn = bundle.mailbox_upn
        existing.access_token_ct = cipher.encrypt(bundle.access_token)
        existing.refresh_token_ct = cipher.encrypt(bundle.refresh_token)
        existing.expires_at = bundle.expires_at
        existing.scopes_granted = bundle.scopes
        existing.is_active = True
        existing.last_error = None
        existing.last_sync_status = M365SyncStatus.idle
        # On reconnect, reset delta so backfill fills potential gaps.
        existing.delta_token_messages = None
        existing.delta_token_events = None
        existing.backfill_completed_at = None
    await db.commit()
    await db.refresh(existing)

    # Fire-and-forget initial backfill.
    asyncio.create_task(trigger_backfill(existing.id))

    # Auto-enrol Graph push subscriptions. Background task so the redirect
    # is not delayed by 3× Graph POST /subscriptions calls. The helper is a
    # no-op when M365_WEBHOOKS_ENABLED=false, so it's safe to fire here even
    # before the flag is flipped in prod.
    asyncio.create_task(m365_webhooks.auto_subscribe_after_connect(existing.id))

    return RedirectResponse(_frontend_callback_url("success"), status_code=302)


@router.get("/connection", response_model=ConnectionStatus)
async def get_connection(
    current_user: CurrentUser,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> ConnectionStatus:
    # 30s private cache — FE polls this co 15-60s, cache redukuje zbędne
    # DB roundtripy. `private` bo response zawiera per-user data
    # (mailbox_upn, sync status). QA 2026-05-27 sygnalizował timeout na
    # tym endpoincie — to nie był Graph call, ale powtarzane zapytania
    # przy załadowaniu /settings dawały kumulatywne >5s. Cache rozluźnia
    # presję bez utraty świeżości (FE refetchInterval i tak pull co 15s).
    response.headers["Cache-Control"] = "private, max-age=30"

    conn = await _get_connection_for_user(db, current_user.id)
    if conn is None:
        return ConnectionStatus(connected=False)
    # Soft-disconnected row with reconnect_required status → surface as "not
    # connected but needs reconnect". Frontend shows an amber CTA banner.
    if not conn.is_active:
        if conn.last_sync_status == M365SyncStatus.reconnect_required:
            return ConnectionStatus(
                connected=False,
                mailbox_upn=conn.mailbox_upn,
                last_sync_status=conn.last_sync_status.value,
                last_error=conn.last_error,
                requires_reconnect=True,
            )
        return ConnectionStatus(connected=False)
    return ConnectionStatus(
        connected=True,
        mailbox_upn=conn.mailbox_upn,
        last_sync_at=conn.last_sync_at,
        synced_through=conn.synced_through,
        last_sync_status=conn.last_sync_status.value if conn.last_sync_status else None,
        last_error=conn.last_error,
        backfill_in_progress=conn.backfill_completed_at is None,
    )


@router.delete("/connection", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_connection_for_user(db, current_user.id)
    if conn is None:
        return None
    # Tear down Graph push subscriptions BEFORE deleting the connection so we
    # still have the token in hand to authenticate DELETE /subscriptions/{id}.
    # Best-effort: a failed Graph DELETE leaves an orphan subscription that
    # Graph will eventually expire (~70h max), so we never block disconnect.
    try:
        await m365_webhooks.unsubscribe_all_for_connection(db, conn)
    except Exception:  # noqa: BLE001
        logger.warning("m365 unsubscribe_all failed (soft-continuing)")
    # Best-effort revoke — currently no-op (see oauth.revoke docstring).
    try:
        cipher = get_token_cipher()
        rt = cipher.decrypt(conn.refresh_token_ct)
        await m365_oauth.revoke(rt)
    except Exception:  # noqa: BLE001
        logger.warning("m365 revoke failed (soft-continuing)")
    await db.delete(conn)
    await db.commit()
    return None


@router.post("/sync/trigger", status_code=status.HTTP_202_ACCEPTED)
@limiter.limit("10/minute")
async def trigger_sync(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conn = await _get_connection_for_user(db, current_user.id)
    if conn is None or not conn.is_active:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED, detail="No active M365 connection"
        )
    conn_id = conn.id

    async def _run() -> None:
        from app.core.database import AsyncSessionLocal

        async with AsyncSessionLocal() as fresh_db:
            fresh_conn = await fresh_db.get(M365Connection, conn_id)
            if fresh_conn:
                await sync_connection(fresh_db, fresh_conn)

    asyncio.create_task(_run())
    return {"status": "accepted", "connection_id": conn_id}


@router.post("/free-busy", response_model=FreeBusyResponse)
@limiter.limit("30/minute")
async def free_busy(
    request: Request,
    # Explicit Body(...) avoids a FastAPI 0.115 + slowapi 0.1.9 quirk that
    # was mis-classifying this Pydantic body param as a query parameter on
    # production (smoke 2026-05-14 returned 422 loc=query.payload). Locally
    # on newer FastAPI it round-trips fine without the marker, but the
    # explicit form is documented as the safe pattern and costs nothing.
    payload: FreeBusyRequest = Body(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> FreeBusyResponse:
    """Return Graph `getSchedule` results for the requested attendees.

    Advisory only — frontend uses this to flag conflicts in
    `ScheduleInterviewModal` but does not block submit. Attendees outside the
    recruiter's tenant return `status="unknown"` (Graph cannot see external
    free/busy without B2B sharing), which the UI ignores silently.
    """
    if not settings.M365_INTEGRATION_ENABLED:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft 365 integration is currently disabled.",
        )
    if payload.end <= payload.start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="`end` must be after `start`.",
        )

    conn = await _get_connection_for_user(db, current_user.id)
    if conn is None or not conn.is_active:
        raise HTTPException(
            status.HTTP_412_PRECONDITION_FAILED, detail="No active M365 connection"
        )

    # Pydantic gives us EmailStr; Graph wants plain strings.
    attendees = [str(a) for a in payload.attendees]
    try:
        async with GraphClient(conn, db) as gc:
            slots = await get_free_busy(
                gc, attendees=attendees, start=payload.start, end=payload.end
            )
    except GraphRequestError as exc:
        # 4xx — surface Graph's complaint (bad attendee, etc.) without
        # leaking tokens; 5xx/timeout — generic 502 so frontend stays quiet.
        if 400 <= exc.status < 500:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, detail="Graph rejected free-busy request"
            ) from exc
        logger.warning("Graph free-busy upstream error: %s", exc.status)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, detail="Graph free-busy lookup failed"
        ) from exc

    return FreeBusyResponse(
        attendees={
            email: [FreeBusySlotSchema(**slot) for slot in slot_list]
            for email, slot_list in slots.items()
        },
        requested_window={"start": payload.start, "end": payload.end},
    )


# ── Phase 7.3 — Graph push-webhook endpoint ─────────────────────────────────

# In-memory replay-protection cache keyed by (subscriptionId, resourceData.id).
# 4096 entries × 24h TTL covers the highest-volume mailbox observed in prod
# (peak ~600 msg/day) by a wide margin. Resetting on worker restart is fine:
# `sync_connection` is idempotent on `m365_message_id`, so a duplicate
# notification just no-ops at upsert time. If we ever outgrow this we can
# move to a `graph_webhook_events` table without changing the API surface.
_REPLAY_CACHE_MAX = 4096
_REPLAY_TTL_SECONDS = 24 * 3600
_replay_cache: OrderedDict[tuple[str, str], float] = OrderedDict()


def _replay_seen(key: tuple[str, str]) -> bool:
    """Return True if we've processed this notification within the TTL window.

    Single-process LRU: the FastAPI app runs as one uvicorn worker today, so
    a Python dict is enough. Multi-worker deploys would need a Redis variant
    (call sites stay the same).
    """
    now = time.time()
    # Drop TTL-expired head entries cheaply (OrderedDict iterates insertion order).
    while _replay_cache:
        oldest_key, ts = next(iter(_replay_cache.items()))
        if now - ts > _REPLAY_TTL_SECONDS:
            _replay_cache.popitem(last=False)
            continue
        break
    if key in _replay_cache:
        return True
    _replay_cache[key] = now
    while len(_replay_cache) > _REPLAY_CACHE_MAX:
        _replay_cache.popitem(last=False)
    return False


def _reset_replay_cache_for_tests() -> None:
    """Test-only helper — clears the LRU between cases."""
    _replay_cache.clear()


@router.post("/webhooks")
async def webhooks(
    request: Request,
    validationToken: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Microsoft Graph push-notification endpoint.

    No slowapi rate limit by design:
    - Validation handshake must reply 200 within 10s no matter what; Graph
      retries with backoff and disables the subscription on failure.
    - Real notifications can burst legitimately when a connected mailbox
      receives 100 messages back-to-back. A 600/min cap would clip exactly
      the case we built this for.
    Abuse mitigation lives at the edge (Cloudflare WAF + bot challenge) and
    in the handler itself (unknown subscription IDs are silently dropped).

    Handles two cases:

    1. **Validation handshake.** When a new subscription is created Graph
       calls this URL with a `validationToken` query param and expects a
       200 ``text/plain`` body echoing the token within 10 seconds. We
       intentionally do NOT require the kill-switch for this branch — Graph
       must be able to validate the URL even when the feature flag is off
       at app boot, otherwise the very first POST /subscriptions during
       provisioning fails before we get a chance to flip the flag.

    2. **Real notification.** Body shape:
       ``{"value": [{"subscriptionId", "clientState", "resource",
       "resourceData": {"id"}, "changeType"}]}`` — for each entry we look
       up the local row by `subscriptionId`, constant-time compare the
       shared `clientState`, dedupe on (sub_id, resourceData.id), then
       dispatch a fresh sync task per affected connection. Graph requires
       a <3s reply; the sync runs in `asyncio.create_task` so the response
       returns immediately.
    """
    # ── Validation handshake (no auth, no flag gate by design) ───────────
    if validationToken is not None:
        # Graph requires plaintext echo, exactly the same bytes back. No
        # newline, no quotes. PlainTextResponse handles content-type.
        return PlainTextResponse(validationToken, status_code=200)

    if not settings.M365_WEBHOOKS_ENABLED:
        # Kill-switch — refuse pushes loudly so Graph backs off rather than
        # silently absorbing them.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Microsoft 365 webhooks disabled",
        )

    # ── Notification body parse ──────────────────────────────────────────
    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001
        # Graph health-pings sometimes arrive with empty/non-JSON bodies and
        # no validation token. Treat as no-op (202) so we don't trip Graph's
        # "endpoint unhealthy" auto-disable.
        return Response(status_code=status.HTTP_202_ACCEPTED)

    entries = payload.get("value") if isinstance(payload, dict) else None
    if not isinstance(entries, list) or not entries:
        return Response(status_code=status.HTTP_202_ACCEPTED)

    # Dedupe affected connections — one inbox + sent + events tick should
    # fire ONE sync, not three.
    conns_to_sync: set[int] = set()

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        sub_id = entry.get("subscriptionId")
        client_state = entry.get("clientState")
        if not isinstance(sub_id, str) or not isinstance(client_state, str):
            continue

        sub = await db.scalar(
            select(GraphSubscription).where(GraphSubscription.subscription_id == sub_id)
        )
        if sub is None:
            # Subscription was unsubscribed locally but Graph hasn't caught
            # up yet — log truncated id so a Sentry breadcrumb can correlate.
            logger.warning(
                "webhook for unknown subscription_id prefix=%s — ignoring",
                sub_id[:32],
            )
            continue

        # Constant-time compare to neutralise timing side-channels.
        if not hmac.compare_digest(sub.client_state, client_state):
            logger.warning(
                "webhook client_state mismatch for sub_id prefix=%s — refusing entry",
                sub_id[:32],
            )
            continue

        # Replay dedup key. resourceData.id is present for created/updated
        # messages and events; if Graph ever omits it we fall back to a
        # composite fingerprint so retries still dedupe.
        resource_data = entry.get("resourceData") or {}
        rd_id = (
            resource_data.get("id") if isinstance(resource_data, dict) else None
        ) or f"{entry.get('changeType', '')}|{entry.get('resource', '')}"
        if _replay_seen((sub_id, str(rd_id))):
            continue

        conns_to_sync.add(sub.m365_connection_id)

    for conn_id in conns_to_sync:
        asyncio.create_task(_webhook_dispatch_sync(conn_id))

    return Response(status_code=status.HTTP_202_ACCEPTED)


async def _webhook_dispatch_sync(connection_id: int) -> None:
    """Background-friendly sync triggered by an inbound webhook.

    Opens a fresh DB session so it survives the HTTP response that started
    it. Errors are recorded on the connection row by `sync_connection`
    itself — we only catch here to keep the task from logging an unhandled
    exception traceback at task-done time.
    """
    async with AsyncSessionLocal() as db:
        conn = await db.get(M365Connection, connection_id)
        if conn is None or not conn.is_active:
            return
        try:
            await sync_connection(db, conn)
        except Exception:  # noqa: BLE001
            logger.exception(
                "webhook-dispatched sync failed for connection_id=%s",
                connection_id,
            )
