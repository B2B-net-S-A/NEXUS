"""Microsoft 365 OAuth + connection management endpoints.

Routes:
    GET    /api/microsoft365/authorize    → returns Microsoft login URL
    GET    /api/microsoft365/callback     → OAuth redirect target (unauth)
    GET    /api/microsoft365/connection   → current user's status
    DELETE /api/microsoft365/connection   → disconnect
    POST   /api/microsoft365/sync/trigger → manual sync (202)
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import RedirectResponse
from jose import JWTError
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_current_user
from app.core.config import settings
from app.core.database import get_db
from app.core.encryption import TokenCipherNotConfigured, get_token_cipher
from app.core.rate_limit import limiter
from app.models.m365 import M365Connection, M365SyncStatus
from app.models.user import User
from app.services.m365 import oauth as m365_oauth
from app.services.m365.sync import sync_connection, trigger_backfill

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ─────────────────────────────────────────────────────────────────


class AuthorizeResponse(BaseModel):
    authorize_url: str


class ConnectionStatus(BaseModel):
    connected: bool
    mailbox_upn: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    synced_through: Optional[datetime] = None
    last_sync_status: Optional[str] = None
    last_error: Optional[str] = None
    backfill_in_progress: bool = False
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
    except TokenCipherNotConfigured as exc:
        return RedirectResponse(
            _frontend_callback_url("error", "Server encryption key not configured"),
            status_code=302,
        )

    # Upsert connection row.
    existing = await _get_connection_for_user(db, user_id)
    now = datetime.now(timezone.utc)
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

    return RedirectResponse(_frontend_callback_url("success"), status_code=302)


@router.get("/connection", response_model=ConnectionStatus)
async def get_connection(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ConnectionStatus:
    conn = await _get_connection_for_user(db, current_user.id)
    if conn is None or not conn.is_active:
        return ConnectionStatus(connected=False)
    return ConnectionStatus(
        connected=True,
        mailbox_upn=conn.mailbox_upn,
        last_sync_at=conn.last_sync_at,
        synced_through=conn.synced_through,
        last_sync_status=conn.last_sync_status.value
        if conn.last_sync_status
        else None,
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
