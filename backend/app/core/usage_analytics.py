"""Klucz PostHog dla sondy przeglądarki (`/api/health/live`).

Klucz projektu PostHog (`phc_…`) służy tylko do wysyłania zdarzeń, więc
przeglądarka i tak go widzi. Wychodzi z API wyłącznie przy włączonej fladze
i w znanym formacie: literówka albo wklejony klucz osobisty (`phx_…`, ten ma
odczyt danych) nie trafia do żadnej karty.
`docs/claude/podstawy/analityka-uzycia-posthog.md`.
"""

import re
from typing import Protocol

_PROJECT_KEY = re.compile(r"phc_[A-Za-z0-9]{20,64}")


class _Settings(Protocol):
    USAGE_ANALYTICS_ENABLED: bool
    POSTHOG_PROJECT_KEY: str


def usage_analytics_key(settings: _Settings) -> str | None:
    key = (settings.POSTHOG_PROJECT_KEY or "").strip()
    if not settings.USAGE_ANALYTICS_ENABLED or not _PROJECT_KEY.fullmatch(key):
        return None
    return key
