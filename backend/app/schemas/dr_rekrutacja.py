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
