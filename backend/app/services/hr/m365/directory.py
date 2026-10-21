"""Odczyt konta osoby z katalogu Microsoft 365 (Entra ID) dla kartoteki.

``GET /users/{upn}?$select=…`` tokenem rejestracji „NEXUS Kadry”, a od etapu 2
(D7, 17.10.2026) także ``GET /users/{upn}/manager?$select=userPrincipalName``
— przełożony z katalogu, zapisywany w kartotece tylko jako podpowiedź
rozjazdu w „Ludzie → Struktura” (o przełożonym decydują Kadry). Wymaga
APPLICATION ``User.Read.All`` (zgoda administratora) — to uprawnienie
katalogu, nie Exchange: RBAC for Applications go nie zawęża, aplikacja czyta
stanowiska i telefony całego tenanta (bez poczty i kalendarzy).

Transport jak w ``ops.py`` (``_send``: ten sam klient, ponowienia i kategorie
błędów bez treści odpowiedzi Graph), więc symulacja nie może zbudować innego
żądania niż tryb ``live``:

* ``GraphDirectoryOps`` — prawdziwy Graph,
* ``SimulatedDirectoryOps`` — żądanie zapisane w ``requests``, konto „puste”
  (żadnego pola, więc nic by się nie zmieniło),
* ``tests/test_hr_m365_profile_sync.py::FakeDirectory`` — katalog w pamięci.
"""

from __future__ import annotations

from typing import Any, Optional, Protocol

from app.services.hr.m365.ops import GraphMailboxOps, MailboxError, user_path
from app.services.hr.m365.simulated import SimulatedMailboxOps

#: Pola konta, które czytamy — tylko te, które kartoteka ma (plus stan konta).
USER_SELECT = "jobTitle,department,mobilePhone,businessPhones,accountEnabled"

#: Stan konta po ``id`` (``azure_oid``) — przegląd usuniętych kont
#: (``app/services/m365_account_sweep.py``).
ACCOUNT_SELECT = "id,accountEnabled"

#: Przełożony z katalogu — sam UPN (kolumna ``m365_manager_upn``, 255 znaków).
MANAGER_SELECT = "userPrincipalName"
MANAGER_UPN_LIMIT = 255

#: Kolumna kartoteki → limit długości (jak w ``hr_foundation_schema``).
FIELD_LIMITS: dict[str, int] = {"job_title": 200, "department": 200, "phone": 64}
FIELDS: tuple[str, ...] = tuple(FIELD_LIMITS)


class DirectoryOps(Protocol):
    async def get_user(self, upn: str) -> dict[str, Any]: ...

    async def get_manager(self, upn: str) -> Optional[str]: ...

    async def aclose(self) -> None: ...


class GraphDirectoryOps(GraphMailboxOps):
    """``DirectoryOps`` przez Graph app-only (rejestracja HR)."""

    async def get_user(self, upn: str) -> dict[str, Any]:
        data = await self._send("GET", user_path(upn), params={"$select": USER_SELECT})
        return data if isinstance(data, dict) else {}

    async def get_manager(self, upn: str) -> Optional[str]:
        """UPN przełożonego z katalogu; ``None`` = konto bez przełożonego (404)."""

        try:
            data = await self._send(
                "GET", f"{user_path(upn)}/manager", params={"$select": MANAGER_SELECT}
            )
        except MailboxError as exc:
            if exc.status == 404:
                return None
            raise
        return manager_upn(data)

    async def get_account(self, object_id: str) -> dict[str, Any]:
        """Konto po ``id`` obiektu Entra; usunięte konto = ``MailboxError`` 404."""

        data = await self._send(
            "GET", user_path(object_id), params={"$select": ACCOUNT_SELECT}
        )
        return data if isinstance(data, dict) else {}


class SimulatedDirectoryOps(SimulatedMailboxOps, GraphDirectoryOps):
    """Tryb ``simulate``: żądanie zapisane, odpowiedź bez pól konta."""


def _text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\x00", "").strip()
    return cleaned[:limit] or None


def _phone(data: dict[str, Any]) -> Optional[str]:
    """Komórka służbowa, a bez niej pierwszy numer biurowy (kolejność Compassa).

    Kartoteka z importu ma numery wybrane tą samą regułą — inna kolejność
    przestawiłaby telefony przy pierwszej synchronizacji.
    """

    limit = FIELD_LIMITS["phone"]
    mobile = _text(data.get("mobilePhone"), limit)
    if mobile:
        return mobile
    business = data.get("businessPhones")
    if isinstance(business, list):
        for number in business:
            cleaned = _text(number, limit)
            if cleaned:
                return cleaned
    return None


def profile_values(data: dict[str, Any]) -> dict[str, Optional[str]]:
    """Odpowiedź Graph → pola kartoteki; puste pole w katalogu = ``None``."""

    return {
        "job_title": _text(data.get("jobTitle"), FIELD_LIMITS["job_title"]),
        "department": _text(data.get("department"), FIELD_LIMITS["department"]),
        "phone": _phone(data),
    }


def manager_upn(data: Any) -> Optional[str]:
    """Odpowiedź ``/manager`` → UPN małymi literami (pusty = brak)."""

    value = data.get("userPrincipalName") if isinstance(data, dict) else None
    cleaned = _text(value, MANAGER_UPN_LIMIT)
    return cleaned.lower() if cleaned else None


def account_disabled(data: dict[str, Any]) -> bool:
    return data.get("accountEnabled") is False
