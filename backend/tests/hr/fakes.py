"""Atrapy dla testów „Ludzi w NEXUSIE” (bez sieci).

``FakeMailboxOps`` — skrzynki Microsoft 365 w pamięci, zgodne z protokołem
``app.services.hr.m365.ops.MailboxOps``. Zachowuje się jak Graph tam, gdzie
to ma znaczenie dla reguł:

* autoodpowiedź zapisana w strefie Warszawy wraca w UTC (tak odpowiada
  Graph) — test okna przy zmianie czasu sprawdza prawdziwe przeliczenie,
* drugi POST wydarzenia z tym samym ``transactionId`` → 409,
* usunięcie nieistniejącego obiektu → 404,
* ``fail(metoda, status)`` wstrzykuje błąd (np. 403) na kolejne wywołania.

Dane fikcyjne — repo jest publiczne.
"""

from __future__ import annotations

import copy
import itertools
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from app.services.hr.m365 import oof_state
from app.services.hr.m365.ops import MailboxError


def _to_utc(value: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    moment = oof_state.instant(value)
    if moment is None:
        return value
    utc = moment.astimezone(timezone.utc).replace(tzinfo=None)
    return {"dateTime": utc.isoformat() + ".0000000", "timeZone": "UTC"}


class FakeMailboxOps:
    def __init__(self, *, echo_utc: bool = True) -> None:
        self.echo_utc = echo_utc
        self.auto_replies: dict[str, dict[str, Any]] = {}
        self.events: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.rules: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self.calls: list[tuple[str, str]] = []
        self.writes: list[tuple[str, str, Any]] = []
        self._ids = itertools.count(1)
        self._failures: dict[str, list[MailboxError]] = defaultdict(list)
        self._always: dict[str, MailboxError] = {}
        self.closed = False

    # ── Sterowanie testem ────────────────────────────────────────────────────
    def fail(
        self, method: str, status: int, *, times: int = 1, code: Optional[str] = None
    ) -> None:
        self._failures[method].extend(MailboxError(status, code) for _ in range(times))

    def fail_always(
        self, method: str, status: Optional[int], *, category: Optional[str] = None
    ) -> None:
        self._always[method] = MailboxError(status, category=category)

    def set_oof(self, upn: str, setting: dict[str, Any]) -> None:
        self.auto_replies[upn.lower()] = copy.deepcopy(setting)

    def add_rule(self, upn: str, display_name: str) -> str:
        rule_id = f"rule-{next(self._ids)}"
        self.rules[upn.lower()][rule_id] = {"id": rule_id, "displayName": display_name}
        return rule_id

    def add_event(
        self, upn: str, transaction_id: str, start: datetime, end: datetime
    ) -> str:
        event_id = f"event-{next(self._ids)}"
        self.events[upn.lower()][event_id] = {
            "id": event_id,
            "transactionId": transaction_id,
            "_start": start,
            "_end": end,
        }
        return event_id

    def _enter(self, method: str, upn: str) -> None:
        self.calls.append((method, upn.lower()))
        if method in self._always:
            raise self._always[method]
        queue = self._failures.get(method)
        if queue:
            raise queue.pop(0)

    # ── MailboxOps ───────────────────────────────────────────────────────────
    async def aclose(self) -> None:
        self.closed = True

    async def get_auto_replies(self, upn: str) -> dict[str, Any]:
        self._enter("get_auto_replies", upn)
        setting = copy.deepcopy(
            self.auto_replies.get(upn.lower()) or {"status": "disabled"}
        )
        if self.echo_utc:
            for key in ("scheduledStartDateTime", "scheduledEndDateTime"):
                if setting.get(key):
                    setting[key] = _to_utc(setting[key])
        return setting

    async def set_auto_replies(self, upn: str, setting: dict[str, Any]) -> None:
        self._enter("set_auto_replies", upn)
        self.writes.append(("set_auto_replies", upn.lower(), copy.deepcopy(setting)))
        if setting.get("status") == "disabled":
            current = self.auto_replies.get(upn.lower()) or {}
            self.auto_replies[upn.lower()] = {**current, "status": "disabled"}
        else:
            self.auto_replies[upn.lower()] = copy.deepcopy(setting)

    async def create_event(self, upn: str, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("create_event", upn)
        mailbox = self.events[upn.lower()]
        transaction = body.get("transactionId")
        if transaction and any(
            e.get("transactionId") == transaction for e in mailbox.values()
        ):
            raise MailboxError(409)
        event_id = f"event-{next(self._ids)}"
        start = oof_state.instant(body.get("start"))
        end = oof_state.instant(body.get("end"))
        mailbox[event_id] = {
            **copy.deepcopy(body),
            "id": event_id,
            "_start": start,
            "_end": end,
        }
        self.writes.append(("create_event", upn.lower(), copy.deepcopy(body)))
        return {"id": event_id}

    async def update_event(
        self, upn: str, event_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        self._enter("update_event", upn)
        mailbox = self.events[upn.lower()]
        if event_id not in mailbox:
            raise MailboxError(404)
        mailbox[event_id].update(copy.deepcopy(body))
        mailbox[event_id]["_start"] = oof_state.instant(body.get("start"))
        mailbox[event_id]["_end"] = oof_state.instant(body.get("end"))
        self.writes.append(("update_event", upn.lower(), copy.deepcopy(body)))
        return {"id": event_id}

    async def delete_event(self, upn: str, event_id: str) -> None:
        self._enter("delete_event", upn)
        mailbox = self.events[upn.lower()]
        if event_id not in mailbox:
            raise MailboxError(404)
        del mailbox[event_id]
        self.writes.append(("delete_event", upn.lower(), event_id))

    async def find_events(
        self, upn: str, start: datetime, end: datetime
    ) -> list[dict[str, Any]]:
        self._enter("find_events", upn)
        found = []
        for event in self.events[upn.lower()].values():
            event_start, event_end = event.get("_start"), event.get("_end")
            if event_start is None or event_end is None:
                continue
            if event_start < end and event_end > start:
                found.append(
                    {
                        key: value
                        for key, value in event.items()
                        if not key.startswith("_")
                    }
                )
        return found

    async def list_rules(self, upn: str) -> list[dict[str, Any]]:
        self._enter("list_rules", upn)
        return [copy.deepcopy(rule) for rule in self.rules[upn.lower()].values()]

    async def create_rule(self, upn: str, body: dict[str, Any]) -> dict[str, Any]:
        self._enter("create_rule", upn)
        rule_id = f"rule-{next(self._ids)}"
        self.rules[upn.lower()][rule_id] = {**copy.deepcopy(body), "id": rule_id}
        self.writes.append(("create_rule", upn.lower(), copy.deepcopy(body)))
        return {"id": rule_id}

    async def update_rule(
        self, upn: str, rule_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        self._enter("update_rule", upn)
        mailbox = self.rules[upn.lower()]
        if rule_id not in mailbox:
            raise MailboxError(404)
        mailbox[rule_id].update(copy.deepcopy(body))
        self.writes.append(("update_rule", upn.lower(), copy.deepcopy(body)))
        return {"id": rule_id}

    async def delete_rule(self, upn: str, rule_id: str) -> None:
        self._enter("delete_rule", upn)
        mailbox = self.rules[upn.lower()]
        if rule_id not in mailbox:
            raise MailboxError(404)
        del mailbox[rule_id]
        self.writes.append(("delete_rule", upn.lower(), rule_id))
