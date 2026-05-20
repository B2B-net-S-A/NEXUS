"""Pydantic schemas dla DynaReporter Rekrutacja mega-dashboard.

Port `client/src/pages/Rekrutacja.tsx` + `server/src/routes/competitions.ts` z
artur-t-96/InfraReporter. Endpointy zwracają agregaty team-wide.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field


class UserMetricValue(BaseModel):
    """Wartość KPI + target + procent realizacji."""

    model_config = ConfigDict(from_attributes=True)

    value: int = Field(description="Realna wartość zsumowana w okresie")
    target: int = Field(description="Cel (obliczany z roli + dni roboczych)")
    percentage: int = Field(description="Procent realizacji (0-100+, może >100)")


class UserMetrics(BaseModel):
    """Komplet KPI dla jednej osoby w wybranym okresie."""

    model_config = ConfigDict(from_attributes=True)

    verifications: UserMetricValue
    recommendations: UserMetricValue
    interviews: UserMetricValue
    placements: UserMetricValue
    quality_score: UserMetricValue = Field(
        description="Interviews/Recommendations × 100 (jakość rekomendacji)"
    )


class TeamMember(BaseModel):
    """Pojedynczy rekruter w widoku Performance per osoba."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    first_name: str
    last_name: str
    role: str
    is_active: bool
    metrics: UserMetrics
    league_points: int = Field(
        description="Punkty Ligi Mistrzów (placement×150 + interview×15 + recommendation×5)"
    )
    is_qualified: bool = Field(
        default=True,
        description="Czy spełnia warunek udziału w Lidze Mistrzów (min 1 placement/mc).",
    )


class TeamSummary(BaseModel):
    """Suma team-wide KPI w wybranym okresie."""

    model_config = ConfigDict(from_attributes=True)

    total_verifications: int
    total_recommendations: int
    total_interviews: int
    total_placements: int
    average_quality_score: int = Field(
        description="Średnia Interviews/Recommendations × 100"
    )


class FunnelStage(BaseModel):
    """Konwersja w lejku rekrutacyjnym."""

    model_config = ConfigDict(from_attributes=True)

    label: str = Field(description="Pełna nazwa (np. 'Weryfikacje → Rekomendacje')")
    short_label: str = Field(description="Skrót (np. 'Wer → Rek')")
    percentage: float = Field(description="Procent konwersji 0-100")
    numerator: int
    denominator: int


class QuarterlyEntryRequirement(BaseModel):
    """Warunek udziału w Lidze Mistrzów na bieżący moment kwartału."""

    model_config = ConfigDict(from_attributes=True)

    min_placements: int = Field(description="Wymagane placement do dziś (1/2/3)")
    total_required: int = Field(default=3, description="Wymagane łącznie w kwartale")
    month_in_quarter: int = Field(description="1/2/3 — który miesiąc kwartału")
    description: str = Field(description="Czytelny opis dla użytkownika")


class RekrutacjaDashboard(BaseModel):
    """Pełny payload `GET /api/dynareporter/rekrutacja/dashboard`."""

    model_config = ConfigDict(from_attributes=True)

    period: str = Field(description="'week' | 'month' | 'year'")
    period_label: str = Field(
        description="Człowiecznie czytelny label (np. 'Maj 2026')"
    )
    period_start: date
    period_end: date

    team_summary: TeamSummary
    funnel: list[FunnelStage]
    users: list[TeamMember]
    league_ranking: list[TeamMember] = Field(
        description="Te same osoby co users, ale sortowane po league_points DESC, "
        "z wyłączeniem ról nielicznych (delivery_lead)"
    )
    league_ranking_quarterly: list[TeamMember] = Field(
        default_factory=list,
        description="Ranking dla bieżącego kwartału — Liga Mistrzów agreguje punkty "
        "kwartalnie, niezależnie od filtru `period`.",
    )
    quarter_label: str = Field(
        default="",
        description="Czytelny label kwartału (np. 'Q2 2026') dla Liga Mistrzów.",
    )
    quarter_start: date | None = Field(default=None)
    quarter_end: date | None = Field(default=None)
    # Nowe pola — DR full parity (countdown, progress, completion state)
    quarter_days_remaining: int = Field(
        default=0,
        description="Dni do końca kwartału (0 jeśli zakończony).",
    )
    quarter_progress: int = Field(
        default=0,
        description="Procent kwartału ukończony (0-100).",
    )
    quarter_is_completed: bool = Field(
        default=False,
        description="Czy kwartał już się skończył (end_date < today).",
    )
    quarter_entry_requirement: QuarterlyEntryRequirement | None = Field(
        default=None,
        description="Warunek udziału w Lidze Mistrzów na bieżący moment.",
    )

    scoring: dict[str, int] = Field(
        description="System punktowy z dr_system_config "
        "(placement/interview/recommendation/verification/prize_1/2/3)"
    )


class AvailableWeek(BaseModel):
    """Pojedynczy tydzień z dostępnymi danymi KPI."""

    model_config = ConfigDict(from_attributes=True)

    week_number: int
    year: int
    label: str = Field(description="Czytelny label (np. 'Tydzień 26/2026')")
    has_data: bool = Field(description="Czy są wpisy KPI w tym tygodniu")


# === Sub-sections (follow-up port) ===========================================


class HallOfFameEntry(BaseModel):
    """Historic zwycięzca z dr_competition_winners."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(description="Internal PK z dr_competition_winners.id")
    competition_type: str = Field(
        description="'quarterly' | 'monthly_recommendations' | 'monthly_placements'"
    )
    period: str = Field(description="Q1 2026 / 2026-04 / etc.")
    rank: int = Field(description="1, 2 lub 3")
    user_id: int
    user_name: str
    points: int = 0
    metric_value: int = 0
    prize: str | None = None


class YearlyStatsRow(BaseModel):
    """Tygodniowy agregat KPI dla wykresu Statystyki Roczne."""

    model_config = ConfigDict(from_attributes=True)

    week_label: str = Field(description="np. 'T26 2026'")
    week_number: int
    year: int
    verifications: int = 0
    recommendations: int = 0
    interviews: int = 0
    placements: int = 0


class MonthlyRaceEntry(BaseModel):
    """Wiersz Wyścigu Rekomendacji / Placementów (miesięczne competitions).

    Full DR shape: per-row badges weryfikacji/dzień + precision rate + qualification flags.
    """

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    role: str
    metric_value: int = Field(
        description="recommendations OR placements w miesiącu (primary metric)"
    )
    per_day: float = Field(description="metric / days roboczych (avg)")
    # === Pola dodatkowe (DR parity) ===========================================
    verifications: int = Field(
        default=0,
        description="Sumaryczne weryfikacje w miesiącu (dla recommendations race).",
    )
    days_worked: int = Field(default=0, description="Dni roboczych w miesiącu.")
    verifications_per_day: float = Field(
        default=0.0,
        description="Weryfikacje/dzień roboczy — kryterium kwalifikacji dla rekomendacji.",
    )
    precision_rate: int = Field(
        default=0,
        description="recommendations / verifications × 100 (0-100). Dla recommendations race.",
    )
    meets_verification_requirement: bool = Field(
        default=True,
        description="Czy verifications_per_day >= 4 (target dla recommendations).",
    )
    meets_precision_requirement: bool = Field(
        default=True,
        description="Czy precision_rate >= 75% (od 2026-04 dla recommendations).",
    )
    is_qualified: bool = Field(
        default=True,
        description="Dla placements: metric_value >= min_qualification (2). "
        "Dla recommendations: meets_verification_requirement AND meets_precision_requirement.",
    )
    is_excluded: bool = Field(
        default=False,
        description="Czy zwycięzca kwartalny wykluczony z nagrody miesięcznej "
        "(tylko ostatni miesiąc kwartału).",
    )


class MonthlyRace(BaseModel):
    """Pełen Wyścig z meta-data.

    Full DR shape: period info + days_remaining + requirements + tie_breaker.
    """

    model_config = ConfigDict(from_attributes=True)

    competition_type: str = Field(description="'recommendations' | 'placements'")
    month: str = Field(description="YYYY-MM (legacy)")
    voucher: str = "Voucher 1 500 PLN (Modivo, Douglas, Media Markt)"
    requirement: str
    entries: list[MonthlyRaceEntry]
    # === Pola dodatkowe (DR parity) ===========================================
    period: str = Field(default="", description="YYYY-MM")
    month_name: str = Field(default="", description="Polska nazwa miesiąca")
    year: int = Field(default=0)
    days_remaining: int = Field(default=0)
    is_completed: bool = Field(default=False, description="Miesiąc zakończony.")
    min_qualification: int | None = Field(
        default=None,
        description="Minimalna liczba placementów do kwalifikacji (dla placements race).",
    )
    verification_requirement: int | None = Field(
        default=None,
        description="Wymóg weryfikacji/dzień (dla recommendations race).",
    )
    precision_rate_requirement: int | None = Field(
        default=None,
        description="Wymóg precision rate % (od 2026-04 dla recommendations).",
    )
    is_precision_rate_active: bool = Field(default=False)
    tie_breaker: str = Field(default="Wyższa sumaryczna marża")
    is_last_month_of_quarter: bool = Field(default=False)
    excluded_user_id: int | None = Field(default=None)
    current_leader_id: int | None = Field(default=None)
    prize: str = Field(
        default="Voucher 1 500 PLN (Modivo, Douglas, Media Markt)",
        description="Display prize string (mirror DR `prize`).",
    )


class PlacementByPerson(BaseModel):
    """Placement count per osoba (Analiza Placementów — wg osób)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    role: str
    count: int


class PlacementByClient(BaseModel):
    """Placement count per klient (Analiza Placementów — wg klientów)."""

    model_config = ConfigDict(from_attributes=True)

    client_id: int
    client_name: str
    count: int


class PlacementAnalysis(BaseModel):
    """Analiza Placementów — breakdown wg osób + wg klientów dla okresu."""

    model_config = ConfigDict(from_attributes=True)

    by_person: list[PlacementByPerson] = Field(default_factory=list)
    by_client: list[PlacementByClient] = Field(default_factory=list)
    total: int = 0


class TeamPanelSourcer(BaseModel):
    """Sourcer w kategorii kompetencji z priority."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    name: str
    priority: int


class TeamPanelCategory(BaseModel):
    """Kategoria kompetencji z sourcerami 1st/2nd priority (Zespół Rekrutacji)."""

    model_config = ConfigDict(from_attributes=True)

    category_id: int
    category_name: str
    first_priority: list[TeamPanelSourcer] = Field(default_factory=list)
    second_priority: list[TeamPanelSourcer] = Field(default_factory=list)


class TeamPanelTacDl(BaseModel):
    """DL → przypisane TAC (Zespół Rekrutacji — TAC-DL)."""

    model_config = ConfigDict(from_attributes=True)

    dl_user_id: int
    dl_name: str
    tac_names: list[str] = Field(default_factory=list)


class TeamPanel(BaseModel):
    """Zespół Rekrutacji - Przypisania (read-only display dla dashboardu)."""

    model_config = ConfigDict(from_attributes=True)

    sourcer_categories: list[TeamPanelCategory] = Field(default_factory=list)
    tac_dl: list[TeamPanelTacDl] = Field(default_factory=list)


class PowerCallingEntry(BaseModel):
    """Wiersz Power Calling — dzienna efektywność weryfikacji."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    role: str
    verifications: int
    days_worked: int
    per_day: float = Field(description="verifications / days_worked")
    week_label: str


class LinkedInPerformanceRow(BaseModel):
    """Per-TAC LinkedIn farming stats."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    role: str
    cv_added: int = 0
    messages_sent: int = 0
    responses_received: int = 0
    response_rate: float = Field(description="responses_received / messages_sent × 100")
    cv_per_md: float = Field(description="avg CV/MD (target 5)")


class AccelerationPathEntry(BaseModel):
    """Wiersz Acceleration Path (Junior→Senior lub Senior→Expert)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    role: str
    start_date: str = Field(description="acceleration_start_date lub senior_since")
    months_elapsed: int = Field(description="Liczba miesięcy od startu")
    placements_6m: int = Field(description="Placements w ostatnich 6mc")
    placements_12m: int = Field(description="Placements w ostatnich 12mc")
    threshold_6m: int = Field(description="Próg 6m (6 dla J→S, 12 dla S→E)")
    threshold_12m: int = Field(description="Próg 12m (12 dla J→S, 24 dla S→E)")
    status: str = Field(description="'Awans od ...' | 'Na ścieżce' | 'Poniżej tempa'")
    next_promotion_date: str | None = Field(
        default=None, description="Data awansu YYYY-MM-DD jeśli osiągnięty próg"
    )


class AccelerationPath(BaseModel):
    """Pełen Acceleration Path — 2 listy."""

    model_config = ConfigDict(from_attributes=True)

    junior_to_senior: list[AccelerationPathEntry] = Field(default_factory=list)
    senior_to_expert: list[AccelerationPathEntry] = Field(default_factory=list)
    junior_count: int = 0
    senior_count: int = 0
    expert_count: int = 0
    ready_for_promotion: int = Field(
        default=0, description="Łączna liczba osób gotowych do awansu"
    )
