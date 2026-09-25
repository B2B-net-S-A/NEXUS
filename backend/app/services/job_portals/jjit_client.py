"""Klient HTTP Employer Public API (1EP) — JustJoin.IT i RocketJobs (0381).

Jeden host (``PORTAL_JJIT_API_URL``) dla obu portali; portal wybiera
``jobBoard`` w ciele albo ścieżce. Token dostarcza ``token_provider``
(domyślnie ``jjit_connection.access_token`` — własna sesja, zapis od razu),
więc klient da się testować na ``httpx.MockTransport`` bez bazy.

Błędy: RFC 7807. ``title`` to stabilny klucz dostawcy, ``detail`` bywa
zmieniany — do ``last_error`` idzie zdanie po polsku z mapy, a do logu
wyłącznie status, ``title`` i ``traceId`` (bez treści ogłoszenia i tokenów).
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Optional

import httpx

from app.core.config import settings
from app.services.job_portals.jjit_payload import skill_key
from app.services.job_portals.base import (
    PortalError,
    PortalGone,
    PortalReconnectRequired,
)

logger = logging.getLogger(__name__)

TokenProvider = Callable[[bool], Awaitable[str]]

_TITLE_MESSAGES = {
    "job.advertisement.not.found": "Ogłoszenia nie ma już na portalu.",
    "job.advertisement.not.published": (
        "Ogłoszenie na portalu jest już zamknięte — nie da się go edytować."
    ),
    "hiring.company.logo.required": (
        "Portal wymaga logo firmy — dodaj je w profilu pracodawcy na portalu."
    ),
    "subscription.does_not_belong_to_organization_unit": (
        "Subskrypcja nie należy do jednostki, na której publikujemy — sprawdź "
        "saldo w Ustawieniach → Portale ogłoszeniowe."
    ),
}


def portal_error(response: httpx.Response, *, action: str) -> PortalError:
    """Odpowiedź błędu → ``PortalError`` z polskim komunikatem i flagą ponowienia."""
    error = _portal_error(response, action=action)
    error.status = response.status_code
    return error


def _portal_error(response: httpx.Response, *, action: str) -> PortalError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    title = str(body.get("title") or "")
    trace = str(body.get("traceId") or "")
    status = response.status_code
    logger.warning(
        "jjit api %s failed status=%s title=%s trace=%s", action, status, title, trace
    )
    if status == 404:
        return PortalGone(_TITLE_MESSAGES.get(title, "Portal nie zna tego ogłoszenia."))
    if status == 401:
        return PortalReconnectRequired(
            "Portal odrzucił token — połącz konto ponownie w Ustawieniach → "
            "Portale ogłoszeniowe."
        )
    if status == 429 or status >= 500:
        suffix = f" (kod zgłoszenia: {trace})" if trace and status >= 500 else ""
        return PortalError(
            "Portal chwilowo nie odpowiada — spróbujemy ponownie" + suffix + ".",
            retryable=True,
        )
    if title in _TITLE_MESSAGES:
        return PortalError(_TITLE_MESSAGES[title], retryable=False)
    if status == 422 and isinstance(body.get("errors"), list):
        fields = []
        for item in body["errors"][:5]:
            if isinstance(item, dict):
                name = str(item.get("propertyName") or "").strip()
                text = str(item.get("errorMessage") or "").strip()
                fields.append(f"{name}: {text}" if name else text)
        joined = "; ".join(f for f in fields if f)[:600]
        return PortalError(
            "Portal odrzucił ogłoszenie" + (f" — {joined}" if joined else "") + ".",
            retryable=False,
        )
    if status == 403:
        return PortalError(
            "Konto portalu nie ma uprawnień do tej operacji.", retryable=False
        )
    detail = str(body.get("detail") or "").strip()[:300]
    return PortalError(
        f"Portal odmówił ({status})" + (f": {detail}" if detail else "") + ".",
        retryable=False,
    )


class JjitApi:
    def __init__(
        self,
        token_provider: Optional[TokenProvider] = None,
        *,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        base_url: Optional[str] = None,
    ) -> None:
        if token_provider is None:
            from app.services.job_portals import jjit_connection

            token_provider = jjit_connection.access_token
        self._token = token_provider
        self._transport = transport
        self._base_url = (base_url or settings.PORTAL_JJIT_API_URL).rstrip("/")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        action: str,
        json: Any = None,
        params: Optional[dict[str, Any]] = None,
    ) -> httpx.Response:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            transport=self._transport,
            timeout=settings.PORTAL_JJIT_HTTP_TIMEOUT_SECONDS,
        ) as client:
            for attempt in (0, 1):
                token = await self._token(attempt == 1)
                try:
                    response = await client.request(
                        method,
                        path,
                        json=json,
                        params=params,
                        headers={"Authorization": f"Bearer {token}"},
                    )
                except httpx.TimeoutException as exc:
                    raise PortalError(
                        "Portal nie odpowiedział na czas — spróbujemy ponownie.",
                        retryable=True,
                    ) from exc
                except httpx.HTTPError as exc:
                    raise PortalError(
                        "Brak połączenia z portalem — spróbujemy ponownie.",
                        retryable=True,
                    ) from exc
                if response.status_code == 401 and attempt == 0:
                    continue  # jedno odświeżenie tokenu, potem błąd
                if response.status_code >= 400:
                    raise portal_error(response, action=action)
                return response
        raise AssertionError("unreachable")  # pragma: no cover

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    # ── Odczyty ─────────────────────────────────────────────────────────────

    async def me(self) -> dict[str, Any]:
        data = self._json(await self._request("GET", "/employer/oauth/me", action="me"))
        return data if isinstance(data, dict) else {}

    async def dictionaries(self) -> dict[str, Any]:
        data = self._json(
            await self._request("GET", "/employer/dictionaries", action="dictionaries")
        )
        return data if isinstance(data, dict) else {}

    async def balance(self, unit_id: str) -> dict[str, Any]:
        data = self._json(
            await self._request(
                "GET",
                f"/employer/organization-unit/{unit_id}/payments/balance",
                action="balance",
                params={"state": "Active"},
            )
        )
        return data if isinstance(data, dict) else {}

    async def skills(self, board: str, names: list[str]) -> dict[str, dict[str, str]]:
        """``PUT /skills`` (get-or-create) → ``skill_key`` nazwy → ``{id, name}``."""
        if not names:
            return {}
        data = self._json(
            await self._request(
                "PUT",
                f"/employer/{board}/skills",
                action="skills",
                json={"skillNames": names},
            )
        )
        items = data.get("items") if isinstance(data, dict) else data
        out: dict[str, dict[str, str]] = {}
        for item in items or []:
            if isinstance(item, dict) and item.get("id") and item.get("name"):
                skill = {"id": str(item["id"]), "name": str(item["name"])}
                out[skill_key(skill["name"])] = skill
                normalized = skill_key(str(item.get("normalizedName") or ""))
                if normalized:
                    out.setdefault(normalized, skill)
        return out

    # ── Ogłoszenia ──────────────────────────────────────────────────────────

    @staticmethod
    def _ads(unit_id: str) -> str:
        return f"/employer/organization-units/{unit_id}/job-advertisements"

    async def find_published(self, unit_id: str, external_id: str) -> Optional[dict]:
        data = self._json(
            await self._request(
                "GET",
                self._ads(unit_id),
                action="list",
                params={
                    "pageSize": 5,
                    "pageNumber": 1,
                    "state": "Published",
                    "externalId": external_id,
                },
            )
        )
        items = data.get("items") if isinstance(data, dict) else None
        for item in items or []:
            # Filtr po stronie portalu, ale korelację sprawdzamy sami (dokumentacja).
            if isinstance(item, dict) and item.get("externalId") == external_id:
                return item
        return None

    async def create(self, unit_id: str, body: dict[str, Any]) -> dict[str, Any]:
        data = self._json(
            await self._request("POST", self._ads(unit_id), action="create", json=body)
        )
        return data if isinstance(data, dict) else {}

    async def get(self, unit_id: str, ad_id: str) -> dict[str, Any]:
        data = self._json(
            await self._request("GET", f"{self._ads(unit_id)}/{ad_id}", action="get")
        )
        return data if isinstance(data, dict) else {}

    async def update(self, unit_id: str, ad_id: str, body: dict[str, Any]) -> None:
        await self._request(
            "PUT", f"{self._ads(unit_id)}/{ad_id}", action="update", json=body
        )

    async def close(self, unit_id: str, ad_id: str) -> None:
        await self._request("DELETE", f"{self._ads(unit_id)}/{ad_id}", action="close")
