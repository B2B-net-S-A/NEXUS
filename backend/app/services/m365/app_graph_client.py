"""Graph app-only (client_credentials) — czytnik skrzynki zamówień.

Ten sam ``GraphClient`` (retry sieciowy, throttling 429/503, twardy timeout,
semafor współbieżności), tylko bez wiersza ``M365Connection``: token pochodzi
z MSAL ``acquire_token_for_client`` tej samej rejestracji, którą użytkownicy
łączą delegowanie. Autorytetem jest zgoda administratora na APPLICATION
``Mail.Read`` **plus Application Access Policy** zawężająca aplikację do
skrzynki zamówień — bez tej polityki uprawnienie aplikacyjne czytałoby każdą
skrzynkę w firmie, więc jej brak jest błędem konfiguracji, nie „szerszym
dostępem".

Dlaczego subklasa, a nie osobny klient: pętla retry/throttle w ``GraphClient``
jest tym, co przez rok chroniło sync skrzynek przed zapętleniem na 429;
kopiowanie jej do drugiej klasy dałoby dwa miejsca, w których to samo
zachowanie się rozjeżdża. Nadpisujemy wyłącznie trzy rzeczy, które zależą od
tożsamości użytkownika: konstruktor (brak tokenów z bazy), bramkę
``_authorize`` (brak właściciela do rewalidacji) i ``_refresh_and_persist``
(odświeżenie = nowy token klienta, nic do zapisania w bazie).
"""

from __future__ import annotations

import logging
from typing import Optional

import httpx
from fastapi.concurrency import run_in_threadpool

from app.services.m365.app_mail import acquire_app_token
from app.services.m365.graph_client import GraphClient

logger = logging.getLogger(__name__)


class AppOnlyTokenUnavailable(RuntimeError):
    """Brak poświadczeń client_credentials albo Entra odmówiło tokenu."""


class AppGraphClient(GraphClient):
    """``GraphClient`` bez użytkownika — ścieżki muszą być ``/users/{upn}/...``."""

    def __init__(self) -> None:  # noqa: D107 — celowo bez super().__init__
        # Klasa bazowa deszyfruje tokeny z wiersza połączenia; tu ich nie ma.
        self._conn = None  # type: ignore[assignment]
        self._db = None  # type: ignore[assignment]
        self._client = httpx.AsyncClient(timeout=30.0, follow_redirects=True)
        self._access_token = ""
        self._refresh_token = ""

    async def __aenter__(self) -> "AppGraphClient":
        try:
            await self._refresh_and_persist()
        except Exception:
            await self.close()
            raise
        return self

    async def _authorize(self) -> None:
        # Brak właściciela do rewalidacji: dostęp aplikacji odbiera się po
        # stronie tenanta (cofnięcie zgody / polityki), nie po naszej.
        return None

    async def _refresh_and_persist(self) -> None:
        # Po 401 MSAL może wciąż trzymać w cache token, który Graph odrzucił —
        # przy ponowieniu wymuszamy nowy. Nic nie zapisujemy: token klienta nie
        # rotuje refresh-tokena.
        force = bool(self._access_token)
        token: Optional[str] = await run_in_threadpool(
            acquire_app_token, force_refresh=force
        )
        if not token:
            raise AppOnlyTokenUnavailable(
                "app-only Graph token unavailable (check M365_CLIENT_ID/SECRET,"
                " M365_MAIL_TENANT_ID and the app's admin consent)"
            )
        self._access_token = token
