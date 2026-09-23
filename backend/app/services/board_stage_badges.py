"""Etapy szablonu a kolumny Tablicy rekrutacji (8 kolumn od 24.09.2026).

Tablica ma 8 kolumn — Nowi · Screening · Zweryfikowany · QC CV · CV wysłane ·
Rozmowa u klienta · Umowa · Zatrudniony (makiety
https://claude.ai/artifact/CG4mBk9xcHZAn3y9jcmMeW). To, co nie jest krokiem
procesu, jest znacznikiem na karcie (`frontend/src/lib/board-stages.ts`).

* „QC CV" (dawniej „Przepuszczony przez DZ") — gospodarz kolumny QC CV.
  Do 23.09.2026 ustawiał go wyłącznie DL/HoR („DZ ✓"); od 24.09 przesuwa na
  niego każdy, kto może ruszać kartą — kontrolą jest QC CV liczone przez kod
  (`services/cv_qc.py`), a nie rola osoby klikającej.
* „Wysłać do Cpro" (znacznik „w kolejce Cpro") — kolumna QC CV, wyłącznie
  u Nordei. Klienta rozpoznaje ta sama konfiguracja, co politykę zamówień
  Nordei (`NORDEA_ORDER_NUMBER_CLIENT_IDS`), więc nie ma drugiej listy.

Nocny import z Traffita zapisuje ruchy bez tego API — etap z importu
pokazuje się zawsze. Reguła nazw ma lustro we froncie; oba czytają
`frontend/src/lib/__fixtures__/board-stage-cases.json`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Optional, Sequence

from fastapi import HTTPException

from app.models.user import User
from app.services.order_policies.registry import is_client_in_policy

# „DZ" (dawna nazwa) i „QC" (od 24.09.2026) — całe słowa, żeby „qc" nie
# łapało się w środku innej nazwy.
_QC_RE = re.compile(r"\b(dz|qc)\b")
_CPRO_RE = re.compile(r"\bcpro\b")


def normalize_stage_name(name: Optional[str]) -> str:
    """Małe litery, bez polskich znaków — lustro `normalizeStageName`."""

    folded = (name or "").lower().replace("ł", "l")
    folded = unicodedata.normalize("NFKD", folded)
    return "".join(ch for ch in folded if not unicodedata.combining(ch)).strip()


def is_qc_stage(name: Optional[str]) -> bool:
    """Etap „QC CV" albo dawny „Przepuszczony przez DZ" — gospodarz kolumny QC CV.

    Szablon z Traffita nadal niesie starą nazwę (nocny sync by ją przepisał),
    więc obie nazwy znaczą to samo.
    """

    n = normalize_stage_name(name)
    return bool(_QC_RE.search(n)) or "przepuszcz" in n


# Dawna nazwa — zostaje dla wołających sprzed 24.09.2026.
is_dz_stage = is_qc_stage


def is_cpro_stage(name: Optional[str]) -> bool:
    return bool(_CPRO_RE.search(normalize_stage_name(name)))


def stage_badge_kind(name: Optional[str]) -> Optional[str]:
    """Rodzaj etapu-odznaki po nazwie — lustro części „badge" `placeStage`.

    `qc` · `cpro` · `contract_signed` · `contract_sent` · `after_interview` ·
    `prep` · `onboarding` albo `None` (zwykły etap). Wspólne przypadki:
    `frontend/src/lib/__fixtures__/board-stage-cases.json`.
    """

    n = normalize_stage_name(name)
    if is_qc_stage(name):
        return "qc"
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


# Rodzaje etapów rozpoznawane wyłącznie po nazwie — nigdy celem dopasowania
# obcego etapu po samym kodzie.
_NAME_ONLY_KINDS = ("qc", "cpro")

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
    u klienta) → kod etapu, jak dotąd. Od 24.09.2026 szablon „Default B2B"
    nazywa ten etap „QC CV", a Traffit dalej „Przepuszczony przez DZ" — obie
    nazwy mają rodzaj `qc`, więc trafiają na ten sam etap.
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
        # Etap rozpoznawany po NAZWIE nie jest celem dopasowania po kodzie:
        # „QC CV" (dawniej „Przepuszczony przez DZ") ma kod `interview`, ale
        # znaczy kontrolę CV — obca „Rozmowa techniczna" z tym samym kodem
        # nie może na nim wylądować. Wiersz bez etapu (`stage_def_id` NULL)
        # zostaje przy starej regule.
        if (
            name is not None
            and mapped is not None
            and stage_badge_kind(mapped.name) in _NAME_ONLY_KINDS
        ):
            hosts = [
                sd
                for sd in live
                if sd.legacy_enum_value == legacy_enum
                and stage_badge_kind(sd.name) not in _NAME_ONLY_KINDS
            ]
            return hosts[-1] if hosts else None
        return mapped
    return None


# Kolumna Tablicy dla KODU etapu — lustro `BY_ENUM` w `board-stages.ts`.
_COLUMN_BY_ENUM: dict[str, str] = {
    "posting": "new",
    "new": "new",
    "prep_call": "screening",
    "screening": "screening",
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
    "qc": "cv_qc",
    "cpro": "cv_qc",
    "contract_signed": "contract",
    "contract_sent": "contract",
    "after_interview": "client_interview",
    "prep": "client_interview",
    "onboarding": "hired",
}

# Kolejność kolumn Tablicy (bez paska zamkniętych) — lustro
# `BOARD_COLUMN_ORDER` we froncie. Czytają ją wymagania przejścia
# (`services/move_requirements.py`: które kolumny ruch pomija).
BOARD_COLUMN_ORDER: tuple[str, ...] = (
    "new",
    "screening",
    "verified",
    "cv_qc",
    "cv_sent",
    "client_interview",
    "contract",
    "hired",
)

NEW_COLUMN = "new"
SCREENING_COLUMN = "screening"
CV_QC_COLUMN = "cv_qc"
# Kolumny, w których obowiązuje blokada 12 h i „rozmowa w Nowych" (od
# 24.09.2026 także Screening — to on jest dziś miejscem pierwszej rozmowy).
CLAIM_COLUMNS: frozenset[str] = frozenset({NEW_COLUMN, SCREENING_COLUMN})


def board_column_for(
    name: Optional[str],
    stage: Optional[str],
    *,
    category: Optional[str] = None,
    terminal_type: Optional[str] = None,
) -> str:
    """Kolumna Tablicy (8 kolumn + „closed") — lustro `placeStage`.

    Czytają ją blokada 12 h (osoba jest w „Nowych”/„Screeningu”?),
    wymagania przejścia i statystyki
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
    """Kolejka Cpro istnieje tylko u Nordei."""

    return is_client_in_policy("nordea", client_id)


def ensure_badge_stage_allowed(
    user: User, *, stage_name: Optional[str], client_id: Optional[int]
) -> None:
    """Odmawia ruchu na etap Cpro rekrutacji spoza Nordei.

    Etap QC CV nie ma już reguły roli (24.09.2026): przesuwa na niego każdy,
    kto może ruszać kartą. `user` zostaje w sygnaturze — wołający go podają,
    a reguła roli może wrócić bez zmiany wywołań.
    """

    del user
    if is_cpro_stage(stage_name) and not cpro_enabled_for_client(client_id):
        raise HTTPException(
            status_code=422,
            detail="Kolejka Cpro dotyczy wyłącznie rekrutacji dla Nordei.",
        )
