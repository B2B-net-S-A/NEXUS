"""Kod błędu synchronizacji M365 wyliczany z zapisanego tekstu (UAT B61).

`M365Connection.last_error` to swobodny tekst — bywa `repr` wyjątku Pythona
(`GraphRequestError("Graph 503: 'retry_after cap exceeded (4x)'")`). Karta
w Ustawieniach pokazywała go użytkownikowi wprost. Kod pozwala interfejsowi
powiedzieć po polsku, czy trzeba czekać, połączyć konto ponownie, czy zgłosić
problem; surowy tekst zostaje dla diagnostyki.

Klasyfikacja przy odczycie, bez migracji: działa też dla wpisów zapisanych
przed tą zmianą.
"""

from __future__ import annotations

import re
from typing import Literal, Optional

M365ErrorCode = Literal[
    "graph_throttled",
    "reauth_required",
    "timeout",
    "import_errors",
    "delta_reset",
    "unknown",
]

_THROTTLED = re.compile(r"graph\s+(?:429|502|503|504)\b|retry_after cap", re.IGNORECASE)
_REAUTH = re.compile(
    r"m365reauthrequired|must reconnect|refresh token invalid|token_cipher_unreadable",
    re.IGNORECASE,
)


def classify_m365_error(text: Optional[str]) -> Optional[M365ErrorCode]:
    if not text or not text.strip():
        return None
    if _REAUTH.search(text):
        return "reauth_required"
    if _THROTTLED.search(text):
        return "graph_throttled"
    lowered = text.lower()
    if lowered.startswith("timeout after"):
        return "timeout"
    if "błędów importu" in lowered:
        return "import_errors"
    if "delta cursor" in lowered:
        return "delta_reset"
    return "unknown"
