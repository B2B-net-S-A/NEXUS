"""Tryb symulacji (``HR_M365_MODE=simulate``): żądania zapisane, nic nie wychodzi.

``SimulatedMailboxOps`` dziedziczy po ``GraphMailboxOps`` i nadpisuje wyłącznie
``_send`` — ścieżki, parametry i ciała buduje ten sam kod co w trybie ``live``.
Wykonawca zapisuje listę ``requests`` w ``hr_m365_operations.simulated_request``,
a karta w Ustawieniach → Kadry pokazuje ją jako podgląd.

Odczyt stanu skrzynki jest symulowany jako pusta skrzynka: autoodpowiedź
wyłączona, brak reguł i wydarzeń. Utworzone obiekty dostają identyfikator
``simulated-…``, którego wykonawca nie zapamiętuje w stanie skrzynki.
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from app.services.hr.m365.ops import GraphMailboxOps


class SimulatedMailboxOps(GraphMailboxOps):
    def __init__(self) -> None:
        super().__init__()
        self.requests: list[dict[str, Any]] = []

    async def aclose(self) -> None:
        return None

    async def _send(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, str]] = None,
        body: Optional[dict[str, Any]] = None,
    ) -> Any:
        entry: dict[str, Any] = {"method": method, "path": path}
        if params:
            entry["params"] = dict(params)
        if body is not None:
            entry["body"] = copy.deepcopy(body)
        self.requests.append(entry)
        number = len(self.requests)
        if method == "GET":
            if path.endswith("/automaticRepliesSetting"):
                return {"status": "disabled", "externalAudience": "none"}
            return {"value": []}
        if method == "POST":
            return {"id": f"simulated-{number}"}
        if method == "PATCH":
            return {}
        return None
