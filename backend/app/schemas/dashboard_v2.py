"""Typed contracts for the canonical role dashboards.

The dashboard API deliberately exposes narrow, role-specific models instead of
one ``dict[str, Any]`` payload.  Two containment properties are structural:

* Delivery Lead schemas contain no money, rate, invoice or margin fields.
* Finance schemas contain no candidate/person fields.

Every section can independently report incomplete data.  An unavailable source
must therefore never be serialized as a numeric zero.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


class DashboardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


DashboardQualityStatus = Literal["complete", "partial", "stale", "unavailable"]
DashboardScopeKind = Literal[
    "organization",
    "recruitment_org",
    "delivery_clients",
    "self",
]
DashboardSeverity = Literal["info", "warning", "critical"]
DashboardKpiValue = Union[str, int, float, None]


class DashboardClientTacPairPayload(DashboardModel):
    client_id: int
    tac_user_id: int


class DashboardScopePayload(DashboardModel):
    kind: DashboardScopeKind
    user_id: int | None = None
    client_ids: list[int] = Field(default_factory=list)
    tac_user_ids: list[int] = Field(default_factory=list)
    operator_user_ids: list[int] = Field(default_factory=list)
    client_tac_pairs: list[DashboardClientTacPairPayload] = Field(default_factory=list)


class DashboardSectionQuality(DashboardModel):
    status: DashboardQualityStatus
    warnings: list[str] = Field(default_factory=list)
    source_watermarks: dict[str, datetime] = Field(default_factory=dict)


class DashboardDataQuality(DashboardModel):
    status: DashboardQualityStatus
    warnings: list[str] = Field(default_factory=list)
    source_watermarks: dict[str, datetime] = Field(default_factory=dict)
    sections: dict[str, DashboardSectionQuality] = Field(default_factory=dict)


class DashboardKpi(DashboardModel):
    value: DashboardKpiValue = None
    unit: Literal["count", "percent", "hours", "PLN", "fraction", "status"]
    quality: DashboardQualityStatus = "complete"
    target: DashboardKpiValue = None
    comparison: DashboardKpiValue = None
    definition: str
    drilldown_href: str | None = None


class DashboardAlert(DashboardModel):
    id: str
    kind: str
    severity: DashboardSeverity
    title: str
    description: str | None = None
    source: str
    occurred_at: datetime | None = None
    due_at: datetime | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    href: str | None = None


class DashboardQueueItem(DashboardModel):
    id: str
    kind: str
    priority: int = Field(ge=0, le=100)
    title: str
    subtitle: str | None = None
    source: str
    due_at: datetime | None = None
    entity_type: str | None = None
    entity_id: int | None = None
    href: str | None = None
    action_label: str | None = None
    version: int | None = None


class DashboardResponseBase(DashboardModel):
    schema_version: Literal["2"] = "2"
    generated_at: datetime
    scope: DashboardScopePayload
    data_quality: DashboardDataQuality


# ── Admin Ops ────────────────────────────────────────────────────────────────


class AdminOpsKpis(DashboardModel):
    critical_readiness: DashboardKpi
    critical_schema_drift: DashboardKpi
    background_workers: DashboardKpi
    failed_dead_events: DashboardKpi
    integrations_in_sla: DashboardKpi
    lowest_critical_coverage: DashboardKpi


class AdminOpsBoardRow(DashboardModel):
    id: str
    severity: DashboardSeverity
    domain: str
    signal: str
    last_success_at: datetime | None = None
    owner: str | None = None
    next_action_href: str | None = None


class AdminOpsDashboardData(DashboardModel):
    kpis: AdminOpsKpis
    alerts: list[DashboardAlert] = Field(default_factory=list)
    queue: list[DashboardQueueItem] = Field(default_factory=list)
    operations_board: list[AdminOpsBoardRow] = Field(default_factory=list)


class AdminOpsDashboardResponse(DashboardResponseBase):
    data: AdminOpsDashboardData


# ── Delivery Lead — intentionally no finance fields ─────────────────────────


class DeliveryLeadKpis(DashboardModel):
    open_requests: DashboardKpi
    open_vacancies: DashboardKpi
    first_recommendation_sla_pct: DashboardKpi
    median_time_to_first_recommendation_hours: DashboardKpi
    fill_rate_pct: DashboardKpi
    placements: DashboardKpi


class DeliveryRiskBoardRow(DashboardModel):
    client_id: int
    client_name: str
    job_id: int
    job_title: str
    priority: str
    open_vacancies: int
    tac_user_id: int | None = None
    # `None` = nie znamy daty otwarcia rekrutacji (0270). Zero znaczyłoby
    # „otwarta dzisiaj", a dla wierszy sprzed backfillu byłaby to data importu.
    age_days: Optional[int] = None
    first_recommendation_at: datetime | None = None
    risk: DashboardSeverity
    next_action_href: str


class DeliveryLeadDashboardData(DashboardModel):
    kpis: DeliveryLeadKpis
    alerts: list[DashboardAlert] = Field(default_factory=list)
    queue: list[DashboardQueueItem] = Field(default_factory=list)
    risk_board: list[DeliveryRiskBoardRow] = Field(default_factory=list)


class DeliveryLeadDashboardResponse(DashboardResponseBase):
    data: DeliveryLeadDashboardData


# ── Head of Recruitment ─────────────────────────────────────────────────────


class HeadOfRecruitmentKpis(DashboardModel):
    priority_vacancies: DashboardKpi
    unassigned_work: DashboardKpi
    capacity_utilization_pct: DashboardKpi
    first_recommendation_sla_pct: DashboardKpi
    recommendation_to_interview_pct: DashboardKpi
    placements: DashboardKpi


class RecruitmentTeamBoardRow(DashboardModel):
    user_id: int
    user_name: str
    roles: list[str] = Field(default_factory=list)
    status: str
    verification_capacity: int
    verification_target: int
    assignment_count: int
    carry_over_count: int
    urgent_carry_over_count: int
    blocker_count: int


class HeadOfRecruitmentDashboardData(DashboardModel):
    kpis: HeadOfRecruitmentKpis
    alerts: list[DashboardAlert] = Field(default_factory=list)
    queue: list[DashboardQueueItem] = Field(default_factory=list)
    team_board: list[RecruitmentTeamBoardRow] = Field(default_factory=list)


class HeadOfRecruitmentDashboardResponse(DashboardResponseBase):
    data: HeadOfRecruitmentDashboardData


# ── Sourcer / TAC / Recruiter ───────────────────────────────────────────────


class MyWorkKpis(DashboardModel):
    plan_completion_pct: DashboardKpi
    overdue_actions: DashboardKpi
    completed_calls: DashboardKpi
    first_verifications: DashboardKpi
    first_recommendations: DashboardKpi
    placements: DashboardKpi


class MyWorkDashboardData(DashboardModel):
    kpis: MyWorkKpis
    alerts: list[DashboardAlert] = Field(default_factory=list)
    queue: list[DashboardQueueItem] = Field(default_factory=list)


class MyWorkDashboardResponse(DashboardResponseBase):
    data: MyWorkDashboardData


# ── Finance — intentionally no candidate/person fields ──────────────────────


class FinanceOperationsKpis(DashboardModel):
    mrr_pln: DashboardKpi
    monthly_margin_pln: DashboardKpi
    margin_pct: DashboardKpi
    outstanding_pln: DashboardKpi
    overdue_pln: DashboardKpi
    revenue_forecast_3m_pln: DashboardKpi


class FinanceExecutiveKpis(DashboardModel):
    mrr_pln: DashboardKpi
    monthly_margin_pln: DashboardKpi
    margin_pct: DashboardKpi
    revenue_forecast_3m_pln: DashboardKpi
    utilization_pct: DashboardKpi
    mrr_at_risk_90d_pln: DashboardKpi


class FinanceExceptionBoardRow(DashboardModel):
    id: str
    severity: DashboardSeverity
    kind: str
    client_id: int | None = None
    client_name: str | None = None
    contract_id: int | None = None
    invoice_id: int | None = None
    invoice_number: str | None = None
    amount: str | None = None
    currency: str | None = None
    due_at: datetime | None = None
    next_action_href: str | None = None


class FinanceOperationsDashboardData(DashboardModel):
    tab: Literal["operations"] = "operations"
    kpis: FinanceOperationsKpis
    alerts: list[DashboardAlert] = Field(default_factory=list)
    queue: list[DashboardQueueItem] = Field(default_factory=list)
    exceptions_board: list[FinanceExceptionBoardRow] = Field(default_factory=list)


class FinanceExecutiveDashboardData(DashboardModel):
    tab: Literal["executive"] = "executive"
    kpis: FinanceExecutiveKpis
    alerts: list[DashboardAlert] = Field(default_factory=list)
    queue: list[DashboardQueueItem] = Field(default_factory=list)
    exceptions_board: list[FinanceExceptionBoardRow] = Field(default_factory=list)


FinanceDashboardData = Union[
    FinanceOperationsDashboardData,
    FinanceExecutiveDashboardData,
]


class FinanceDashboardResponse(DashboardResponseBase):
    data: FinanceDashboardData = Field(discriminator="tab")


# ── Statystyki rekrutacji (sekcja wspólna /dashboard) ───────────────────────
#
# Sekcja jest z natury IMIENNA (tabela per osoba, podia, wyścigi, LinkedIn),
# więc jej guard to OperationalUser — persona finance jej nie widzi i ten
# kontrakt NIE może wejść do FinanceDashboardResponse (containment
# strukturalny). Każdy pod-blok jest `| None`: awaria źródła daje null +
# sekcję `unavailable` w data_quality, nigdy fabrykowane zera.


class RecruitmentStatsPeriod(DashboardModel):
    kind: str
    start: datetime
    end: datetime
    timezone: str = "Europe/Warsaw"


class RecruitmentStatsKpis(DashboardModel):
    """5 kafli — zawsze z `totals` tabeli zespołu (jedno przeliczenie CTE)."""

    verifications: DashboardKpi
    recommendations: DashboardKpi
    interviews: DashboardKpi
    acceptances: DashboardKpi
    placements: DashboardKpi


class RecruitmentTeamTableRow(DashboardModel):
    user_id: int
    name: str
    role: str
    verifications: int
    recommendations: int
    interviews: int
    acceptances: int
    placements: int
    cv_to_base: int
    precision_pct: float | None = None
    precision_verified_30d: int
    precision_sent_30d: int
    # False = osoba nieaktywna z dorobkiem w oknie. Wiersz zostaje, bo kafle są
    # sumą tabeli — bez niego odejście rekrutera kasowałoby wstecznie wynik firmy.
    is_active: bool = True


class RecruitmentTeamTableTotals(DashboardModel):
    verifications: int
    recommendations: int
    interviews: int
    acceptances: int
    placements: int
    cv_to_base: int
    precision_pct: float | None = None
    people: int
    # Kamienie milowe w oknie bez możliwej atrybucji do użytkownika. Nie wchodzą
    # do sum per osoba (nie ma do kogo), ale są raportowane — brak danych nie
    # może renderować się jako zero.
    unattributed: int = 0


class RecruitmentTeamTable(DashboardModel):
    precision_target_pct: int
    rows: list[RecruitmentTeamTableRow] = Field(default_factory=list)
    totals: RecruitmentTeamTableTotals


class RecruitmentFunnelConversions(DashboardModel):
    """Konwersje ze zliczeń okresu (nie kohorty).

    `None` ma dwa znaczenia i rozróżnia je wyłącznie `uncovered`: mianownik
    był zerowy, albo któryś operand pochodzi z etapu bez pokrycia w imporcie
    (wtedy nazwa pola jest w `uncovered`, a `coverage_note` mówi dlaczego).
    """

    verified_to_recommendation_pct: float | None = None
    recommendation_to_interview_pct: float | None = None
    interview_to_acceptance_pct: float | None = None
    acceptance_to_placement_pct: float | None = None
    interview_to_placement_pct: float | None = None
    overall_pct: float | None = None
    uncovered: list[str] = Field(default_factory=list)
    coverage_note: str | None = None


class CompetitionRankingEntry(DashboardModel):
    """Typowany wpis rankingu (zamiast luźnych dictów `RankedUser.to_dict`).

    Pola opcjonalne pokrywają unię extras wszystkich typów konkursów;
    mapowanie jawnie wybiera znane klucze, więc nowe extras nie łamią
    kontraktu `extra="forbid"`.
    """

    rank: int
    user_id: int
    name: str
    metric_value: float | int
    role: str | None = None
    hit_ratio: float | None = None
    prize_pln: int | None = None
    excluded: bool = False
    qualified: bool | None = None
    placements: int | None = None
    interviews: int | None = None
    recommendations: int | None = None
    verifications: int | None = None
    precision_pct: float | None = None
    required_verifications: int | None = None
    disqualification_reasons: list[str] = Field(default_factory=list)
    # Hall of Fame jest rankingiem WSZECH CZASÓW i świadomie zostawia byłych
    # pracowników — odejście z firmy nie cofa tego, co ktoś osiągnął. Bez tego
    # pola widget nie ma jak ich oznaczyć i wiersz kłamie przez przemilczenie.
    # `None` = ranking, który tego nie rozróżnia (konkursy okresowe).
    is_active: bool | None = None


class RecruitmentQuarterlyLeague(DashboardModel):
    period: str
    days_remaining: int
    points_formula: dict[str, int]
    prizes_pln: dict[str, int]
    requirement: str
    top3: list[CompetitionRankingEntry] = Field(default_factory=list)
    full_ranking: list[CompetitionRankingEntry] = Field(default_factory=list)


class RecruitmentMonthlyRace(DashboardModel):
    requirements: list[str] = Field(default_factory=list)
    ranking: list[CompetitionRankingEntry] = Field(default_factory=list)
    excluded_user_ids: list[int] = Field(default_factory=list)
    qualified_leader_user_id: int | None = None


class RecruitmentMonthlyRaces(DashboardModel):
    period: str
    days_remaining: int
    prize_amount_pln: int
    prize_name: str
    recommendations: RecruitmentMonthlyRace
    placements: RecruitmentMonthlyRace


class RecruitmentHallOfFameHistoryEntry(DashboardModel):
    rank: int
    user_id: int
    name: str
    metric_value: float | int | None = None
    points: int | None = None
    prize_pln: int | None = None


class RecruitmentHallOfFameHistoryPeriod(DashboardModel):
    period: str
    top3: list[RecruitmentHallOfFameHistoryEntry] = Field(default_factory=list)


class RecruitmentHallOfFame(DashboardModel):
    """All-time TOP 5 (live) + zamrożone podia ligi z historii."""

    all_time: list[CompetitionRankingEntry] = Field(default_factory=list)
    history: list[RecruitmentHallOfFameHistoryPeriod] = Field(default_factory=list)


class RecruitmentLinkedInRow(DashboardModel):
    user_id: int
    name: str
    role: str
    cv_added: int
    messages_sent: int
    responses_received: int
    response_rate: float
    cv_response_rate: float
    days_reported: int


class RecruitmentLinkedInTotals(DashboardModel):
    cv_added: int
    messages_sent: int
    responses_received: int
    response_rate: float
    cv_response_rate: float
    active_users: int


class RecruitmentLinkedIn(DashboardModel):
    date_from: date
    date_to: date
    per_user: list[RecruitmentLinkedInRow] = Field(default_factory=list)
    totals: RecruitmentLinkedInTotals


class RecruitmentTrendMonth(DashboardModel):
    month: str
    verifications: int
    recommendations: int
    interviews: int
    acceptances: int
    placements: int


class RecruitmentTrend(DashboardModel):
    months: list[RecruitmentTrendMonth] = Field(default_factory=list)


class RecruitmentStatsData(DashboardModel):
    period: RecruitmentStatsPeriod
    kpis: RecruitmentStatsKpis
    team_table: RecruitmentTeamTable | None = None
    conversions: RecruitmentFunnelConversions | None = None
    quarterly_league: RecruitmentQuarterlyLeague | None = None
    monthly_races: RecruitmentMonthlyRaces | None = None
    hall_of_fame: RecruitmentHallOfFame | None = None
    linkedin: RecruitmentLinkedIn | None = None
    trend: RecruitmentTrend | None = None


class RecruitmentStatsDashboardResponse(DashboardResponseBase):
    data: RecruitmentStatsData
