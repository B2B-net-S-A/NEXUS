"""Jeden katalog KPI rekrutacji — definicje i domyślne cele (22.09.2026).

Do 22.09.2026 w repo żyły DWA systemy KPI z własnymi identyfikatorami
i własnymi liczbami: widget KPI Coach (ten plik) i panel „Moje KPI"
(`kpi_panel.PANEL_KPI_DEFAULTS`, seed 0124). Ta sama osoba dostawała dwa różne
cele placementów (widget 2/3/1, panel 1/1/1) i odwrotny kierunek celu nowych
kandydatów. Teraz katalog jest JEDYNYM źródłem definicji i domyślnych liczb:
panel, widget, nudge'e, wyścig miesięczny, panel zespołu i raport Power
Calling czytają cele przez `app.services.kpi_targets`.

Identyfikatory panelu (`verifications_daily`, `placements_monthly`,
`precision_monthly`) są ALIASAMI — migracja 0346 przepisała na kanoniczne id
wiersze `kpi_role_defaults` / `user_kpi_targets`, a `get_kpi` i resolver
targetów nadal rozumieją stare id (zapisane gdzieś w historii albo wołane
przez starszy kod).

Liczby (decyzje Artura 22.09.2026, od 0411 jedna rola „rekruter”): placementy /
miesiąc = 1; weryfikacje / dzień = 4; precision = 75%; rekomendacje / tydzień
= 15. Wiersz w `kpi_role_defaults` albo `user_kpi_targets` NADPISUJE domyślną
liczbę z katalogu (precedencja w `kpi_targets`); zapisuje je edytor
Ustawienia → Rekrutacja → Cele KPI (`kpi_target_editor`).

Cel „Nowi kandydaci dziś” (`daily_new_candidates`, 5 dziennie) wycofany
13.10.2026 decyzją Artura — patrz `WITHDRAWN_KPI_TITLES`. Sama liczba „CV do
bazy” zostaje jako statystyka bez celu (`kpi_team`, `kpi_panel`).

Dodawanie nowego KPI:
  1) Dopisz `KpiDef(...)` do `KPI_CATALOG`.
  2) Dopisz warianty wiadomości w `kpi_messages.py` (praise_hit, remind_behind),
     jeśli KPI jest widoczne w KPI Coach (`in_coach=True`).

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
    - first_recommendations  — pierwsze `cv_sent` (atrybucja j.w.),
    - first_placements       — pierwsze `hired` (atrybucja j.w.),
    - precision              — rekomendacje ÷ weryfikacje w oknie kroczącym
                               30 dni (w procentach). Nie jest licznikiem
                               narastającym w okresie, więc nie trafia do
                               KPI Coach (`in_coach=False`).
    """

    completed_calls = "completed_calls"
    first_verifications = "first_verifications"
    first_recommendations = "first_recommendations"
    first_placements = "first_placements"
    precision = "precision"


@dataclass(frozen=True)
class KpiDef:
    """Definicja pojedynczego KPI (niezmienna)."""

    kpi_id: str
    period: KpiPeriod
    title_pl: str
    # Nazwa bez okresu — podpis segmentu w liczniku górnego paska, gdzie okres
    # stoi obok liczby („Weryfikacje · 2 / 4 dziś”).
    short_title_pl: str
    # Jedno zdanie „co się liczy” dla człowieka: pokazują je panel celów
    # w górnym pasku i edytor celów.
    description_pl: str
    # Kanoniczne źródło licznika (patrz KpiMetric).
    metric: KpiMetric
    # Domyślne cele per rola, gdy w DB brak wiersza. Role spoza słownika = 0
    # (KPI nie dotyczy tej roli). Wiele ról → obowiązuje MAKSIMUM
    # (`kpi_targets.resolve_kpi_target`).
    default_targets: dict[UserRole, int] = field(default_factory=dict)
    # Stare identyfikatory tego samego KPI (panel „Moje KPI" sprzed 22.09).
    aliases: tuple[str, ...] = ()
    # Czy KPI pokazuje widget KPI Coach i czy wysyła nudge'e.
    in_coach: bool = True
    # Metryka wymaga telefonii (CloudTalk). Przy `CLOUDTALK_ENABLED=false`
    # KPI nie istnieje — nie ma „0/15", nie ma nudge'a.
    requires_cloudtalk: bool = False


_OPERATORS = (UserRole.recruiter,)


def _same_for_operators(value: int) -> dict[UserRole, int]:
    return {role: value for role in _OPERATORS}


KPI_CATALOG: tuple[KpiDef, ...] = (
    KpiDef(
        kpi_id="daily_completed_calls",
        period=KpiPeriod.day,
        title_pl="Rozmowy dziś",
        short_title_pl="Rozmowy",
        description_pl="Liczą się zakończone rozmowy telefoniczne.",
        metric=KpiMetric.completed_calls,
        default_targets=_same_for_operators(15),
        requires_cloudtalk=True,
    ),
    KpiDef(
        kpi_id="daily_first_verifications",
        period=KpiPeriod.day,
        title_pl="Weryfikacje dziś",
        short_title_pl="Weryfikacje",
        description_pl="Liczy się pierwsze przejście kandydata na „Zweryfikowany”.",
        metric=KpiMetric.first_verifications,
        default_targets=_same_for_operators(4),
        aliases=("verifications_daily",),
    ),
    KpiDef(
        kpi_id="weekly_cvs_sent",
        period=KpiPeriod.week,
        title_pl="Rekomendacje w tygodniu",
        short_title_pl="Rekomendacje",
        description_pl="Liczy się pierwsza wysyłka CV kandydata do klienta.",
        metric=KpiMetric.first_recommendations,
        default_targets=_same_for_operators(15),
    ),
    KpiDef(
        kpi_id="monthly_placements",
        period=KpiPeriod.month,
        title_pl="Placementy w tym miesiącu",
        short_title_pl="Placementy",
        description_pl="Liczy się pierwsze zatrudnienie kandydata.",
        metric=KpiMetric.first_placements,
        default_targets=_same_for_operators(1),
        aliases=("placements_monthly",),
    ),
    KpiDef(
        kpi_id="monthly_precision",
        period=KpiPeriod.month,
        title_pl="Precyzja (30 dni)",
        short_title_pl="Precyzja",
        description_pl="Rekomendacje podzielone przez weryfikacje z ostatnich 30 dni.",
        metric=KpiMetric.precision,
        default_targets=_same_for_operators(75),
        aliases=("precision_monthly",),
        in_coach=False,
    ),
)


# ── Helpers ──────────────────────────────────────────────────────────────

_BY_ID: dict[str, KpiDef] = {kpi.kpi_id: kpi for kpi in KPI_CATALOG}

# Stary id → kanoniczny id.
KPI_ID_ALIASES: dict[str, str] = {
    alias: kpi.kpi_id for kpi in KPI_CATALOG for alias in kpi.aliases
}

# Identyfikatory zasiane przez 0034 i od dawna martwe (UserActivity).
# Migracja 0346 kasuje ich wiersze z `kpi_role_defaults`.
RETIRED_KPI_IDS: tuple[str, ...] = ("daily_activity_count", "weekly_screenings")

# Cele wycofane po 0346 (id → tytuł sprzed wycofania). Wiersze tych id zostają
# w `kpi_role_defaults` / `user_kpi_targets` — resolver (`kpi_targets`) ich nie
# czyta, bo pyta bazę tylko o id z katalogu; historia edytora celów bierze stąd
# tytuł, żeby stary wpis nie pokazywał surowego id. Osobna lista, bo
# `RETIRED_KPI_IDS` jest przypięta do zamrożonych stałych migracji 0346.
WITHDRAWN_KPI_TITLES: dict[str, str] = {
    # 13.10.2026, decyzja Artura: nie ma już celu dodawania kandydatów do bazy.
    "daily_new_candidates": "Nowi kandydaci dziś",
}


def canonical_kpi_id(kpi_id: str) -> str:
    """Kanoniczny id dla id kanonicznego albo aliasu (nieznany → bez zmian)."""
    return KPI_ID_ALIASES.get(kpi_id, kpi_id)


def get_kpi(kpi_id: str) -> Optional[KpiDef]:
    """Zwraca KpiDef po ID (także po starym id z panelu) albo None."""
    return _BY_ID.get(canonical_kpi_id(kpi_id))


def kpis_for_role(role: UserRole) -> tuple[KpiDef, ...]:
    """KPI z niezerowym domyślnym celem dla danej roli.

    Role `admin`, `head_of_recruitment`, `delivery_lead`, `finance`,
    `talent_community_manager` nie mają osobistych celów rekrutacyjnych —
    liderzy mają cele zespołu/portfela (`kpi_goals`).
    """
    return tuple(kpi for kpi in KPI_CATALOG if kpi.default_targets.get(role, 0) > 0)


def all_kpi_ids() -> tuple[str, ...]:
    return tuple(kpi.kpi_id for kpi in KPI_CATALOG)


def kpi_available(kpi: KpiDef) -> bool:
    """Czy KPI ma dziś źródło danych (telefonia dla rozmów)."""
    if not kpi.requires_cloudtalk:
        return True
    # Import leniwy: katalog jest liściem grafu importów (czytają go migracyjne
    # testy kontraktowe bez pełnej konfiguracji aplikacji).
    from app.core.config import settings

    return bool(settings.CLOUDTALK_ENABLED)
