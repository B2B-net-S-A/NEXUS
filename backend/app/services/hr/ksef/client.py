"""Klient API KSeF 2.0 — uwierzytelnienie tokenem, metadane i XML faktur.

Uwierzytelnienie tokenem KSeF (dokumentacja MF „Uwierzytelnianie”, 2.2):

1. ``POST /auth/challenge`` → ``challenge`` i ``timestampMs``,
2. ``GET /security/public-key-certificates`` → klucz ``KsefTokenEncryption``,
3. ``POST /auth/ksef-token`` z ``{token}|{timestampMs}`` zaszyfrowanym
   RSA-OAEP/SHA-256, kontekst ``Nip`` spółki → ``referenceNumber``
   i tymczasowy ``authenticationToken``,
4. ``GET /auth/{referenceNumber}`` do kodu 200 (100 = w toku),
5. ``POST /auth/token/redeem`` → ``accessToken`` (kilkanaście minut)
   i ``refreshToken`` (do 7 dni),
6. ``POST /auth/token/refresh`` z ``refreshToken`` — nowy ``accessToken``
   bez ponownego uwierzytelnienia.

Tokeny trzymamy w pamięci procesu (nie w bazie): pętla co godzinę odświeża
``accessToken`` jednym wywołaniem, a po restarcie uwierzytelnia się od nowa.

Limity: 429 z ``Retry-After`` — czekamy, gdy blokada jest krótka (do minuty,
najwyżej dwa razy), dłuższa przerywa przebieg z ``retry_after`` (pobieranie
zapisuje, kiedy wolno wrócić). 5xx i zerwane połączenie ponawiamy dwa razy.
Do logów trafia kategoria i status — bez tokenów, numerów KSeF i NIP-ów.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Awaitable, Callable, Optional

import httpx

from app.services.hr.ksef import crypto, numbers

logger = logging.getLogger(__name__)

SUBJECT_SELLER = "Subject1"
SUBJECT_BUYER = "Subject2"
SUBJECT_TYPES = (SUBJECT_SELLER, SUBJECT_BUYER)
DATE_TYPES = ("Issue", "Invoicing", "PermanentStorage")
PAGE_SIZE_MAX = 250
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
#: Dłużej nie czekamy w przebiegu — przerywamy i wracamy po blokadzie.
MAX_RETRY_AFTER = 60.0
DEFAULT_RETRY_AFTER = 30.0
RATE_LIMIT_ATTEMPTS = 3
SERVER_ERROR_DELAYS = (2.0, 5.0)
SERVER_ERRORS = frozenset({500, 502, 503, 504})
AUTH_POLL_DELAYS = (0.5, 1.0, 1.0, 2.0, 2.0, 3.0, 3.0, 5.0, 5.0)
TOKEN_MARGIN = timedelta(seconds=60)
PUBLIC_KEYS_TTL = timedelta(hours=12)
MAX_XML_BYTES = 5 * 1024 * 1024

#: Kody błędów API (``errors[].code`` / ``exceptionDetailList[].exceptionCode``).
CODE_NOT_FOUND = 21164
CODE_NOT_READY = 21165
CODE_UNKNOWN_KEY = 21470
CODE_UNAUTHORIZED = 21301

ERROR_MESSAGES = {
    "auth_failed": "KSeF odrzucił uwierzytelnienie tokenem spółki.",
    "forbidden": "Token KSeF spółki nie ma uprawnienia do odczytu faktur.",
    "rate_limited": "KSeF chwilowo ogranicza liczbę zapytań.",
    "unavailable": "KSeF nie odpowiada.",
    "rejected": "KSeF odrzucił zapytanie.",
    "not_ready": "Faktura jest w KSeF, ale nie jest jeszcze gotowa do pobrania.",
    "not_found": "Nie ma takiej faktury w KSeF.",
    "invalid_response": "KSeF zwrócił odpowiedź w nieoczekiwanym kształcie.",
    "too_large": "Plik faktury z KSeF jest większy niż 5 MB.",
    "public_key": "Brak ważnego klucza publicznego MF do szyfrowania tokenu.",
    "internal": "Pobieranie z KSeF przerwał błąd w NEXUSIE — szczegóły są w logu serwera.",
}
#: Kody statusu uwierzytelnienia (``GET /auth/{referenceNumber}``).
AUTH_STATUS_LABELS = {
    415: "brak uprawnień tokenu w kontekście spółki",
    425: "uwierzytelnienie unieważnione",
    450: "nieprawidłowy, nieaktywny albo unieważniony token",
    460: "błąd certyfikatu",
    470: "uwierzytelnienie odrzucone",
    480: "uwierzytelnienie zablokowane przez MF",
    500: "nieznany błąd KSeF",
    550: "operacja anulowana przez KSeF",
}


class KsefApiError(Exception):
    """Odmowa albo awaria KSeF. ``label`` idzie do stanu i logów, ``message`` do UI."""

    def __init__(
        self,
        category: str,
        *,
        status: Optional[int] = None,
        code: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        self.category = category
        self.status = status
        self.code = code
        self.retry_after = retry_after
        super().__init__(self.label)

    @property
    def label(self) -> str:
        detail = self.code or self.status
        return f"{self.category} ({detail})" if detail else self.category

    @property
    def message(self) -> str:
        text = ERROR_MESSAGES.get(self.category, ERROR_MESSAGES["unavailable"])
        if self.category == "auth_failed" and self.code in AUTH_STATUS_LABELS:
            return f"{text[:-1]}: {AUTH_STATUS_LABELS[self.code]}."
        if self.category == "rejected" and self.code:
            return f"{text[:-1]} (kod {self.code})."
        return text


@dataclass
class _Tokens:
    access: str
    access_until: datetime
    refresh: Optional[str]
    refresh_until: Optional[datetime]


@dataclass(frozen=True)
class MetadataPage:
    invoices: list[dict[str, Any]]
    has_more: bool
    is_truncated: bool
    #: ``permanentStorageHwmDate`` w postaci z odpowiedzi (pełna precyzja).
    hwm: Optional[str]


#: Tokeny dostępu per (adres, NIP spółki, skrót tokenu KSeF) — tylko w pamięci.
_SESSIONS: dict[str, _Tokens] = {}
#: Certyfikaty kluczy publicznych MF per adres środowiska.
_PUBLIC_KEYS: dict[str, tuple[datetime, list[dict[str, Any]]]] = {}


def forget_sessions() -> None:
    """Czyści tokeny i klucze w pamięci (testy, zmiana tokenu)."""

    _SESSIONS.clear()
    _PUBLIC_KEYS.clear()


def parse_instant(raw: Any) -> Optional[datetime]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        moment = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def format_instant(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="milliseconds")


def _retry_after(response: httpx.Response, now: datetime) -> float:
    raw = (response.headers.get("Retry-After") or "").strip()
    if raw.isdigit():
        return float(raw)
    if raw:
        try:
            moment = parsedate_to_datetime(raw)
        except (TypeError, ValueError):
            return DEFAULT_RETRY_AFTER
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return max((moment - now).total_seconds(), 0.0)
    return DEFAULT_RETRY_AFTER


def _error_codes(response: httpx.Response) -> list[int]:
    try:
        payload = response.json()
    except ValueError:
        return []
    if not isinstance(payload, dict):
        return []
    codes: list[int] = []
    for error in payload.get("errors") or []:
        if isinstance(error, dict) and isinstance(error.get("code"), int):
            codes.append(error["code"])
    exception = payload.get("exception") or {}
    if isinstance(exception, dict):
        for detail in exception.get("exceptionDetailList") or []:
            if isinstance(detail, dict) and isinstance(
                detail.get("exceptionCode"), int
            ):
                codes.append(detail["exceptionCode"])
    return codes


def _error_for(response: httpx.Response) -> KsefApiError:
    status = response.status_code
    codes = _error_codes(response)
    code = codes[0] if codes else None
    if status == 401 or code == CODE_UNAUTHORIZED:
        return KsefApiError("auth_failed", status=status, code=code)
    if status == 403:
        return KsefApiError("forbidden", status=status)
    if code == CODE_NOT_FOUND:
        return KsefApiError("not_found", status=status, code=code)
    if code == CODE_NOT_READY:
        return KsefApiError("not_ready", status=status, code=code)
    return KsefApiError("rejected", status=status, code=code)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError:
        raise KsefApiError("invalid_response", status=response.status_code) from None
    if not isinstance(payload, dict):
        raise KsefApiError("invalid_response", status=response.status_code)
    return payload


def _token_info(payload: Any) -> tuple[str, Optional[datetime]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("token"), str):
        raise KsefApiError("invalid_response")
    return payload["token"], parse_instant(payload.get("validUntil"))


class KsefClient:
    """Jedno połączenie z API KSeF w kontekście NIP-u spółki."""

    def __init__(
        self,
        base_url: str,
        *,
        context_nip: str,
        token: str,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._context_nip = context_nip
        self._token = token
        self._transport = transport
        self._sleep = sleep
        self._now = now
        self._http: Optional[httpx.AsyncClient] = None
        fingerprint = hashlib.sha256(token.encode("utf-8")).hexdigest()[:16]
        self._session_key = f"{self._base_url}|{context_nip}|{fingerprint}"
        self.requests = 0

    async def __aenter__(self) -> "KsefClient":
        self._http = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=REQUEST_TIMEOUT,
            transport=self._transport,
            headers={"Accept": "application/json", "X-Error-Format": "problem-details"},
        )
        return self

    async def __aexit__(self, *_exc: object) -> None:
        if self._http is not None:
            await self._http.aclose()
            self._http = None

    # ── Transport ────────────────────────────────────────────────────────────

    async def _send(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        bearer: Optional[str] = None,
        accept: Optional[str] = None,
    ) -> httpx.Response:
        if self._http is None:
            raise RuntimeError("KsefClient używaj w `async with`")
        headers: dict[str, str] = {}
        if bearer:
            headers["Authorization"] = f"Bearer {bearer}"
        if accept:
            headers["Accept"] = accept
        rate_attempts = 0
        server_attempts = 0
        while True:
            self.requests += 1
            try:
                response = await self._http.request(
                    method, path, json=json_body, params=params, headers=headers
                )
            except httpx.HTTPError as exc:
                if server_attempts < len(SERVER_ERROR_DELAYS):
                    await self._sleep(SERVER_ERROR_DELAYS[server_attempts])
                    server_attempts += 1
                    continue
                logger.warning("ksef: brak odpowiedzi (%s)", type(exc).__name__)
                raise KsefApiError("unavailable") from None
            status = response.status_code
            if status == 429:
                wait = _retry_after(response, self._now())
                rate_attempts += 1
                if wait <= MAX_RETRY_AFTER and rate_attempts < RATE_LIMIT_ATTEMPTS:
                    await self._sleep(wait)
                    continue
                logger.warning("ksef: limit zapytań, blokada %.0f s", wait)
                raise KsefApiError("rate_limited", status=429, retry_after=wait)
            if status in SERVER_ERRORS:
                if server_attempts < len(SERVER_ERROR_DELAYS):
                    await self._sleep(SERVER_ERROR_DELAYS[server_attempts])
                    server_attempts += 1
                    continue
                logger.warning("ksef: błąd serwera %s", status)
                raise KsefApiError("unavailable", status=status)
            return response

    # ── Uwierzytelnienie ─────────────────────────────────────────────────────

    async def _public_keys(self, *, refresh: bool) -> list[dict[str, Any]]:
        cached = _PUBLIC_KEYS.get(self._base_url)
        now = self._now()
        if cached and not refresh and now - cached[0] < PUBLIC_KEYS_TTL:
            return cached[1]
        response = await self._send("GET", "/security/public-key-certificates")
        if response.status_code != 200:
            raise _error_for(response)
        try:
            payload = response.json()
        except ValueError:
            raise KsefApiError("invalid_response", status=200) from None
        if not isinstance(payload, list):
            raise KsefApiError("invalid_response", status=200)
        _PUBLIC_KEYS[self._base_url] = (now, payload)
        return payload

    async def _start_authentication(self, *, refresh_keys: bool) -> httpx.Response:
        challenge = await self._send("POST", "/auth/challenge")
        if challenge.status_code != 200:
            raise _error_for(challenge)
        data = _json_object(challenge)
        timestamp_ms = data.get("timestampMs")
        if not isinstance(timestamp_ms, int):
            moment = parse_instant(data.get("timestamp"))
            if moment is None:
                raise KsefApiError("invalid_response")
            timestamp_ms = int(moment.timestamp() * 1000)
        if not isinstance(data.get("challenge"), str):
            raise KsefApiError("invalid_response")
        try:
            key = crypto.pick_token_key(
                await self._public_keys(refresh=refresh_keys), self._now()
            )
        except crypto.PublicKeyError:
            raise KsefApiError("public_key") from None
        body: dict[str, Any] = {
            "challenge": data["challenge"],
            "contextIdentifier": {"type": "Nip", "value": self._context_nip},
            "encryptedToken": crypto.encrypt_token(
                self._token, timestamp_ms, key.public_key
            ),
        }
        if key.public_key_id:
            body["publicKeyId"] = key.public_key_id
        return await self._send("POST", "/auth/ksef-token", json_body=body)

    async def _authenticate(self) -> _Tokens:
        response = await self._start_authentication(refresh_keys=False)
        if response.status_code == 400 and CODE_UNKNOWN_KEY in _error_codes(response):
            # MF wymienił klucz — pobieramy listę od nowa i próbujemy raz jeszcze.
            response = await self._start_authentication(refresh_keys=True)
        if response.status_code not in (200, 202):
            raise _error_for(response)
        init = _json_object(response)
        reference = init.get("referenceNumber")
        operation_token, _ = _token_info(init.get("authenticationToken"))
        if not isinstance(reference, str) or not reference:
            raise KsefApiError("invalid_response")
        await self._wait_for_authentication(reference, operation_token)

        redeemed = await self._send(
            "POST", "/auth/token/redeem", bearer=operation_token
        )
        if redeemed.status_code != 200:
            raise _error_for(redeemed)
        tokens = _json_object(redeemed)
        access, access_until = _token_info(tokens.get("accessToken"))
        refresh, refresh_until = _token_info(tokens.get("refreshToken"))
        return _Tokens(
            access=access,
            access_until=access_until or self._now() + timedelta(minutes=10),
            refresh=refresh,
            refresh_until=refresh_until,
        )

    async def _wait_for_authentication(
        self, reference: str, operation_token: str
    ) -> None:
        for delay in (0.0, *AUTH_POLL_DELAYS):
            if delay:
                await self._sleep(delay)
            response = await self._send(
                "GET", f"/auth/{reference}", bearer=operation_token
            )
            if response.status_code != 200:
                raise _error_for(response)
            status = _json_object(response).get("status") or {}
            code = status.get("code") if isinstance(status, dict) else None
            if code == 200:
                return
            if code != 100:
                logger.warning("ksef: uwierzytelnienie odrzucone (status %s)", code)
                raise KsefApiError(
                    "auth_failed", code=code if isinstance(code, int) else None
                )
        raise KsefApiError("unavailable", code=100)

    async def _refresh(self, tokens: _Tokens) -> _Tokens:
        response = await self._send(
            "POST", "/auth/token/refresh", bearer=tokens.refresh
        )
        if response.status_code != 200:
            raise _error_for(response)
        access, access_until = _token_info(_json_object(response).get("accessToken"))
        return _Tokens(
            access=access,
            access_until=access_until or self._now() + timedelta(minutes=10),
            refresh=tokens.refresh,
            refresh_until=tokens.refresh_until,
        )

    async def access_token(self) -> str:
        now = self._now()
        tokens = _SESSIONS.get(self._session_key)
        if tokens and tokens.access_until - TOKEN_MARGIN > now:
            return tokens.access
        if (
            tokens
            and tokens.refresh
            and (
                tokens.refresh_until is None
                or tokens.refresh_until - TOKEN_MARGIN > now
            )
        ):
            try:
                tokens = await self._refresh(tokens)
            except KsefApiError as exc:
                if exc.category not in {"auth_failed", "rejected"}:
                    raise
                tokens = None
            if tokens is not None:
                _SESSIONS[self._session_key] = tokens
                return tokens.access
        _SESSIONS.pop(self._session_key, None)
        tokens = await self._authenticate()
        _SESSIONS[self._session_key] = tokens
        return tokens.access

    async def _authorized(
        self,
        method: str,
        path: str,
        *,
        json_body: Optional[dict[str, Any]] = None,
        params: Optional[dict[str, Any]] = None,
        accept: Optional[str] = None,
    ) -> httpx.Response:
        response = await self._send(
            method,
            path,
            json_body=json_body,
            params=params,
            bearer=await self.access_token(),
            accept=accept,
        )
        if response.status_code == 401:
            # Token wygasł albo MF go unieważnił — jeden nowy przebieg uwierzytelnienia.
            tokens = _SESSIONS.get(self._session_key)
            if tokens is not None:
                tokens.access_until = self._now() - TOKEN_MARGIN
            response = await self._send(
                method,
                path,
                json_body=json_body,
                params=params,
                bearer=await self.access_token(),
                accept=accept,
            )
        return response

    # ── Faktury ──────────────────────────────────────────────────────────────

    async def query_metadata(
        self,
        *,
        subject_type: str,
        date_from: str,
        date_to: Optional[str] = None,
        date_type: str = "PermanentStorage",
        seller_nip: Optional[str] = None,
        page_offset: int = 0,
        page_size: int = PAGE_SIZE_MAX,
    ) -> MetadataPage:
        """``POST /invoices/query/metadata`` — jedna strona, sortowanie rosnąco.

        Dla ``PermanentStorage`` zawsze z ``restrictToPermanentStorageHwmDate``:
        dane do znacznika HWM są kompletne i nie zmienią się przy kolejnym
        zapytaniu (pobieranie przyrostowe bez dziur).
        """

        if subject_type not in SUBJECT_TYPES:
            raise ValueError(f"nieobsługiwany subjectType: {subject_type}")
        if date_type not in DATE_TYPES:
            raise ValueError(f"nieobsługiwany dateType: {date_type}")
        date_range: dict[str, Any] = {"dateType": date_type, "from": date_from}
        if date_to:
            date_range["to"] = date_to
        if date_type == "PermanentStorage":
            date_range["restrictToPermanentStorageHwmDate"] = True
        body: dict[str, Any] = {"subjectType": subject_type, "dateRange": date_range}
        if seller_nip:
            body["sellerNip"] = seller_nip
        response = await self._authorized(
            "POST",
            "/invoices/query/metadata",
            json_body=body,
            params={
                "pageOffset": page_offset,
                "pageSize": max(10, min(page_size, PAGE_SIZE_MAX)),
                "sortOrder": "Asc",
            },
        )
        if response.status_code != 200:
            raise _error_for(response)
        payload = _json_object(response)
        invoices = payload.get("invoices")
        if not isinstance(invoices, list) or not isinstance(
            payload.get("hasMore"), bool
        ):
            raise KsefApiError("invalid_response", status=200)
        hwm = payload.get("permanentStorageHwmDate")
        return MetadataPage(
            invoices=[item for item in invoices if isinstance(item, dict)],
            has_more=payload["hasMore"],
            is_truncated=bool(payload.get("isTruncated")),
            hwm=hwm if isinstance(hwm, str) and parse_instant(hwm) else None,
        )

    async def download_invoice(self, ksef_number: str) -> bytes:
        """``GET /invoices/ksef/{numer}`` — XML faktury, sprawdzony skrótem z nagłówka."""

        if not numbers.is_valid(ksef_number):
            raise KsefApiError("invalid_response")
        response = await self._authorized(
            "GET", f"/invoices/ksef/{ksef_number}", accept="application/xml"
        )
        if response.status_code != 200:
            raise _error_for(response)
        content = response.content
        if len(content) > MAX_XML_BYTES:
            raise KsefApiError("too_large", status=200)
        expected = response.headers.get("x-ms-meta-hash")
        if expected:
            actual = base64.b64encode(hashlib.sha256(content).digest()).decode("ascii")
            if actual != expected.strip():
                logger.warning(
                    "ksef: skrót pobranej faktury nie zgadza się z nagłówkiem"
                )
                raise KsefApiError("invalid_response", status=200)
        return content
