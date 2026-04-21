"""KPI Coach — statyczny katalog KPI.

Definicje KPI (co liczymy, z jakich akcji, per jaka rola default) żyją tu
w kodzie jako frozen dataclass. To świadoma decyzja: KPI to kontrakt z
enumem `UserActionType`, a nie dane. Zmiana definicji wymaga deploya —
targety (liczby) można zmieniać w DB przez tabelę `kpi_role_defaults` /
`user_kpi_targets`.

Dodawanie nowego KPI:
  1) Dopisz `KpiDef(...)` do `KPI_CATALOG`.
  2) Dodaj rekord do `kpi_role_defaults` (np. przez data migration lub
     seed w `alembic/versions/0033_kpi_coach.py` dla MVP).
  3) Dopisz warianty wiadomości w `kpi_messages.py` (wszystkie 4 nudge
     typy: praise_hit, remind_behind, eod_summary, streak_bonus).

Tone: komunikaty koleżeńskie po polsku (feedback Artura).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from app.models.user import UserRole
from app.models.user_activity import UserActionType


class KpiPeriod(str, Enum):
    day = "day"
    week = "week"
    month = "month"


@dataclass(frozen=True)
class KpiDef:
    """Definicja pojedynczego KPI (niezmienna)."""

    kpi_id: str
    period: KpiPeriod
    title_pl: str
    description_pl: str
    # Jakie akcje z user_activities wchodzą do licznika.
    action_types: tuple[UserActionType, ...]
    # Defaulty per rola jeśli w DB brak rekordu `kpi_role_defaults`.
    # Role spoza dict traktowane jako 0 (KPI niewidoczne).
    default_targets: dict[UserRole, int] = field(default_factory=dict)
    # Opcjonalny filtr po `user_activities.details` (JSONB). Np. dla
    # `stage_changed → cv_sent`: {"stage": "cv_sent"}.
    details_filter: Optional[dict] = None


# ── Catalog (MVP: 5 KPI) ─────────────────────────────────────────────────

KPI_CATALOG: tuple[KpiDef, ...] = (
    KpiDef(
        kpi_id="daily_activity_count",
        period=KpiPeriod.day,
        title_pl="Aktywności dziś",
        description_pl="Rozmowy + screeningi łącznie",
        action_types=(
            UserActionType.call_made,
            UserActionType.screening_done,
        ),
        default_targets={
            UserRole.recruiter: 10,
            UserRole.tac: 12,
            UserRole.sourcer: 8,
        },
    ),
    KpiDef(
        kpi_id="daily_new_candidates",
        period=KpiPeriod.day,
        title_pl="Nowi kandydaci dziś",
        description_pl="Liczba nowych kandydatów dodanych w systemie",
        action_types=(UserActionType.candidate_added,),
        default_targets={
            UserRole.recruiter: 3,
            UserRole.tac: 2,
            UserRole.sourcer: 5,
        },
    ),
    KpiDef(
        kpi_id="weekly_cvs_sent",
        period=KpiPeriod.week,
        title_pl="CV wysłane w tygodniu",
        description_pl="Wgrania CV + przejścia na etap cv_sent",
        action_types=(
            UserActionType.cv_uploaded,
            UserActionType.stage_changed,
        ),
        details_filter={"stage": "cv_sent"},
        default_targets={
            UserRole.recruiter: 15,
            UserRole.tac: 12,
        },
    ),
    KpiDef(
        kpi_id="weekly_screenings",
        period=KpiPeriod.week,
        title_pl="Screeningi w tygodniu",
        description_pl="Rozmowy screeningowe przeprowadzone",
        action_types=(UserActionType.screening_done,),
        default_targets={
            UserRole.recruiter: 5,
            UserRole.tac: 7,
            UserRole.sourcer: 3,
        },
    ),
    KpiDef(
        kpi_id="monthly_placements",
        period=KpiPeriod.month,
        title_pl="Placementy w tym miesiącu",
        description_pl="Zamknięte placementy (hired)",
        action_types=(UserActionType.placement_closed,),
        default_targets={
            UserRole.recruiter: 2,
            UserRole.tac: 3,
            UserRole.sourcer: 1,
        },
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────

_BY_ID: dict[str, KpiDef] = {kpi.kpi_id: kpi for kpi in KPI_CATALOG}


def get_kpi(kpi_id: str) -> Optional[KpiDef]:
    """Zwraca KpiDef po ID albo None."""
    return _BY_ID.get(kpi_id)


def kpis_for_role(role: UserRole) -> tuple[KpiDef, ...]:
    """Zwraca KPI które mają niezerowy default target dla danej roli.

    Role `admin`, `head_of_recruitment`, `delivery_lead`, `user` nie
    wykonują operacyjnej pracy, więc nie dostają toastów — dla nich ten
    helper zwraca pustą krotkę (chyba że default_targets explicitly
    wymienia tę rolę).
    """
    return tuple(
        kpi for kpi in KPI_CATALOG if kpi.default_targets.get(role, 0) > 0
    )


def all_kpi_ids() -> tuple[str, ...]:
    return tuple(kpi.kpi_id for kpi in KPI_CATALOG)
