"""Nazwa firmy w postaci kanonicznej i „pracuje tam teraz” z wpisu CV.

Wydzielone z ``api/integrations_companies.py`` (21.10.2026), żeby off-limits
(``services/client_off_limits.py``) dopasowywał firmy tą samą regułą co
API dla ATLAS-a, bez importu trasy (ta ciągnie ``api.candidates``).
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Ported verbatim from ATLAS `src/services/company_service.py` so both sides
# agree byte-for-byte on what "the same company" means. Any change here MUST be
# mirrored there, otherwise matches silently diverge between the two systems.
_SUFFIXES = [
    " sp. z o.o.",
    " sp.z o.o.",
    " sp z oo",
    " sp. z o. o.",
    " spolka z o.o.",
    " sp. j.",
    " sp.j.",
    " s.a.",
    " sa",
    " s.k.",
    " sp k",
    " sp. k.",
    " s.c.",
    " s. c.",
    " sp. komandytowa",
    " spółka z ograniczoną odpowiedzialnością",
    " spolka z ograniczona odpowiedzialnoscia",
    " inc",
    " inc.",
    " ltd",
    " ltd.",
    " gmbh",
]


def normalize_company_name(name: str) -> str:
    """Canonical form used for cross-system company matching.

    Keep in lockstep with ATLAS ``src/services/company_service.py``.
    """
    if not name:
        return ""
    s = name.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("ł", "l")
    for suf in _SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)].rstrip()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    s = re.sub(r"\s+", " ", s)
    return s


def entry_says_current(entry: dict[str, Any]) -> bool:
    """Open-ended entry that carries evidence, not just a missing date.

    Called only for entries where ``is_current_end(end)`` already holds. A
    ``start`` date means the CV listed a period that has not closed; a word
    like "present"/"obecnie" in ``end`` says it outright. A blank ``end`` with
    no ``start`` says nothing.
    """
    start = entry.get("start")
    if isinstance(start, str) and start.strip():
        return True
    end = entry.get("end")
    return isinstance(end, str) and bool(end.strip())
