"""Licznik wejść na obszary produktu — poza ścieżką żądania.

Czysty middleware ASGI bez ``await`` na bazie: po skończonej odpowiedzi dolicza
jedynkę w pamięci (``services.access_usage``), a zapis robi pętla co minutę.
Błąd licznika kończy się wpisem w logu, odpowiedź już poszła do klienta.
"""

from __future__ import annotations

import logging

from app.core.config import settings
from app.services.access_usage import area_for_request, record_entry

logger = logging.getLogger(__name__)

_SCREEN_HEADER = b"x-nexus-screen"


def _screen(scope: dict) -> str | None:
    for name, value in scope.get("headers", ()):
        if name == _SCREEN_HEADER:
            return value.decode("latin-1")
    return None


def _count(scope: dict, status_code: int) -> None:
    """Tylko udane odpowiedzi: odmowa 403 to nie jest użycie dostępu."""

    if not 200 <= status_code < 400:
        return
    user_id = (scope.get("state") or {}).get("access_usage_user_id")
    if user_id is None:
        return
    area = area_for_request(_screen(scope), scope.get("path", ""))
    if area is not None:
        record_entry(user_id, area)


class AccessUsageMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not settings.ACCESS_USAGE_COUNTER_ENABLED:
            return await self.app(scope, receive, send)
        status_code = 0

        async def send_with_status(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message["status"]
            await send(message)

        await self.app(scope, receive, send_with_status)
        try:
            _count(scope, status_code)
        except Exception as exc:  # noqa: BLE001 - licznik nie może zepsuć żądania
            logger.warning("access_usage: nie policzono wejścia: %r", exc)
