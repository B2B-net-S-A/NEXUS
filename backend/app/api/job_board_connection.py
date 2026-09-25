"""Połączenie konta firmy w JustJoin.IT / RocketJobs (Employer Public API, 0381).

    GET    /api/job-boards/jjit/connection   — stan, kto połączył, saldo (admin)
    GET    /api/job-boards/jjit/authorize    — adres logowania u dostawcy (admin)
    GET    /api/job-boards/jjit/callback     — powrót z logowania (bez sesji NEXUSA)
    DELETE /api/job-boards/jjit/connection   — rozłączenie (admin)

Dostawca ma wyłącznie ``authorization_code``: konto łączy RAZ osoba, która
ma login pracodawcy B2B.NET, a dalej pracujemy na odświeżanym tokenie
(``services/job_portals/jjit_connection``). Callback nie ma sesji NEXUSA —
tożsamość niesie podpisany ``state`` (wzór ``api/microsoft365.py``), a rola
admina jest sprawdzana ponownie przed wymianą kodu.
"""

# Bez `from __future__ import annotations` — slowapi (#579) zamienia wtedy
# guard `Annotated` w parametr QUERY (422 na poprawnym żądaniu).

import logging
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import RedirectResponse
from jose import JWTError
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.user import User, UserRole
from app.services.job_portals import PortalConfig, jjit_connection
from app.services.job_portals.base import JJIT_FAMILY, PortalError

logger = logging.getLogger(__name__)

router = APIRouter()

_LABELS = {"justjoinit": "JustJoin.IT", "rocketjobs": "RocketJobs"}


class AuthorizeResponse(BaseModel):
    authorize_url: str


class BalanceCode(BaseModel):
    name: str
    remaining: int
    expires_at: Optional[str] = None
    plan_key: Optional[str] = None


class BalanceSubscription(BaseModel):
    id: str
    remaining: int
    end_date: Optional[str] = None
    plan_key: Optional[str] = None
    active: bool


class BoardBalance(BaseModel):
    codes: list[BalanceCode]
    subscriptions: list[BalanceSubscription]


class BoardState(BaseModel):
    board: str
    label: str
    enabled: bool
    organization_unit_id: Optional[str] = None
    balance: Optional[BoardBalance] = None
    balance_error: Optional[str] = None


class JobBoardConnectionRead(BaseModel):
    oauth_configured: bool
    status: str  # not_connected | active | reconnect_required
    connected_by_name: Optional[str] = None
    connected_at: Optional[datetime] = None
    last_error: Optional[str] = None
    boards: list[BoardState]


def _settings_url(status: str, message: Optional[str] = None) -> str:
    query = {"item": "job-boards", "status": status}
    if message:
        query["message"] = message[:200]
    return f"{settings.PUBLIC_BASE_URL.rstrip('/')}/settings?{urlencode(query)}"


def _remaining(item: dict) -> int:
    try:
        return max(
            0, int(item.get("maxUsage") or 0) - int(item.get("currentUsage") or 0)
        )
    except (TypeError, ValueError):
        return 0


def _balance(board: str, raw: dict) -> BoardBalance:
    def mine(item: dict) -> bool:
        return str(item.get("jobBoard") or board).casefold() == board

    return BoardBalance(
        codes=[
            BalanceCode(
                name=str(c.get("name")),
                remaining=_remaining(c),
                expires_at=str(c["expiresAt"]) if c.get("expiresAt") else None,
                plan_key=c.get("planKey"),
            )
            for c in raw.get("codes") or []
            if isinstance(c, dict) and c.get("name") and mine(c)
        ],
        subscriptions=[
            BalanceSubscription(
                id=str(s.get("id")),
                remaining=_remaining(s),
                end_date=str(s["endDate"]) if s.get("endDate") else None,
                plan_key=s.get("planKey"),
                active=bool(s.get("isActive")),
            )
            for s in raw.get("subscriptions") or []
            if isinstance(s, dict) and s.get("id") and mine(s)
        ],
    )


@router.get("/job-boards/jjit/connection", response_model=JobBoardConnectionRead)
@limiter.limit("30/minute")
async def get_connection(
    request: Request, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> JobBoardConnectionRead:
    row = await jjit_connection.load(db)
    connected_by = (
        await db.get(User, row.connected_by) if row and row.connected_by else None
    )
    boards: list[BoardState] = []
    for portal in JJIT_FAMILY:
        board = portal.value
        unit = jjit_connection.unit_for(row, board)
        state = BoardState(
            board=board,
            label=_LABELS[board],
            enabled=PortalConfig.from_settings(portal).enabled,
            organization_unit_id=unit,
        )
        if row is not None and row.status == "active" and state.enabled and unit:
            from app.services.job_portals.jjit_client import JjitApi

            try:
                state.balance = _balance(board, await JjitApi().balance(unit))
            except PortalError as exc:
                state.balance_error = exc.message
        boards.append(state)
    return JobBoardConnectionRead(
        oauth_configured=jjit_connection.oauth_configured(),
        status=row.status if row else "not_connected",
        connected_by_name=getattr(connected_by, "name", None)
        or getattr(connected_by, "email", None),
        connected_at=row.connected_at if row else None,
        last_error=row.last_error if row else None,
        boards=boards,
    )


@router.get("/job-boards/jjit/authorize", response_model=AuthorizeResponse)
@limiter.limit("10/minute")
async def authorize(request: Request, current_user: AdminUser) -> AuthorizeResponse:
    try:
        url = jjit_connection.authorize_url(current_user.id)
    except jjit_connection.ConnectionNotConfigured:
        raise HTTPException(
            409,
            detail={
                "code": "oauth_not_configured",
                "message": "Brak danych aplikacji od dostawcy portalu "
                "(client_id, client_secret, adres powrotu).",
            },
        ) from None
    return AuthorizeResponse(authorize_url=url)


@router.get("/job-boards/jjit/callback", response_class=RedirectResponse)
@limiter.limit("20/minute")
async def callback(
    request: Request,
    code: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    error: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Powrót z logowania u dostawcy — bez sesji NEXUSA; tożsamość w ``state``."""
    if error:
        logger.warning("jjit oauth callback error=%s", error[:60])
        return RedirectResponse(
            _settings_url("error", "Dostawca portalu odmówił połączenia."), 302
        )
    if not code or not state:
        return RedirectResponse(_settings_url("error", "Brak kodu logowania."), 302)
    try:
        user_id, verifier = jjit_connection.verify_state(state)
    except (JWTError, KeyError, ValueError):
        return RedirectResponse(
            _settings_url("error", "Logowanie wygasło — spróbuj ponownie."), 302
        )
    user = await db.get(User, user_id)
    if user is None or not user.is_active or not user.has_role(UserRole.admin):
        return RedirectResponse(
            _settings_url("error", "Konto portalu łączy wyłącznie administrator."), 302
        )
    try:
        await jjit_connection.exchange_code(
            db, code=code, verifier=verifier, user_id=user.id
        )
    except PortalError as exc:
        await db.rollback()
        return RedirectResponse(_settings_url("error", exc.message), 302)
    except Exception as exc:  # noqa: BLE001 — bez szczegółów w adresie
        await db.rollback()
        logger.error("jjit oauth exchange failed: %s", type(exc).__name__)
        return RedirectResponse(
            _settings_url("error", "Nie udało się połączyć konta portalu."), 302
        )
    await db.commit()
    logger.info(
        "jjit account connected by user=%s at=%s",
        user.id,
        datetime.now(timezone.utc).isoformat(),
    )
    return RedirectResponse(_settings_url("success"), 302)


@router.delete("/job-boards/jjit/connection", status_code=204)
@limiter.limit("10/minute")
async def disconnect(
    request: Request, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> Response:
    """Rozłączenie: kasuje tokeny. Żywe ogłoszenia zostają na portalu."""
    row = await jjit_connection.load(db)
    if row is not None:
        await db.delete(row)
        await db.commit()
    return Response(status_code=204)
