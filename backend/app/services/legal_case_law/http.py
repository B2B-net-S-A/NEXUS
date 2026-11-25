"""Grzeczny klient HTTP źródeł orzecznictwa: limit tempa, timeout, ponowienia.

Każde źródło dostaje własny ``PoliteClient``: najwyżej jedno zapytanie na
``min_interval`` sekund (zapytania czekają w kolejce na zamku), ponowienie
przy błędzie sieci, 429 i 5xx z rosnącą przerwą (``Retry-After`` wygrywa,
o ile nie przekracza ``MAX_RETRY_AFTER``). Awaria źródła nigdy nie wychodzi
wyjątkiem: ``get_json`` zwraca ``None`` i zapisuje powód w logu.

User-Agent nazywa tylko aplikację — bez osób, adresów i nazwy firmy.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

import httpx

logger = logging.getLogger(__name__)

USER_AGENT = "NEXUS-legal-sources/1.0"
TIMEOUT_SECONDS = 20.0
RETRIES = 2
BACKOFF_SECONDS = 2.0
MAX_RETRY_AFTER = 30.0
_RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass
class PoliteClient:
    """Klient jednego źródła; ``client`` podają testy (``httpx.MockTransport``)."""

    name: str
    min_interval: float = 1.0
    timeout: float = TIMEOUT_SECONDS
    retries: int = RETRIES
    client: Optional[httpx.AsyncClient] = None
    requests: int = 0
    errors: int = 0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    _last: float = 0.0
    _owned: bool = False

    async def __aenter__(self) -> "PoliteClient":
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=self.timeout,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            )
            self._owned = True
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if getattr(self, "_owned", False) and self.client is not None:
            await self.client.aclose()
            self.client = None

    async def _wait_turn(self) -> None:
        async with self._lock:
            delay = self._last + self.min_interval - time.monotonic()
            if delay > 0:
                await asyncio.sleep(delay)
            self._last = time.monotonic()

    async def get_json(
        self, url: str, params: Optional[Mapping[str, Any]] = None
    ) -> Optional[dict[str, Any]]:
        """Słownik z odpowiedzi 200 albo ``None`` (404, awaria, zły JSON)."""
        assert self.client is not None, "użyj ``async with PoliteClient(...)``"
        for attempt in range(self.retries + 1):
            await self._wait_turn()
            self.requests += 1
            pause = BACKOFF_SECONDS * (2**attempt)
            try:
                response = await self.client.get(url, params=params)
            except httpx.HTTPError as exc:
                reason = type(exc).__name__
            else:
                if response.status_code == 200:
                    try:
                        data = response.json()
                    except ValueError:
                        data = None
                    if isinstance(data, dict):
                        return data
                    self.errors += 1
                    logger.warning("[orzecznictwo] %s: odpowiedź bez JSON-a", self.name)
                    return None
                if response.status_code not in _RETRY_STATUSES:
                    if response.status_code != 404:
                        self.errors += 1
                        logger.warning(
                            "[orzecznictwo] %s: HTTP %s",
                            self.name,
                            response.status_code,
                        )
                    return None
                reason = f"HTTP {response.status_code}"
                pause = _retry_after(response, pause)
            if attempt < self.retries:
                await asyncio.sleep(pause)
                continue
            self.errors += 1
            logger.warning("[orzecznictwo] %s niedostępny: %s", self.name, reason)
        return None


def _retry_after(response: httpx.Response, default: float) -> float:
    raw = response.headers.get("Retry-After", "")
    try:
        value = float(raw)
    except ValueError:
        return default
    return max(0.0, min(value, MAX_RETRY_AFTER))
