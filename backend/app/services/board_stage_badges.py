"""Odznaki Tablicy rekrutacji, które są etapami szablonu (22.09.2026).

Tablica ma 6 kolumn (od 23.09.2026) — to, co nie jest krokiem procesu, jest odznaką na
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
from typing import Any, Optional, Sequence

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


def stage_badge_kind(name: Optional[str]) -> Optional[str]:
    """Rodzaj etapu-odznaki po nazwie — lustro części „badge" `placeStage`.

    `dz` · `cpro` · `contract_signed` · `contract_sent` · `after_interview` ·
    `prep` · `onboarding` albo `None` (zwykły etap). Wspólne przypadki:
    `frontend/src/lib/__fixtures__/board-stage-cases.json`.
    """

    n = normalize_stage_name(name)
    if is_dz_stage(name):
        return "dz"
    if is_cpro_stage(name):
        return "cpro"
    if "umowa podpis" in n:
        return "contract_signed"
    if "umowa wysl" in n:
        return "contract_sent"
    if "po interview" in n or "po rozmowie" in n:
        return "after_interview"
    if "prep" in n or "pre-interview" in n or "przygotowany do spotkania" in n:
        return "prep"
    if "onboarding" in n:
        return "onboarding"
    return None


_IMPORT_SUFFIX = re.compile(r"\s*\(#\d+\)\s*$")


def _base_name(name: Optional[str]) -> str:
    return _IMPORT_SUFFIX.sub("", normalize_stage_name(name))


def foreign_stage_target(
    name: Optional[str], legacy_enum: Optional[str], stage_defs: Sequence[Any]
) -> Optional[Any]:
    """Etap szablonu rekrutacji dla wiersza z INNEGO szablonu (23.09.2026).

    310 z 326 opublikowanych rekrutacji nie ma własnego szablonu (tablica
    rysuje „Default B2B"), a nocny import zapisuje ruchy na etapy szablonu
    Traffita. Samo dopasowanie po kodzie etapu myliło znaczenia: pięć etapów
    Traffita z kodem `interview` („Interview - Prep", „Po Interview"…)
    lądowało na „Przepuszczony przez DZ" (też `interview`) i dostawało odznakę
    „DZ ✓", a „NORDEA: Wysłać do Cpro" (kod `screening`) — w Screeningu.
    Kolejność: ta sama nazwa → ten sam rodzaj odznaki → (po interview: rozmowa
    u klienta) → kod etapu, jak dotąd.
    """

    live = [sd for sd in stage_defs if not getattr(sd, "is_terminal", False)]
    base = _base_name(name)
    if base:
        for sd in stage_defs:
            if _base_name(sd.name) == base:
                return sd
    kind = stage_badge_kind(name)
    if kind is not None:
        for sd in live:
            if stage_badge_kind(sd.name) == kind:
                return sd
        if kind in ("after_interview", "prep"):
            for sd in live:
                if sd.legacy_enum_value == "client_interview":
                    return sd
    if legacy_enum:
        # Ostatni wygrywa — lustro dotychczasowego `enum_to_def`.
        mapped = None
        for sd in stage_defs:
            if sd.legacy_enum_value == legacy_enum:
                mapped = sd
        # Etap-odznaka NIE jest celem dopasowania po kodzie: „Przepuszczony
        # przez DZ" ma kod `interview`, ale znaczy zatwierdzenie DZ.
        # Wiersz bez etapu (`stage_def_id` NULL) zostaje przy starej regule.
        if (
            name is not None
            and mapped is not None
            and stage_badge_kind(mapped.name) in ("dz", "cpro")
        ):
            hosts = [
                sd
                for sd in live
                if sd.legacy_enum_value == legacy_enum
                and stage_badge_kind(sd.name) not in ("dz", "cpro")
            ]
            return hosts[-1] if hosts else None
        return mapped
    return None


# Kolumna Tablicy dla KODU etapu — lustro `BY_ENUM` w `board-stages.ts`.
_COLUMN_BY_ENUM: dict[str, str] = {
    "posting": "new",
    "new": "new",
    "prep_call": "new",
    "screening": "new",
    "verified": "verified",
    "interview": "verified",
    "cv_sent": "cv_sent",
    "client_interview": "client_interview",
    "acceptance": "contract",
    "negotiation": "contract",
    "onboarding": "hired",
    "hired": "hired",
    "rejected": "closed",
    "withdrawn": "closed",
}

# Kolumna dla odznak rozpoznanych po NAZWIE — lustro `placeStage`.
_COLUMN_BY_NAME_BADGE: dict[str, str] = {
    "dz": "verified",
    "cpro": "verified",
    "contract_signed": "contract",
    "contract_sent": "contract",
    "after_interview": "client_interview",
    "prep": "client_interview",
    "onboarding": "hired",
}

# Etapy kolumny „Nowi" (23.09.2026) — tu obowiązuje blokada 12 h.
NEW_COLUMN = "new"


def board_column_for(
    name: Optional[str],
    stage: Optional[str],
    *,
    category: Optional[str] = None,
    terminal_type: Optional[str] = None,
) -> str:
    """Kolumna Tablicy (6 kolumn + „closed") — lustro `placeStage`.

    Czytają ją blokada 12 h (osoba jest w „Nowych”?) i statystyki
    („ile osób jest teraz w kolumnie”). Wspólne przypadki:
    `frontend/src/lib/__fixtures__/board-stage-cases.json`.
    """

    kind = stage_badge_kind(name)
    if kind is not None:
        return _COLUMN_BY_NAME_BADGE[kind]
    if "rezerw" in normalize_stage_name(name):
        return "closed"
    if stage == "hired" or terminal_type == "hired":
        return "hired"
    if category == "terminal":
        return "closed"
    return _COLUMN_BY_ENUM.get(stage or "", "new")


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
