"""Klient API EBI24 v1 (podręcznik 1.9.1) — wyłącznie odczyt.

Każde żądanie niesie dwa wyliczane nagłówki:

* ``X-EBI24-SIGNATURE`` — HMAC-SHA256 kluczem komunikacji z
  ``base64(treść) + akcja + znacznik + UUID konta``,
* ``X-EBI24-CREDENTIALS`` — AES-256-ECB/PKCS5 tym samym kluczem z
  ``sesja.sekret.odcisk.znacznik``. ECB narzuca podręcznik, nie my.

Zasady z podręcznika, których pilnuje klient: treść serializowana raz i
podpisywana jako te same bajty, znacznik liczony przy każdej próbie i rosnący,
żądania kolejno (najwyżej jedno naraz, co sekundę = 60 na minutę), metoda POST,
429 z ``Retry-After``, ponawianie błędów sieci z rosnącym odstępem. Identyfikator
sesji zmienia się raz na dobę, bo pierwsze żądanie nowej sesji jest kosztowne.

``READ_ACTIONS`` to lista akcji, które klient w ogóle wyśle: ``bucket/create``
świadomie na niej nie ma. Do logów trafia kategoria, status HTTP i akcja — bez
kluczy, UUID, treści żądań i odpowiedzi.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Optional

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from app.services.ebi24.environment import Ebi24Config

logger = logging.getLogger(__name__)

READ_ACTIONS = frozenset(
    {
        "bucket/index",
        "bucket/getDocument",
        "bucket/getKsefData",
        "archive/getKsefData",
    }
)
#: Serwer przerywa zapytania po 20 s, więc 30 s obejmuje też pobranie wyniku.
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
FINGERPRINT = "NEXUS_BACKEND"
MIN_REQUEST_INTERVAL = 1.0
PAGE_SIZE_MAX = 500
MAX_XML_BYTES = 5 * 1024 * 1024
#: Dłużej nie czekamy w przebiegu — przerywamy i podajemy czas powrotu.
MAX_RETRY_AFTER = 60.0
DEFAULT_RETRY_AFTER = 30.0
RATE_LIMIT_ATTEMPTS = 3
NETWORK_DELAYS = (1.0, 2.0, 4.0)
SERVER_ERRORS = frozenset({500, 502, 503, 504})

ERROR_MESSAGES = {
    "auth_failed": "EBI24 odrzuciło uwierzytelnienie (podpis, klucze albo uprawnienia API).",
    "not_authorized": "EBI24 nie wpuszcza tego serwera (adres IP spoza listy zaufanych).",
    "rate_limited": "EBI24 chwilowo ogranicza liczbę zapytań.",
    "unavailable": "EBI24 nie odpowiada.",
    "rejected": "EBI24 odrzuciło zapytanie.",
    "not_found": "EBI24 nie ma takiego dokumentu albo danych KSeF.",
    "invalid_response": "EBI24 zwróciło odpowiedź w nieoczekiwanym kształcie.",
    "too_large": "Plik z EBI24 jest większy niż 5 MB.",
}


class Ebi24ApiError(Exception):
    def __init__(
        self,
        category: str,
        *,
        status: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> None:
        super().__init__(ERROR_MESSAGES[category])
        self.category = category
        self.status = status
        self.retry_after = retry_after


@dataclass(frozen=True)
class DocumentPage:
    documents: tuple[dict[str, Any], ...]
    total: int


def build_signature(
    body: bytes, action: str, timestamp: str, account_uuid: str, key: bytes
) -> str:
    signed = base64.b64encode(body).decode("ascii") + action + timestamp + account_uuid
    digest = hmac.new(key, signed.encode("utf-8"), hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def build_credentials(
    session_id: str, secret_phrase: str, fingerprint: str, timestamp: str, key: bytes
) -> str:
    plain = f"{session_id}.{secret_phrase}.{fingerprint}.{timestamp}".encode("utf-8")
    padder = padding.PKCS7(algorithms.AES.block_size).padder()
    padded = padder.update(plain) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()  # noqa: S305
    return base64.b64encode(encryptor.update(padded) + encryptor.finalize()).decode(
        "ascii"
    )


def _retry_after(response: httpx.Response) -> float:
    try:
        return max(float(response.headers.get("Retry-After", "")), 0.0)
    except ValueError:
        return DEFAULT_RETRY_AFTER


def _is_json(response: httpx.Response) -> bool:
    return "application/json" in response.headers.get("content-type", "")


class Ebi24Client:
    """Klient na jeden przebieg: ``async with Ebi24Client(config) as client``."""

    def __init__(
        self,
        config: Ebi24Config,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        if config.api_url is None:
            raise ValueError(f"tryb {config.mode} nie ma adresu API")
        self._config = config
        self._key = config.key_bytes
        self._now = now
        self._sleep = sleep
        self._lock = asyncio.Lock()
        self._last_timestamp = 0
        self._http = httpx.AsyncClient(
            base_url=config.api_url, timeout=REQUEST_TIMEOUT, transport=transport
        )

    async def __aenter__(self) -> "Ebi24Client":
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self._http.aclose()

    def _now_ms(self) -> int:
        return int(self._now().timestamp() * 1000)

    async def _pace(self) -> None:
        if not self._last_timestamp:
            return
        waited = (self._now_ms() - self._last_timestamp) / 1000
        if waited < MIN_REQUEST_INTERVAL:
            await self._sleep(MIN_REQUEST_INTERVAL - waited)

    def _headers(self, action: str, body: bytes) -> dict[str, str]:
        self._last_timestamp = max(self._now_ms(), self._last_timestamp + 1)
        timestamp = str(self._last_timestamp)
        session_id = f"NEXUS_{self._now():%Y%m%d}"
        return {
            "X-EBI24-SIGNATURE": build_signature(
                body, action, timestamp, self._config.account_uuid, self._key
            ),
            "X-EBI24-CREDENTIALS": build_credentials(
                session_id,
                self._config.secret_phrase,
                FINGERPRINT,
                timestamp,
                self._key,
            ),
            "X-EBI24-USER-UUID": self._config.user_uuid,
            "X-EBI24-ACCOUNT-UUID": self._config.account_uuid,
            "Content-Type": "application/json",
        }

    def _fail(
        self,
        category: str,
        action: str,
        *,
        status: Optional[int] = None,
        retry_after: Optional[float] = None,
    ) -> Ebi24ApiError:
        logger.warning("ebi24: %s (HTTP %s, akcja %s)", category, status, action)
        return Ebi24ApiError(category, status=status, retry_after=retry_after)

    async def _send(self, action: str, payload: dict[str, Any]) -> httpx.Response:
        if action not in READ_ACTIONS:
            raise ValueError(f"akcja {action} nie jest na liście odczytu")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
        async with self._lock:
            return await self._send_locked(action, body)

    async def _send_locked(self, action: str, body: bytes) -> httpx.Response:
        rate_limited = 0
        failures = 0
        while True:
            await self._pace()
            try:
                response = await self._http.post(
                    action, content=body, headers=self._headers(action, body)
                )
            except httpx.HTTPError:
                response = None
            if response is None or response.status_code in SERVER_ERRORS:
                if failures >= len(NETWORK_DELAYS):
                    raise self._fail(
                        "unavailable",
                        action,
                        status=response.status_code if response is not None else None,
                    )
                await self._sleep(NETWORK_DELAYS[failures])
                failures += 1
                continue
            if response.status_code == 429:
                delay = _retry_after(response)
                rate_limited += 1
                if delay > MAX_RETRY_AFTER or rate_limited >= RATE_LIMIT_ATTEMPTS:
                    raise self._fail(
                        "rate_limited", action, status=429, retry_after=delay
                    )
                await self._sleep(delay)
                continue
            return self._check_status(action, response)

    def _check_status(self, action: str, response: httpx.Response) -> httpx.Response:
        status = response.status_code
        if status == 200:
            return response
        category = {
            400: "rejected",
            401: "auth_failed",
            403: "not_authorized",
            404: "not_found",
        }.get(status, "invalid_response")
        raise self._fail(category, action, status=status)

    def _envelope(self, action: str, response: httpx.Response) -> dict[str, Any]:
        """Wynik mówi pole ``status`` koperty; treści komunikatów nie czytamy."""

        if not _is_json(response):
            # Podręcznik: serwer spoza Polski może dostać stronę „not authorized”.
            raise self._fail("not_authorized", action, status=response.status_code)
        try:
            envelope = response.json()["response"]
            status = envelope["status"]
        except (ValueError, KeyError, TypeError):
            raise self._fail(
                "invalid_response", action, status=response.status_code
            ) from None
        if status != 0:
            raise self._fail("rejected", action, status=response.status_code)
        return envelope

    async def list_documents(
        self,
        criteria: dict[str, Any],
        *,
        start_row: int,
        end_row: int,
        sort_by: Optional[list[str]] = None,
    ) -> DocumentPage:
        """Jedna strona nagłówków, najwyżej ``PAGE_SIZE_MAX`` wierszy."""

        action = "bucket/index"
        payload: dict[str, Any] = {
            "data": criteria,
            "startRow": start_row,
            "endRow": min(end_row, start_row + PAGE_SIZE_MAX),
        }
        if sort_by:
            payload["sortBy"] = sort_by
        envelope = self._envelope(action, await self._send(action, payload))
        data = envelope.get("data")
        total = envelope.get("actualTotalRows")
        if not isinstance(data, list) or not isinstance(total, int):
            raise self._fail("invalid_response", action, status=200)
        return DocumentPage(
            documents=tuple(row for row in data if isinstance(row, dict)),
            total=total,
        )

    async def get_document(self, document_id: str) -> dict[str, Any]:
        """Pełne dane dokumentu elektronicznego; plik binarny tu nie pasuje."""

        action = "bucket/getDocument"
        response = await self._send(action, {"data": {"_id": document_id}})
        data = self._envelope(action, response).get("data")
        if not isinstance(data, list) or not data or not isinstance(data[0], dict):
            raise self._fail("invalid_response", action, status=200)
        return data[0]

    async def get_ksef_xml(self, document_id: str, *, archive: bool = False) -> bytes:
        """XML faktury KSeF zapisany przy dokumencie EBI24."""

        action = "archive/getKsefData" if archive else "bucket/getKsefData"
        response = await self._send(action, {"data": {"_id": document_id}})
        if _is_json(response):
            # Brak uprawnienia do odczytu ma tu kod 200 i kopertę ze statusem -1.
            self._envelope(action, response)
            raise self._fail("invalid_response", action, status=200)
        if "xml" not in response.headers.get("content-type", ""):
            raise self._fail("not_authorized", action, status=200)
        if len(response.content) > MAX_XML_BYTES:
            raise self._fail("too_large", action, status=200)
        return response.content
