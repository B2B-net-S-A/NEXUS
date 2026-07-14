"""KPI Coach — statyczny katalog KPI.

Definicje KPI i ich kanoniczne identyfikatory żyją tu w kodzie jako frozen
dataclass. Liczniki pochodzą z encji ATS w ``kpi_engine``; ``UserActivity``
pozostaje wyłącznie logiem pomocniczym. Targety można zmieniać w DB przez
``kpi_role_defaults`` / ``user_kpi_targets``.

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

from app.models.user import UserRole


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
    # Defaulty per rola jeśli w DB brak rekordu `kpi_role_defaults`.
    # Role spoza dict traktowane jako 0 (KPI niewidoczne).
    default_targets: dict[UserRole, int] = field(default_factory=dict)


# ── Catalog (MVP: 5 KPI) ─────────────────────────────────────────────────

KPI_CATALOG: tuple[KpiDef, ...] = (
    KpiDef(
        kpi_id="daily_activity_count",
        period=KpiPeriod.day,
        title_pl="Zakończone rozmowy dziś",
        description_pl="Power Calling: rozmowy CloudTalk o statusie completed",
        default_targets={
            UserRole.recruiter: 15,
            UserRole.tac: 15,
            UserRole.sourcer: 15,
        },
    ),
    KpiDef(
        kpi_id="daily_new_candidates",
        period=KpiPeriod.day,
        title_pl="Nowi kandydaci dziś",
        description_pl="Liczba nowych kandydatów dodanych w systemie",
        default_targets={
            UserRole.recruiter: 3,
            UserRole.tac: 2,
            UserRole.sourcer: 5,
        },
    ),
    KpiDef(
        kpi_id="weekly_cvs_sent",
        period=KpiPeriod.week,
        title_pl="Rekomendacje w tygodniu",
        description_pl="Pierwsze osiągnięcie etapu cv_sent",
        default_targets={
            UserRole.recruiter: 15,
            UserRole.tac: 12,
        },
    ),
    KpiDef(
        kpi_id="weekly_screenings",
        period=KpiPeriod.day,
        title_pl="Weryfikacje dziś",
        description_pl="Pierwsze osiągnięcie etapu verified",
        default_targets={
            UserRole.recruiter: 4,
            UserRole.tac: 4,
            UserRole.sourcer: 4,
        },
    ),
    KpiDef(
        kpi_id="monthly_placements",
        period=KpiPeriod.month,
        title_pl="Placementy w tym miesiącu",
        description_pl="Zamknięte placementy (hired)",
        default_targets={
            UserRole.recruiter: 1,
            UserRole.tac: 1,
            UserRole.sourcer: 1,
        },
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────

_BY_ID: dict[str, KpiDef] = {kpi.kpi_id: kpi for kpi in KPI_CATALOG}


def get_kpi(kpi_id: str) -> KpiDef | None:
    """Zwraca KpiDef po ID albo None."""
    return _BY_ID.get(kpi_id)


def kpis_for_role(role: UserRole) -> tuple[KpiDef, ...]:
    """Zwraca KPI które mają niezerowy default target dla danej roli.

    Role `admin`, `head_of_recruitment`, `delivery_lead`, `user` nie
    wykonują operacyjnej pracy, więc nie dostają toastów — dla nich ten
    helper zwraca pustą krotkę (chyba że default_targets explicitly
    wymienia tę rolę).
    """
    return tuple(kpi for kpi in KPI_CATALOG if kpi.default_targets.get(role, 0) > 0)


def all_kpi_ids() -> tuple[str, ...]:
    return tuple(kpi.kpi_id for kpi in KPI_CATALOG)
