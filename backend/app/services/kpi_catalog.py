"""KPI Coach v2 — statyczny katalog KPI (plan analytics 2026-07-16, PR 4).

Definicje KPI żyją tu w kodzie jako frozen dataclass. KPI Coach v2 liczy
z KANONICZNYCH danych ATS (Call / view analytics_first_milestones /
candidates.created_by) — NIE z martwego logu `user_activities` (plan §4.1).
Zmiana definicji wymaga deploya — targety (liczby) można zmieniać w DB
przez tabelę `kpi_role_defaults` / `user_kpi_targets`.

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


class KpiPeriod(str, Enum):
    day = "day"
    week = "week"
    month = "month"


class KpiMetric(str, Enum):
    """Kanoniczne źródło licznika (plan §4.2):

    - completed_calls        — Call.status=completed po dacie efektywnej
                               COALESCE(started_at, created_at),
    - first_verifications    — pierwsze `verified` per (kandydat, job)
                               z atrybucją verifier-anchored,
    - new_candidates         — candidates.created_by w oknie,
    - first_recommendations  — pierwsze `cv_sent` (atrybucja j.w.),
    - first_placements       — pierwsze `hired` (atrybucja j.w.).
    """

    completed_calls = "completed_calls"
    first_verifications = "first_verifications"
    new_candidates = "new_candidates"
    first_recommendations = "first_recommendations"
    first_placements = "first_placements"


@dataclass(frozen=True)
class KpiDef:
    """Definicja pojedynczego KPI (niezmienna)."""

    kpi_id: str
    period: KpiPeriod
    title_pl: str
    description_pl: str
    # Kanoniczne źródło licznika (patrz KpiMetric).
    metric: KpiMetric
    # Defaulty per rola jeśli w DB brak rekordu `kpi_role_defaults`.
    # Role spoza dict traktowane jako 0 (KPI niewidoczne).
    default_targets: dict[UserRole, int] = field(default_factory=dict)


# ── Catalog v2 (plan PR 4) ───────────────────────────────────────────────
#
# Zmiany vs v1 (UserActivity):
# - `daily_activity_count` → `daily_completed_calls` (target 15/dzień — plan),
# - NOWE `daily_first_verifications` (target 4/dzień — plan; niezależny od
#   rozmów), `weekly_screenings` usunięte (screening nie ma kanonicznego
#   źródła w ATS),
# - `weekly_cvs_sent` = pierwsze rekomendacje (cv_sent) z atrybucją,
# - `monthly_placements` = pierwsze `hired` z atrybucją.
# Id `daily_new_candidates` / `weekly_cvs_sent` / `monthly_placements`
# zachowane — DB-owe targety (`kpi_role_defaults`, `user_kpi_targets`)
# i warianty wiadomości (`kpi_messages`) nadal pasują.

KPI_CATALOG: tuple[KpiDef, ...] = (
    KpiDef(
        kpi_id="daily_completed_calls",
        period=KpiPeriod.day,
        title_pl="Rozmowy dziś",
        description_pl="Zakończone rozmowy (CloudTalk)",
        metric=KpiMetric.completed_calls,
        default_targets={
            UserRole.recruiter: 15,
            UserRole.tac: 15,
            UserRole.sourcer: 15,
        },
    ),
    KpiDef(
        kpi_id="daily_first_verifications",
        period=KpiPeriod.day,
        title_pl="Weryfikacje dziś",
        description_pl="Kandydaci zweryfikowani (pierwsze przejście na verified)",
        metric=KpiMetric.first_verifications,
        default_targets={
            UserRole.recruiter: 4,
            UserRole.tac: 4,
            UserRole.sourcer: 4,
        },
    ),
    KpiDef(
        kpi_id="daily_new_candidates",
        period=KpiPeriod.day,
        title_pl="Nowi kandydaci dziś",
        description_pl="Liczba nowych kandydatów dodanych w systemie",
        metric=KpiMetric.new_candidates,
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
        description_pl="Pierwsze wysyłki CV do klienta (cv_sent)",
        metric=KpiMetric.first_recommendations,
        default_targets={
            UserRole.recruiter: 15,
            UserRole.tac: 12,
        },
    ),
    KpiDef(
        kpi_id="monthly_placements",
        period=KpiPeriod.month,
        title_pl="Placementy w tym miesiącu",
        description_pl="Zamknięte placementy (pierwsze hired)",
        metric=KpiMetric.first_placements,
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
    return tuple(kpi for kpi in KPI_CATALOG if kpi.default_targets.get(role, 0) > 0)


def all_kpi_ids() -> tuple[str, ...]:
    return tuple(kpi.kpi_id for kpi in KPI_CATALOG)
