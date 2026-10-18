"""Reguła przekierowania poczty do zastępcy (czysty moduł).

Reguła skrzynki odbiorczej Outlooka nie ma warunków czasowych — żyje, dopóki
ktoś jej nie usunie. Dlatego:

* nazwa niesie id urlopu (``NEXUS · zastępstwo · {uuid}``), żeby sprzątanie
  sierot znalazło regułę bez tabeli powiązań; rozpoznajemy też nazwy Compassa
  (``COMPASS · zastępstwo · {uuid}``) — urlopy z importu mają te same UUID,
* okno = sam urlop: otwarcie pierwszego dnia (nigdy wcześniej — poczta nie
  płynie do zastępcy, kiedy osoba jeszcze pracuje), zamknięcie po ostatnim,
* ``forwardTo`` (kopia, nie przeniesienie) i ``stopProcessingRules: false`` —
  własne reguły osoby działają dalej.

Filtr jak w Compassie: poczta zaadresowana do osoby, bez współpracowników
(domeny firmy z ``SSO_ALLOWED_DOMAINS`` — nie wpisane na sztywno), bez
noreply, powiadomień Microsoft/Teams/SharePoint, list mailingowych,
autoodpowiedzi, zaproszeń i NDR. Wyjątki dla autoodpowiedzi i przekierowań
przerywają pętlę dwóch osób na urlopie, które się nawzajem zastępują.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from typing import Any, Literal, Optional

from app.services.hr.leave_m365 import forward_rule_name

# U+00B7 (kropka środkowa) — tak samo jak w Compassie.
NEXUS_RULE_PREFIX = "NEXUS · zastępstwo · "
COMPASS_RULE_PREFIX = "COMPASS · zastępstwo · "
_PREFIXES = (NEXUS_RULE_PREFIX, COMPASS_RULE_PREFIX)
_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)

_ALWAYS_EXCLUDED = (
    "no-reply",
    "noreply",
    "donotreply",
    "do-not-reply",
    "teams.mail.microsoft",
    "sharepointonline.com",
    "microsoft.com",
    "mailer-daemon",
    "postmaster",
)

WindowState = Literal["before", "open", "after"]


def rule_name(leave_id: str) -> str:
    return forward_rule_name(leave_id)


def parse_leave_id(display_name: Optional[str]) -> Optional[str]:
    """Id urlopu z nazwy reguły NEXUSA albo Compassa; cudza reguła → ``None``."""

    if not isinstance(display_name, str):
        return None
    for prefix in _PREFIXES:
        if display_name.startswith(prefix):
            candidate = display_name[len(prefix) :].strip()
            return candidate.lower() if _UUID.match(candidate) else None
    return None


def is_compass_rule(display_name: Optional[str]) -> bool:
    return isinstance(display_name, str) and display_name.startswith(
        COMPASS_RULE_PREFIX
    )


def excluded_senders(company_domains: Iterable[str]) -> list[str]:
    domains = [
        f"@{d.strip().lower().lstrip('@')}" for d in company_domains if d.strip()
    ]
    return [*domains, *_ALWAYS_EXCLUDED]


def filters(company_domains: Iterable[str]) -> dict[str, Any]:
    return {
        "conditions": {"sentToOrCcMe": True},
        "exceptions": {
            "senderContains": excluded_senders(company_domains),
            "headerContains": ["List-Unsubscribe"],
            "isAutomaticReply": True,
            "isAutomaticForward": True,
            "isMeetingRequest": True,
            "isMeetingResponse": True,
            "isReadReceipt": True,
            "isNonDeliveryReport": True,
        },
    }


def rule_body(
    *,
    leave_id: str,
    substitute_email: str,
    substitute_name: Optional[str],
    company_domains: Iterable[str],
) -> dict[str, Any]:
    """Pełne ciało reguły — to samo przy tworzeniu i przy przejęciu reguły Compassa."""

    return {
        "displayName": rule_name(leave_id),
        "sequence": 1,
        "isEnabled": True,
        "actions": {
            "forwardTo": [
                {
                    "emailAddress": {
                        "name": substitute_name or substitute_email,
                        "address": substitute_email,
                    }
                }
            ],
            "stopProcessingRules": False,
        },
        **filters(company_domains),
    }


def window_state(start: date, end: date, today: date) -> WindowState:
    """Okno przekierowania: od pierwszego do ostatniego dnia urlopu włącznie."""

    if today < start:
        return "before"
    if today > end:
        return "after"
    return "open"
