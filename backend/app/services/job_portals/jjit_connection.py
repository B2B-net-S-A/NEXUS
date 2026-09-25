"""Połączone konto firmy w JustJoin.IT / RocketJobs — OAuth i tokeny (0381).

Employer Public API ma wyłącznie ``authorization_code`` (+ ``refresh_token``),
bez trybu serwer-serwer. Admin łączy konto RAZ w Ustawieniach → Portale
ogłoszeniowe; dalej pracujemy na odświeżanym tokenie.

Dwie reguły, które łatwo zepsuć:

* **Odświeżenie tokenu idzie we WŁASNEJ sesji i od razu się commituje.**
  Dostawca rotuje refresh token — gdyby nowy leżał w transakcji żądania,
  które potem zrobi rollback, stracilibyśmy jedyny ważny token i konto
  wymagałoby ponownego łączenia.
* **Odświeżenie jest pod ``FOR UPDATE`` wiersza połączenia** — przy deployu
  żyją dwa procesy; drugi czeka i dostaje token odświeżony przez pierwszego.

``invalid_grant`` = ``status = reconnect_required`` i ``PortalReconnectRequired``
(worker czeka, nie pali prób). Wzór PKCE/state: ``services/m365/oauth.py``.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import get_token_cipher
from app.models.job_board_connection import (
    PROVIDER_JJIT,
    STATUS_ACTIVE,
    STATUS_RECONNECT_REQUIRED,
    JobBoardConnection,
)
from app.services.job_portals.base import PortalError, PortalReconnectRequired

logger = logging.getLogger(__name__)

STATE_PURPOSE = "jjit_oauth_state"
_STATE_TTL_SECONDS = 600
_STATE_ALGORITHM = "HS256"
# Token odświeżamy z zapasem — żądanie w toku nie może trafić na wygasły.
_EXPIRY_MARGIN = timedelta(seconds=90)

# Nadpisania jednostek z env mają pierwszeństwo przed claimami z `/oauth/me`.
_UNIT_OVERRIDE = {
    "justjoinit": "PORTAL_JJIT_ORGANIZATION_UNIT_ID",
    "rocketjobs": "PORTAL_ROCKETJOBS_ORGANIZATION_UNIT_ID",
}
_UNIT_CLAIMS = ("organization_unit_id", "organizationUnitId", "organization_id")


class ConnectionNotConfigured(RuntimeError):
    """Brak client_id / client_secret / redirect_uri aplikacji OAuth."""


def oauth_configured() -> bool:
    return all(
        str(value or "").strip()
        for value in (
            settings.JJIT_OAUTH_CLIENT_ID,
            settings.JJIT_OAUTH_CLIENT_SECRET,
            settings.JJIT_OAUTH_REDIRECT_URI,
            settings.PORTAL_JJIT_API_URL,
        )
    )


def _api_url(path: str) -> str:
    return settings.PORTAL_JJIT_API_URL.rstrip("/") + path


# ── PKCE + state ─────────────────────────────────────────────────────────────


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(os.urandom(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


def sign_state(user_id: int, verifier: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "pkce": verifier,
            "iat": now,
            "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
            "purpose": STATE_PURPOSE,
        },
        _signing_key(),
        algorithm=_STATE_ALGORITHM,
    )


def verify_state(token: str) -> tuple[int, str]:
    """(user_id, pkce_verifier) albo ``JWTError`` — także przy obcym ``purpose``."""
    payload = jwt.decode(token, _signing_key(), algorithms=[_STATE_ALGORITHM])
    if payload.get("purpose") != STATE_PURPOSE:
        raise JWTError("wrong purpose")
    return int(payload["sub"]), str(payload["pkce"])


def authorize_url(user_id: int) -> str:
    if not oauth_configured():
        raise ConnectionNotConfigured("Brak konfiguracji aplikacji OAuth portalu.")
    verifier, challenge = _pkce_pair()
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.JJIT_OAUTH_CLIENT_ID,
            "redirect_uri": settings.JJIT_OAUTH_REDIRECT_URI,
            "scope": settings.JJIT_OAUTH_SCOPE,
            "state": sign_state(user_id, verifier),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return _api_url("/employer/oauth/authorize") + "?" + query


# ── Wymiana i odświeżenie tokenu ─────────────────────────────────────────────


async def _token_request(
    form: dict[str, str], *, transport: Optional[httpx.AsyncBaseTransport] = None
) -> dict[str, Any]:
    data = dict(form)
    data["client_id"] = settings.JJIT_OAUTH_CLIENT_ID
    data["client_secret"] = settings.JJIT_OAUTH_CLIENT_SECRET
    try:
        async with httpx.AsyncClient(
            transport=transport, timeout=settings.PORTAL_JJIT_HTTP_TIMEOUT_SECONDS
        ) as client:
            response = await client.post(_api_url("/employer/oauth/token"), data=data)
    except httpx.HTTPError as exc:
        raise PortalError(
            "Brak połączenia z portalem przy odświeżaniu tokenu.", retryable=True
        ) from exc
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.status_code == 400 and body.get("error") == "invalid_grant":
        raise PortalReconnectRequired(
            "Połączenie z portalem wygasło — połącz konto ponownie w Ustawieniach → "
            "Portale ogłoszeniowe."
        )
    if response.status_code >= 400 or not body.get("access_token"):
        logger.warning(
            "jjit token request failed status=%s error=%s",
            response.status_code,
            body.get("error"),
        )
        raise PortalError(
            "Portal odrzucił żądanie tokenu.",
            retryable=response.status_code >= 500 or response.status_code == 429,
        )
    return body


def _expiry(body: dict[str, Any]) -> Optional[datetime]:
    try:
        seconds = int(body.get("expires_in") or 0)
    except (TypeError, ValueError):
        seconds = 0
    if seconds <= 0:
        return None
    return datetime.now(timezone.utc) + timedelta(seconds=seconds)


def resolve_units(claims: dict[str, Any]) -> dict[str, str]:
    """Jednostka organizacyjna per portal: env > claim z ``/oauth/me``."""
    claimed = next((str(claims[key]) for key in _UNIT_CLAIMS if claims.get(key)), None)
    units: dict[str, str] = {}
    for board, setting in _UNIT_OVERRIDE.items():
        override = str(getattr(settings, setting, "") or "").strip()
        value = override or claimed
        if value:
            units[board] = value
    return units


async def exchange_code(
    db: AsyncSession,
    *,
    code: str,
    verifier: str,
    user_id: int,
    transport: Optional[httpx.AsyncBaseTransport] = None,
) -> JobBoardConnection:
    """Kod z callbacku → tokeny → ``/oauth/me`` → zapis (bez commitu)."""
    body = await _token_request(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.JJIT_OAUTH_REDIRECT_URI,
            "code_verifier": verifier,
        },
        transport=transport,
    )
    if not body.get("refresh_token"):
        raise PortalError(
            "Portal nie wydał tokenu odświeżania — sprawdź, czy aplikacja ma "
            "zakres offline_access.",
            retryable=False,
        )
    from app.services.job_portals.jjit_client import JjitApi

    access = str(body["access_token"])

    async def _fixed(_force: bool) -> str:
        return access

    claims = await JjitApi(_fixed, transport=transport).me()
    cipher = get_token_cipher()
    now = datetime.now(timezone.utc)
    row = await db.scalar(
        select(JobBoardConnection)
        .where(JobBoardConnection.provider == PROVIDER_JJIT)
        .with_for_update()
    )
    if row is None:
        row = JobBoardConnection(provider=PROVIDER_JJIT, connected_at=now)
        db.add(row)
    row.status = STATUS_ACTIVE
    row.access_token_ct = cipher.encrypt(access)
    row.refresh_token_ct = cipher.encrypt(str(body["refresh_token"]))
    row.expires_at = _expiry(body)
    row.organization_units = resolve_units(claims)
    label = claims.get("name") or claims.get("email") or claims.get("company_name")
    row.account_label = str(label)[:255] if label else None
    row.connected_by = user_id
    row.connected_at = now
    row.last_refresh_at = now
    row.last_error = None
    await db.flush()
    return row


async def load(db: AsyncSession) -> Optional[JobBoardConnection]:
    return await db.scalar(
        select(JobBoardConnection).where(JobBoardConnection.provider == PROVIDER_JJIT)
    )


async def is_connected(db: AsyncSession) -> bool:
    row = await load(db)
    return row is not None and row.status == STATUS_ACTIVE


async def access_token(force_refresh: bool = False) -> str:
    """Ważny token dostępu — odświeżenie we własnej sesji, zapis od razu."""
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(JobBoardConnection)
            .where(JobBoardConnection.provider == PROVIDER_JJIT)
            .with_for_update()
        )
        if row is None or row.status != STATUS_ACTIVE:
            raise PortalReconnectRequired(
                "Konto portalu nie jest połączone — admin łączy je w Ustawieniach → "
                "Portale ogłoszeniowe."
            )
        cipher = get_token_cipher()
        now = datetime.now(timezone.utc)
        fresh = row.expires_at is None or row.expires_at - _EXPIRY_MARGIN > now
        if row.access_token_ct and fresh and not force_refresh:
            token = cipher.decrypt(row.access_token_ct)
            await db.rollback()
            return token
        try:
            body = await _token_request(
                {
                    "grant_type": "refresh_token",
                    "refresh_token": cipher.decrypt(row.refresh_token_ct),
                }
            )
        except PortalReconnectRequired as exc:
            row.status = STATUS_RECONNECT_REQUIRED
            row.last_error = exc.message[:300]
            await db.commit()
            raise
        row.access_token_ct = cipher.encrypt(str(body["access_token"]))
        if body.get("refresh_token"):
            row.refresh_token_ct = cipher.encrypt(str(body["refresh_token"]))
        row.expires_at = _expiry(body)
        row.last_refresh_at = now
        row.last_error = None
        token = str(body["access_token"])
        await db.commit()
        return token


def unit_for(row: Optional[JobBoardConnection], board: str) -> Optional[str]:
    override = str(getattr(settings, _UNIT_OVERRIDE.get(board, ""), "") or "").strip()
    if override:
        return override
    if row is None:
        return None
    value = (row.organization_units or {}).get(board)
    return str(value) if value else None
