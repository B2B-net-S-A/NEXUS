"""Typed contracts for the canonical role dashboards.

The dashboard API deliberately exposes narrow, role-specific models instead of
one ``dict[str, Any]`` payload.  Two containment properties are structural:

* Delivery Lead schemas contain no money, rate, invoice or margin fields.
* Finance schemas contain no candidate/person fields.

Every section can independently report incomplete data.  An unavailable source
must therefore never be serialized as a numeric zero.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Union

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
    age_days: int
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
