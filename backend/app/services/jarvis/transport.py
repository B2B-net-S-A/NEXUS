"""Wywołanie narzędzia = wywołanie istniejącego API, in-process, tokenem pytającego.

Precedens produkcyjny: ``app/tasks/saved_search_alerts.py`` (ASGITransport +
JWT właściciela). Tu jest lepiej — przekazujemy TOKEN Z ŻĄDANIA, więc podłoga
unieważnienia sesji, wersja autoryzacji i snapshot sekcji działają bez zmian,
a żadna bramka nie jest omijana: każde żądanie przechodzi całą aplikację od
middleware'ów po zależności trasy.

Przekazujemy:
- ``Authorization`` — tożsamość pytającego (obowiązkowo);
- ``X-Forwarded-For`` — adres przeglądarki; bez niego trasy liczące limit po
  IP (``client_ip_key``) wrzuciłyby WSZYSTKICH użytkowników Jarvisa do jednego
  kubełka ``127.0.0.1``;
- ``X-Operation-Id`` — jeden na turę, więc logi i Sentry wiążą kroki razem;
- ``X-Jarvis-Internal`` — sekret procesu → ``via: jarvis`` w ``activities``.

Nagłówka ``X-Impersonate-User-Id`` NIE przekazujemy: Jarvis w trybie
„podgląd jako" jest niedostępny już na wejściu trasy czatu.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

from app.services.jarvis.tools import RequestSpec
from app.services.jarvis.via_tag import INTERNAL_HEADER, internal_secret

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 45.0


@dataclass(frozen=True)
class ToolResponse:
    status: int
    data: Any

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300


@dataclass(frozen=True)
class CallerIdentity:
    authorization: str
    forwarded_for: Optional[str] = None
    operation_id: Optional[str] = None


def _error_detail(payload: Any) -> str:
    """Polski komunikat z odpowiedzi błędu — `detail` bywa napisem, obiektem albo listą."""
    if isinstance(payload, dict):
        detail = payload.get("detail", payload)
    else:
        detail = payload
    if isinstance(detail, str):
        return detail
    if isinstance(detail, dict):
        for key in ("message", "msg", "reason", "detail", "code"):
            value = detail.get(key)
            if isinstance(value, str) and value:
                return value
    if isinstance(detail, list) and detail:
        first = detail[0]
        if isinstance(first, dict) and isinstance(first.get("msg"), str):
            loc = ".".join(str(p) for p in first.get("loc", []) if p != "body")
            return f"{loc}: {first['msg']}" if loc else first["msg"]
    return "Nieznany błąd"


def describe_error(response: ToolResponse) -> str:
    detail = _error_detail(response.data)
    prefix = {
        401: "Sesja wygasła",
        403: "Brak uprawnień użytkownika do tych danych",
        404: "Nie znaleziono",
        409: "Konflikt",
        422: "Nieprawidłowe dane",
        429: "Za dużo zapytań — spróbuj za chwilę",
        503: "Usługa chwilowo niedostępna",
    }.get(response.status, f"Błąd {response.status}")
    return f"{prefix}: {detail}" if detail and detail != prefix else prefix


class JarvisTransport:
    """Klient ASGI na jedną turę. Używać jako ``async with``."""

    def __init__(self, identity: CallerIdentity) -> None:
        self._identity = identity
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "JarvisTransport":
        # Leniwy import: `app.main` importuje routery, które importują ten
        # pakiet — import na poziomie modułu dałby cykl przy starcie.
        from app.main import app

        headers = {
            "Authorization": self._identity.authorization,
            INTERNAL_HEADER: internal_secret(),
            "Accept": "application/json",
        }
        if self._identity.forwarded_for:
            headers["X-Forwarded-For"] = self._identity.forwarded_for
        if self._identity.operation_id:
            headers["X-Operation-Id"] = self._identity.operation_id
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://jarvis.internal",
            headers=headers,
            timeout=_TIMEOUT_SECONDS,
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def call(self, spec: RequestSpec) -> ToolResponse:
        assert self._client is not None, "JarvisTransport użyty poza `async with`"
        try:
            response = await self._client.request(
                spec.method,
                spec.path,
                params=spec.params or None,
                json=spec.json,
            )
        except httpx.HTTPError as exc:
            logger.warning(
                "jarvis tool transport error %s %s: %s",
                spec.method,
                spec.path,
                type(exc).__name__,
            )
            return ToolResponse(
                status=599, data={"detail": "Nie udało się połączyć z NEXUSEM"}
            )
        try:
            data = response.json()
        except ValueError:
            data = {"detail": response.text[:500]} if response.text else None
        return ToolResponse(status=response.status_code, data=data)
