"""Typed public contract for ``/api/analytics/v1``."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.analytics.periods import AnalyticsPeriodKind


SCHEMA_VERSION = "1.0"
METRIC_VERSION = "2026-07-14"


class AnalyticsQualityStatus(str, Enum):
    complete = "complete"
    partial = "partial"
    unavailable = "unavailable"


class AnalyticsPeriodSchema(BaseModel):
    kind: AnalyticsPeriodKind
    start: datetime
    end: datetime
    timezone: str = "Europe/Warsaw"


class AnalyticsQuality(BaseModel):
    status: AnalyticsQualityStatus = AnalyticsQualityStatus.complete
    warnings: list[str] = Field(default_factory=list)
    source_watermarks: dict[str, datetime | None] = Field(default_factory=dict)


T = TypeVar("T")


class AnalyticsEnvelope(BaseModel, Generic[T]):
    """Versioned response shared by every analytics v1 endpoint."""

    model_config = ConfigDict(use_enum_values=True)

    schema_version: str = SCHEMA_VERSION
    metric_version: str = METRIC_VERSION
    generated_at: datetime
    scope: str
    period: AnalyticsPeriodSchema
    quality: AnalyticsQuality
    data: T


class OverviewCandidates(BaseModel):
    total: int
    active: int


class OverviewJobs(BaseModel):
    total: int
    open: int


class OverviewClients(BaseModel):
    total: int
    active: int


class OverviewContracts(BaseModel):
    active: int
    expiring_30_days: int
    incomplete_date_data: int


class OverviewPipeline(BaseModel):
    placements: int


class OverviewData(BaseModel):
    """Organization aggregates safe for the read-only viewer role."""

    candidates: OverviewCandidates
    jobs: OverviewJobs
    clients: OverviewClients
    contracts: OverviewContracts
    pipeline: OverviewPipeline


class StageCount(BaseModel):
    stage: str
    candidates: int


class PipelineSnapshotData(BaseModel):
    total_pairs: int
    stages: list[StageCount]


class RecruitmentFunnelData(BaseModel):
    verified: int
    recommended: int
    internal_interview: int
    client_interview: int
    placed: int


class RecentHire(BaseModel):
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    client_id: int
    client_name: str
    hired_at: datetime


class RecentHiresData(BaseModel):
    hires: list[RecentHire]


class SourceMetric(BaseModel):
    source: str
    cohort_candidates: int
    placed_by_period_end: int
    hire_rate_pct: float


class SourcesData(BaseModel):
    attribution: str = "first_touch_cohort"
    sources: list[SourceMetric]


class CallsData(BaseModel):
    completed: int | None
    inbound: int | None
    outbound: int | None
    total_duration_seconds: int | None
    average_duration_seconds: float | None


class PrecisionMetric(BaseModel):
    value_pct: float | None
    verified: int
    recommended: int
    window_days: int = 30


class KpiTargets(BaseModel):
    calls_daily: int
    verifications_daily: int
    candidates_added_daily: int | None
    placements_monthly: int
    precision_pct: int


class PersonalKpiData(BaseModel):
    calls_completed: int | None
    calls_available: bool
    verifications: int
    candidates_added: int
    recommendations: int
    placements: int
    precision_30d: PrecisionMetric
    targets: KpiTargets


class TeamKpiRow(BaseModel):
    user_id: int
    user_name: str
    primary_role: str
    calls_completed: int | None
    calls_available: bool
    verifications: int
    candidates_added: int
    recommendations: int
    placements: int
    targets: KpiTargets


class TeamKpisData(BaseModel):
    users: list[TeamKpiRow]


class TeamCallRow(BaseModel):
    user_id: int
    user_name: str
    completed: int
    total_duration_seconds: int
    average_duration_seconds: float | None


class TeamCallsData(BaseModel):
    users: list[TeamCallRow]


class MetricDefinition(BaseModel):
    key: str
    label: str
    definition: str
    source: str
    timezone: str = "Europe/Warsaw"


class MetricsMetaData(BaseModel):
    metric_version: str = METRIC_VERSION
    interval_semantics: str = "[start, end)"
    definitions: list[MetricDefinition]


# ── Manager, client and finance analytics ──────────────────────────────────


class ClientOperationsData(BaseModel):
    client_id: int
    client_name: str
    jobs_total: int
    jobs_open: int
    pipeline_pairs: int
    placements: int
    active_contracts: int


class FinanceTotals(BaseModel):
    revenue: str | None
    costs: str | None
    margin: str | None
    margin_pct: float | None
    currency: str = "PLN"


class ClientFinanceData(BaseModel):
    client_id: int
    client_name: str
    active_contracts: int
    incomplete_contracts: int
    totals: FinanceTotals


class FinanceSummaryData(BaseModel):
    report_date: str
    active_contracts: int
    incomplete_contracts: int
    totals: FinanceTotals


class FinanceTrendPoint(BaseModel):
    month: str
    active_contracts: int
    incomplete_contracts: int
    totals: FinanceTotals


class FinanceTrendData(BaseModel):
    months: list[FinanceTrendPoint]


class FinanceClientRow(BaseModel):
    client_id: int
    client_name: str
    active_contracts: int
    incomplete_contracts: int
    totals: FinanceTotals


class FinanceClientsData(BaseModel):
    clients: list[FinanceClientRow]


class FinancialAdjustmentStatus(str, Enum):
    draft = "draft"
    approved = "approved"


class FinancialAdjustmentCreate(BaseModel):
    adjustment_date: date
    category: str = Field(min_length=1, max_length=64)
    description: str = Field(min_length=1, max_length=4000)
    amount: Decimal
    currency: str = Field(default="PLN", min_length=3, max_length=3)

    @field_validator("category", "description")
    @classmethod
    def _strip_required_text(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("value cannot be blank")
        return normalized

    @field_validator("currency")
    @classmethod
    def _normalize_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("currency must be a three-letter ISO code")
        return normalized

    @field_validator("amount")
    @classmethod
    def _require_nonzero_amount(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value == 0:
            raise ValueError("amount must be a finite non-zero decimal")
        return value


class FinancialAdjustmentRow(BaseModel):
    id: int
    adjustment_date: date
    category: str
    description: str
    amount: str
    currency: str
    amount_pln: str | None
    fx_rate: str | None
    fx_date: date | None
    status: FinancialAdjustmentStatus
    created_by_user_id: int
    approved_by_user_id: int | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class FinancialAdjustmentsData(BaseModel):
    adjustments: list[FinancialAdjustmentRow]


class TenderRow(BaseModel):
    job_id: int
    job_title: str
    client_id: int
    client_name: str
    outcome: str
    event_at: datetime


class TendersData(BaseModel):
    total: int
    won: int
    lost: int
    pending: int
    unknown: int
    win_rate_pct: float | None
    tenders: list[TenderRow]


class DeliveryLeadPerformanceRow(BaseModel):
    user_id: int
    user_name: str
    jobs: int
    verifications: int
    recommendations: int
    placements: int


class DeliveryLeadPerformanceData(BaseModel):
    delivery_leads: list[DeliveryLeadPerformanceRow]


class RecruitmentUserData(BaseModel):
    user_id: int
    user_name: str
    primary_role: str
    kpis: PersonalKpiData


class ExecutiveBoardData(BaseModel):
    overview: OverviewData
    finance: FinanceSummaryData
    tenders: TendersData
