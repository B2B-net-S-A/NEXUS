"""Połączone konto firmy w JustJoin.IT / RocketJobs — klucz API albo OAuth (0381).

Dwa tryby (``auth_mode``):

* ``static`` — statyczny klucz API (JWT ważny do 2 lat) z env
  ``JJIT_STATIC_ACCESS_TOKEN``. Rekomendacja dostawcy dla integracji
  serwer-serwer (29.09.2026): bez przycisku „Połącz”, bez rotacji refresh
  tokenu. Jednostkę organizacyjną czytamy raz z ``/organizations/units``.
* ``oauth`` — ``authorization_code`` + ``refresh_token``. Admin łączy konto
  RAZ w Ustawieniach → Portale ogłoszeniowe; dalej odświeżany token.

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
import hmac
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.encryption import get_token_cipher
from app.models.app_setting import AppSetting
from app.models.job_board_connection import (
    PROVIDER_JJIT,
    STATUS_ACTIVE,
    STATUS_RECONNECT_REQUIRED,
    JobBoardConnection,
)
from app.services.job_portals.base import (
    PortalError,
    PortalReconnectRequired,
    jjit_static_token,
)

logger = logging.getLogger(__name__)

STATE_PURPOSE = "jjit_oauth_state"
_STATE_TTL_SECONDS = 600
_STATE_ALGORITHM = "HS256"
# Token odświeżamy z zapasem — żądanie w toku nie może trafić na wygasły.
_EXPIRY_MARGIN = timedelta(seconds=90)

# Nadpisania jednostek z env mają pierwszeństwo przed jednostką konta.
_UNIT_OVERRIDE = {
    "justjoinit": "PORTAL_JJIT_ORGANIZATION_UNIT_ID",
    "rocketjobs": "PORTAL_ROCKETJOBS_ORGANIZATION_UNIT_ID",
}
# Sandbox 29.09.2026: `/oauth/me` niesie `organization_id` — to ID ORGANIZACJI,
# nie jednostki (ścieżki ogłoszeń z nim nie działają). Jednostkę podaje
# `GET /employer/organizations/units`; jedna jednostka obsługuje oba portale.
_UNIT_CLAIMS = ("organization_unit_id", "organizationUnitId")


STATIC_UNITS_KEY = "jjit_static_units"
# Ostrzeżenie w Ustawieniach i w `checks.job_portals` na tyle dni przed końcem
# ważności klucza API — dostawca wystawia nowy na prośbę.
STATIC_TOKEN_WARN_DAYS = 30


def auth_mode() -> str:
    return "static" if jjit_static_token() else "oauth"


def static_token_expires_at() -> Optional[datetime]:
    """``exp`` z klucza API — WYŁĄCZNIE do wyświetlenia (bez weryfikacji
    podpisu: sekret zna tylko dostawca, a ważność i tak sprawdza portal)."""
    token = jjit_static_token()
    if not token:
        return None
    try:
        claims = jwt.get_unverified_claims(token)
        return datetime.fromtimestamp(int(claims["exp"]), tz=timezone.utc)
    except (JWTError, KeyError, TypeError, ValueError, OverflowError):
        return None


def static_token_expiring(now: Optional[datetime] = None) -> bool:
    """Klucz API wygasa w ciągu ``STATIC_TOKEN_WARN_DAYS`` dni (albo wygasł)."""
    expires = static_token_expires_at()
    if expires is None:
        return False
    now = now or datetime.now(timezone.utc)
    return expires - now <= timedelta(days=STATIC_TOKEN_WARN_DAYS)


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


def _challenge_for(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def _signing_key() -> str:
    return settings.M365_STATE_SIGNING_KEY or settings.SECRET_KEY


# Runda 10 (R10-N10-8, bliźniak R9-N1-4): weryfikator PKCE jechał JAWNIE
# w ``state``, a ``state`` był wielokrotnego użytku przez 10 min. Kto zdobył
# adres logowania admina (historia przeglądarki, logi dostawcy), logował się
# nim na SWOJE konto portalu i NEXUS podpinał je jako konto firmy. Teraz
# ``state`` niesie tylko losowy ``n``, weryfikator wylicza serwer
# (HMAC klucza podpisu), a callback zużywa ``n`` jednorazowo.
def pkce_verifier_for(nonce: str) -> str:
    digest = hmac.new(
        _signing_key().encode("utf-8"),
        f"jjit-pkce:{nonce}".encode("utf-8"),
        hashlib.sha256,
    ).digest()
    # 43 znaki alfabetu base64url — mieści się w RFC 7636 (43–128).
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass(frozen=True)
class OAuthState:
    user_id: int
    verifier: str
    nonce_digest: str
    expires_at: datetime


def sign_state(user_id: int, nonce: Optional[str] = None) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(user_id),
            "n": nonce or secrets.token_urlsafe(24),
            "iat": now,
            "exp": now + timedelta(seconds=_STATE_TTL_SECONDS),
            "purpose": STATE_PURPOSE,
        },
        _signing_key(),
        algorithm=_STATE_ALGORITHM,
    )


def verify_state(token: str) -> OAuthState:
    """Stan logowania albo ``JWTError`` — także przy obcym ``purpose`` i przy
    ``state`` sprzed rundy 10 (bez ``n``)."""
    payload = jwt.decode(token, _signing_key(), algorithms=[_STATE_ALGORITHM])
    if payload.get("purpose") != STATE_PURPOSE:
        raise JWTError("wrong purpose")
    nonce = payload.get("n")
    if not isinstance(nonce, str) or not nonce:
        raise JWTError("state without nonce")
    return OAuthState(
        user_id=int(payload["sub"]),
        verifier=pkce_verifier_for(nonce),
        nonce_digest=hashlib.sha256(nonce.encode("utf-8")).hexdigest(),
        expires_at=datetime.fromtimestamp(int(payload["exp"]), tz=timezone.utc),
    )


_CONSUMED_STATES_KEY = "jjit_oauth_consumed_states"


async def consume_state(db: AsyncSession, state: OAuthState) -> bool:
    """Zużywa ``state`` (bez commitu). ``False`` = ten ``state`` już wrócił.

    Wiersz ``app_settings`` pod blokadą serializuje równoległe callbacki; w
    wartości leżą skróty ``n`` (nie same ``n``) do upływu ich ważności.
    """
    await db.execute(
        pg_insert(AppSetting)
        .values(key=_CONSUMED_STATES_KEY, value={})
        .on_conflict_do_nothing(index_elements=["key"])
    )
    row = await db.scalar(
        select(AppSetting)
        .where(AppSetting.key == _CONSUMED_STATES_KEY)
        .with_for_update()
    )
    now = datetime.now(timezone.utc)
    seen: dict[str, str] = {}
    for digest, expires in (row.value or {}).items():
        try:
            if datetime.fromisoformat(expires) > now:
                seen[digest] = expires
        except (TypeError, ValueError):
            continue
    if state.nonce_digest in seen:
        return False
    seen[state.nonce_digest] = state.expires_at.isoformat()
    row.value = seen
    await db.flush()
    return True


def authorize_url(user_id: int) -> str:
    if not oauth_configured():
        raise ConnectionNotConfigured("Brak konfiguracji aplikacji OAuth portalu.")
    nonce = secrets.token_urlsafe(24)
    query = urlencode(
        {
            "response_type": "code",
            "client_id": settings.JJIT_OAUTH_CLIENT_ID,
            "redirect_uri": settings.JJIT_OAUTH_REDIRECT_URI,
            "scope": settings.JJIT_OAUTH_SCOPE,
            "state": sign_state(user_id, nonce),
            "code_challenge": _challenge_for(pkce_verifier_for(nonce)),
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


def resolve_units(
    claims: dict[str, Any], units: Optional[list[dict[str, Any]]] = None
) -> dict[str, str]:
    """Jednostka per portal: env > claim jednostki > JEDYNA jednostka konta.

    Konto z kilkoma jednostkami bez nadpisania w env zostaje bez jednostki —
    publikacja mówi wtedy wprost, że trzeba ją ustawić (zgadywanie wydałoby
    kredyt innej jednostki).
    """
    claimed = next((str(claims[key]) for key in _UNIT_CLAIMS if claims.get(key)), None)
    if claimed is None and units and len(units) == 1 and units[0].get("id"):
        claimed = str(units[0]["id"])
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

    api = JjitApi(_fixed, transport=transport)
    claims = await api.me()
    units = await api.units()
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
    row.organization_units = resolve_units(claims, units)
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
    static = jjit_static_token()
    if static:
        if force_refresh:
            # Klient ponawia raz po 401 z `force_refresh=True`; klucza API nie
            # da się odświeżyć — odrzucony znaczy nieważny albo wygasły.
            raise PortalReconnectRequired(
                "Portal odrzucił klucz API albo klucz wygasł — poproś RocketJobs "
                "o nowy i podmień JJIT_STATIC_ACCESS_TOKEN."
            )
        return static
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


def _token_fingerprint(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]


async def resolve_unit(db: AsyncSession, board: str) -> Optional[str]:
    """Jednostka dla portalu: env > wiersz połączenia > (tryb klucza API)
    jednostka konta z ``/organizations/units``, zapamiętana per klucz.

    Pamięć niesie odcisk klucza — nowy klucz (np. inne konto) czyta jednostkę
    od nowa zamiast publikować na starej.
    """
    row = await load(db)
    unit = unit_for(row, board)
    token = jjit_static_token()
    if unit or not token:
        return unit
    fingerprint = _token_fingerprint(token)
    cached = await db.get(AppSetting, STATIC_UNITS_KEY)
    value = (
        cached.value if cached is not None and isinstance(cached.value, dict) else {}
    )
    if value.get("token") == fingerprint and isinstance(value.get("units"), dict):
        return value["units"].get(board)
    from app.services.job_portals.jjit_client import JjitApi

    units = resolve_units({}, await JjitApi().units())
    stmt = pg_insert(AppSetting).values(
        key=STATIC_UNITS_KEY, value={"token": fingerprint, "units": units}
    )
    await db.execute(
        stmt.on_conflict_do_update(
            index_elements=[AppSetting.key],
            set_={"value": stmt.excluded.value},
        )
    )
    await db.commit()
    return units.get(board)


def unit_for(row: Optional[JobBoardConnection], board: str) -> Optional[str]:
    override = str(getattr(settings, _UNIT_OVERRIDE.get(board, ""), "") or "").strip()
    if override:
        return override
    if row is None:
        return None
    value = (row.organization_units or {}).get(board)
    return str(value) if value else None
