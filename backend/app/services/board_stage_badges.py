"""Odznaki Tablicy rekrutacji, które są etapami szablonu (22.09.2026).

Tablica ma 9 kolumn — to, co nie jest krokiem procesu, jest odznaką na
karcie (`frontend/src/lib/board-stages.ts`). Dwie z nich niosą regułę
„kto może", więc serwer sprawdza ją przy ruchu na ich etap:

* „Przepuszczony przez DZ" (odznaka „DZ ✓") — ustawia admin, każdy Delivery
  Lead i Head of Recruitment (decyzja Artura: „każdy DL i Dominik"; Dominik
  ma rolę Head of Recruitment).
* „Wysłać do Cpro" (odznaka „Gotowy do Cpro") — wyłącznie u Nordei. Klienta
  rozpoznaje ta sama konfiguracja, co politykę zamówień Nordei
  (`NORDEA_ORDER_NUMBER_CLIENT_IDS`), więc nie ma drugiej listy do utrzymania.

Nocny import z Traffita zapisuje ruchy bez tego API — odznaka z importu
pokazuje się zawsze. Reguła nazw ma lustro we froncie; oba czytają
`frontend/src/lib/__fixtures__/board-stage-cases.json`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Optional

from fastapi import HTTPException

from app.models.user import User, UserRole
from app.services.order_policies.registry import is_client_in_policy

DZ_BADGE_ROLES: tuple[UserRole, ...] = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)

_DZ_RE = re.compile(r"\bdz\b")
_CPRO_RE = re.compile(r"\bcpro\b")


def normalize_stage_name(name: Optional[str]) -> str:
    """Małe litery, bez polskich znaków — lustro `normalizeStageName`."""

    folded = (name or "").lower().replace("ł", "l")
    folded = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).strip()


def is_dz_stage(name: Optional[str]) -> bool:
    n = normalize_stage_name(name)
    return bool(_DZ_RE.search(n)) or "przepuszcz" in n


def is_cpro_stage(name: Optional[str]) -> bool:
    return bool(_CPRO_RE.search(normalize_stage_name(name)))


def cpro_enabled_for_client(client_id: Optional[int]) -> bool:
    """„Gotowy do Cpro" istnieje tylko u Nordei."""

    return is_client_in_policy("nordea", client_id)


def ensure_badge_stage_allowed(
    user: User, *, stage_name: Optional[str], client_id: Optional[int]
) -> None:
    """Odmawia ruchu na etap-odznakę, jeśli rola albo klient się nie zgadza."""

    if is_dz_stage(stage_name) and not user.has_any_role(*DZ_BADGE_ROLES):
        raise HTTPException(
            status_code=403,
            detail=(
                "„Zweryfikowany przez DZ” może oznaczyć Delivery Lead "
                "albo Head of Recruitment."
            ),
        )
    if is_cpro_stage(stage_name) and not cpro_enabled_for_client(client_id):
        raise HTTPException(
            status_code=422,
            detail="„Gotowy do Cpro” dotyczy wyłącznie rekrutacji dla Nordei.",
        )
