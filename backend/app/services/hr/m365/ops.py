"""Operacje na skrzynce osoby w Microsoft 365 — protokół i implementacja Graph.

``MailboxOps`` opisuje wszystko, czego potrzebują wykonawca kolejki
i uzgadnianie: autoodpowiedź (``mailboxSettings``), wydarzenia w kalendarzu
i reguły skrzynki odbiorczej. Implementacje:

* ``GraphMailboxOps`` — prawdziwy Graph (``AppGraphClient`` z tokenem
  rejestracji HR, ścieżki ``/users/{upn}/…``),
* ``SimulatedMailboxOps`` (``simulated.py``) — te same ścieżki i ciała, ale
  zamiast sieci zapis żądania,
* ``tests/hr/fakes.py::FakeMailboxOps`` — skrzynka w pamięci dla testów.

Każde żądanie przechodzi przez ``GraphMailboxOps._send`` — symulacja nadpisuje
tylko tę metodę, więc nie może zbudować innego żądania niż tryb ``live``.

Błędy wychodzą jako ``MailboxError`` z KATEGORIĄ (``forbidden``,
``throttled``…), bez treści odpowiedzi Graph — ta potrafi nieść adres skrzynki
i nazwiska, a kategoria trafia do ``last_error`` widocznego w Ustawieniach.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

#: Kategorie, które ponawiamy z odroczeniem (uprawnienia Exchange bywają
#: nadawane z opóźnieniem, więc 403 też czeka, zamiast od razu przepaść).
RETRYABLE_CATEGORIES = frozenset(
    {"forbidden", "throttled", "server_error", "timeout", "network", "auth"}
)

#: Konto bez skrzynki Exchange (licencja bez poczty, skrzynka nieaktywna).
_NO_MAILBOX_CODES = frozenset({"MailboxNotEnabledForRESTAPI", "ErrorMailboxNotFound"})


def categorize(status: Optional[int], code: Optional[str] = None) -> str:
    """Status HTTP (albo jego brak) → kategoria błędu bez danych osobowych."""

    if status is None:
        return "network"
    if status == 401:
        return "auth"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "no_mailbox" if code in _NO_MAILBOX_CODES else "not_found"
    if status == 409:
        return "conflict"
    if status == 429:
        return "throttled"
    if status == 599:
        return "timeout"
    if status >= 500:
        return "server_error"
    if status == 400:
        return "bad_request"
    return "rejected"


class MailboxError(Exception):
    """Odmowa albo awaria Graph; ``category`` trafia do ``last_error``."""

    def __init__(
        self,
        status: Optional[int],
        code: Optional[str] = None,
        *,
        category: Optional[str] = None,
    ) -> None:
        self.status = status
        self.code = code
        self.category = category or categorize(status, code)
        super().__init__(self.label)

    @property
    def retryable(self) -> bool:
        return self.category in RETRYABLE_CATEGORIES

    @property
    def label(self) -> str:
        return f"{self.category} ({self.status})" if self.status else self.category


def user_path(upn: str) -> str:
    return f"/users/{quote(upn, safe='@.')}"


def _segment(value: str) -> str:
    return quote(value, safe="")


def graph_instant(moment: datetime) -> str:
    """Chwila w UTC w formacie, który przyjmuje ``calendarView``."""

    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MailboxOps(Protocol):
    async def get_auto_replies(self, upn: str) -> dict[str, Any]: ...

    async def set_auto_replies(self, upn: str, setting: dict[str, Any]) -> None: ...

    async def create_event(self, upn: str, body: dict[str, Any]) -> dict[str, Any]: ...

    async def update_event(
        self, upn: str, event_id: str, body: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def delete_event(self, upn: str, event_id: str) -> None: ...

    async def find_events(
        self, upn: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]: ...

    async def list_rules(self, upn: str) -> list[dict[str, Any]]: ...

    async def create_rule(self, upn: str, body: dict[str, Any]) -> dict[str, Any]: ...

    async def update_rule(
        self, upn: str, rule_id: str, body: dict[str, Any]
    ) -> dict[str, Any]: ...

    async def delete_rule(self, upn: str, rule_id: str) -> None: ...

    async def aclose(self) -> None: ...


class GraphMailboxOps:
    """``MailboxOps`` przez Graph app-only (rejestracja HR, ``auth.py``)."""

    def __init__(self) -> None:
        self._client: Any = None

    async def _graph(self) -> Any:
        if self._client is None:
            from app.services.hr.m365.auth import acquire_hr_token
            from app.services.m365.app_graph_client import AppGraphClient

            client = AppGraphClient(token_provider=acquire_hr_token)
            await client.__aenter__()
            self._client = client
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, str]] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> Any:
        from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
        from app.services.m365.graph_client import GraphRequestError

        try:
            client = await self._graph()
            if method == "GET":
                return await client.get(path, params=params)
            if method == "PATCH":
                return await client.patch(path, json=body)
            if method == "POST":
                return await client.post(path, json=body)
            if method == "DELETE":
                return await client.delete(path)
        except GraphRequestError as exc:
            code = None
            if isinstance(exc.body, dict):
                error = exc.body.get("error")
                if isinstance(error, dict):
                    code = error.get("code")
            raise MailboxError(exc.status, code) from None
        except AppOnlyTokenUnavailable:
            raise MailboxError(None, category="auth") from None
        except httpx.HTTPError:
            raise MailboxError(None, category="network") from None
        raise ValueError(method)

    # ── Autoodpowiedź ─────────────────────────────────────────────────────────
    async def get_auto_replies(self, upn: str) -> dict[str, Any]:
        data = await self._send(
            "GET", f"{user_path(upn)}/mailboxSettings/automaticRepliesSetting"
        )
        return data if isinstance(data, dict) else {}

    async def set_auto_replies(self, upn: str, setting: dict[str, Any]) -> None:
        await self._send(
            "PATCH",
            f"{user_path(upn)}/mailboxSettings",
            body={"automaticRepliesSetting": setting},
        )

    # ── Kalendarz ─────────────────────────────────────────────────────────────
    async def create_event(self, upn: str, body: dict[str, Any]) -> dict[str, Any]:
        data = await self._send("POST", f"{user_path(upn)}/events", body=body)
        return data if isinstance(data, dict) else {}

    async def update_event(
        self, upn: str, event_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        data = await self._send(
            "PATCH", f"{user_path(upn)}/events/{_segment(event_id)}", body=body
        )
        return data if isinstance(data, dict) else {}

    async def delete_event(self, upn: str, event_id: str) -> None:
        await self._send("DELETE", f"{user_path(upn)}/events/{_segment(event_id)}")

    async def find_events(
        self, upn: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        data = await self._send(
            "GET",
            f"{user_path(upn)}/calendarView",
            params={
                "startDateTime": graph_instant(start),
                "endDateTime": graph_instant(end),
                "$select": "id,transactionId,subject,categories",
                "$top": "100",
            },
        )
        value = data.get("value") if isinstance(data, dict) else None
        return [item for item in value or [] if isinstance(item, dict)]

    # ── Reguły skrzynki odbiorczej ────────────────────────────────────────────
    async def list_rules(self, upn: str) -> list[dict[str, Any]]:
        data = await self._send(
            "GET", f"{user_path(upn)}/mailFolders/inbox/messageRules"
        )
        value = data.get("value") if isinstance(data, dict) else None
        return [item for item in value or [] if isinstance(item, dict)]

    async def create_rule(self, upn: str, body: dict[str, Any]) -> dict[str, Any]:
        data = await self._send(
            "POST", f"{user_path(upn)}/mailFolders/inbox/messageRules", body=body
        )
        return data if isinstance(data, dict) else {}

    async def update_rule(
        self, upn: str, rule_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        data = await self._send(
            "PATCH",
            f"{user_path(upn)}/mailFolders/inbox/messageRules/{_segment(rule_id)}",
            body=body,
        )
        return data if isinstance(data, dict) else {}

    async def delete_rule(self, upn: str, rule_id: str) -> None:
        await self._send(
            "DELETE",
            f"{user_path(upn)}/mailFolders/inbox/messageRules/{_segment(rule_id)}",
        )
