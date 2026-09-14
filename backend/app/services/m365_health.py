"""Sonda `checks.m365` w `/api/health` — połączenia i stan synchronizacji.

UAT M11-B07: sonda liczyła wyłącznie AKTYWNE połączenia (``is_active``), więc
skrzynka, której synchronizacja od tygodni kończyła się błędem, dawała
``m365 = healthy``. Połączenie „jest" nie znaczy, że „działa".

Werdykt jest czystą funkcją (``m365_sync_verdict``) — testowalną bez bazy,
wzorem ``insights_workdays.workdays_sync_verdict``. Sonda pozostaje
informacyjna: nie wpływa na bramkę 503.

Dwa stany, które znaczą „skrzynka nie działa", i dlaczego NIE da się ich
rozpoznać po wieku ``last_sync_at``:

* **Aktywna skrzynka w błędzie.** Każda nieudana próba stempluje
  ``last_sync_at = now()`` (``m365/sync.py``), a pętla ponawia ją co 30 min —
  data nigdy się nie zestarzeje, choćby błąd trwał tygodniami. Status
  ``error`` znaczy „ostatnia próba padła”; chwilowa awaria Graph znika przy
  najbliższym ponowieniu (najpóźniej po 30 min), więc krótki ``degraded`` jest
  ceną za wykrycie awarii trwałej. Bez kolumny „ostatni sukces” (migracja)
  lepszego rozróżnienia nie ma.
* **Połączenie wyłączone przez awarię.** Stany końcowe (nieczytelny token,
  odrzucony refresh token, zbyt wiele resetów kursora delta) ustawiają
  ``is_active=False`` — pętla ich już nie ponawia i sama nic nie naprawi.
  Odłączenie skrzynki przez użytkownika KASUJE wiersz
  (``DELETE /api/microsoft365/connection``), więc nieaktywny wiersz to zawsze
  awaria. Liczy się wyłącznie u AKTYWNYCH pracowników: skrzynka osoby, która
  odeszła, nie jest problemem do rozwiązania, a stały ``degraded`` uczyłby
  ignorować sondę.
"""

from dataclasses import dataclass
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.m365 import M365Connection, M365SyncStatus
from app.models.user import User

_BROKEN_STATUSES = frozenset(
    {M365SyncStatus.error.value, M365SyncStatus.reconnect_required.value}
)


@dataclass(frozen=True)
class M365ConnectionSyncState:
    status: str
    is_active: bool = True


def _status_value(status: object) -> str:
    return status.value if isinstance(status, M365SyncStatus) else str(status)


def m365_sync_verdict(connections: Iterable[M365ConnectionSyncState]) -> str:
    """``healthy`` / ``degraded`` dla skrzynek aktywnych pracowników.

    * brak aktywnego połączenia → ``degraded`` (jak dotychczas);
    * połączenie wyłączone przez awarię → ``degraded``;
    * aktywna skrzynka, której ostatnia próba padła → ``degraded``;
    * w pozostałych przypadkach → ``healthy``.
    """
    states = list(connections)
    if not any(state.is_active for state in states):
        return "degraded"
    for state in states:
        if not state.is_active:
            return "degraded"
        if _status_value(state.status) in _BROKEN_STATUSES:
            return "degraded"
    return "healthy"


async def m365_health_status(session: AsyncSession) -> str:
    """Odczyt stanu skrzynek + werdykt. Skrzynka zamówień (``purpose="orders"``)
    ma własną sondę ``checks.order_mail`` i nie wchodzi tutaj."""
    rows = (
        await session.execute(
            select(M365Connection.last_sync_status, M365Connection.is_active)
            .join(User, User.id == M365Connection.user_id)
            .where(
                M365Connection.purpose == "personal",
                User.is_active.is_(True),
            )
        )
    ).all()
    return m365_sync_verdict(
        M365ConnectionSyncState(status=_status_value(r[0]), is_active=bool(r[1]))
        for r in rows
    )
