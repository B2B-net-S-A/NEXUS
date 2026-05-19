"""Pydantic schemas dla DynaReporter Rekrutacja mega-dashboard.

PR `port/dr-rekrutacja-megadashboard` (2026-05-19) — port `/rekrutacja` z
oryginalnego DR (artur-t-96/InfraReporter, `client/src/pages/Rekrutacja.tsx`).

Endpointy zwracają agregaty team-wide (NIE per-user filter), bo dashboard
służy widokowi managerskiemu — admin/DL/HoR widzi wszystkich, sourcer/tac/
recruiter widzą siebie + zespół do porównania (Liga Mistrzów).
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
        description="Ranking dla bieżącego kwartału (Q1/Q2/Q3/Q4) — Liga Mistrzów "
        "agreguje punkty kwartalnie, niezależnie od filtru `period`. "
        "DR pokazuje Q-level podium w sekcji 'Liga Mistrzów' (3 miesiące).",
    )
    quarter_label: str = Field(
        default="",
        description="Czytelny label kwartału (np. 'Q2 2026') dla sekcji Liga Mistrzów.",
    )
    quarter_start: date | None = Field(
        default=None,
        description="Początek kwartału (YYYY-MM-01)",
    )
    quarter_end: date | None = Field(
        default=None,
        description="Ostatni dzień kwartału (YYYY-MM-DD, ostatni dzień miesiąca)",
    )
    scoring: dict[str, int] = Field(
        description="System punktowy z dr_system_config (placement/interview/recommendation)"
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
    """Wiersz Wyścigu Rekomendacji / Placementów (miesięczne competitions)."""

    model_config = ConfigDict(from_attributes=True)

    user_id: int
    user_name: str
    role: str
    metric_value: int = Field(description="recommendations OR placements w miesiącu")
    per_day: float = Field(description="metric / days roboczych (avg)")


class MonthlyRace(BaseModel):
    """Pełen Wyścig z meta-data."""

    model_config = ConfigDict(from_attributes=True)

    competition_type: str = Field(description="'recommendations' | 'placements'")
    month: str = Field(description="YYYY-MM")
    voucher: str = "Voucher 1 500 PLN (Modivo, Douglas, Media Markt)"
    requirement: str
    entries: list[MonthlyRaceEntry]


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
