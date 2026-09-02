"""Contracts for the compact, drillable recruitment activity dashboard."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RecruitmentActivityMetric = Literal[
    "verification",
    "recommendation",
    "interview",
    "acceptance",
    "placement",
]
RecruitmentActivityWindow = Literal["day", "month"]
RecruitmentActivityScope = Literal["person", "team"]


class RecruitmentActivityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecruitmentActivityPerson(RecruitmentActivityModel):
    id: int
    name: str
    role: str


class RecruitmentActivityMetricCounts(RecruitmentActivityModel):
    metric: RecruitmentActivityMetric
    day: int | None
    month: int


class RecruitmentActivityProgress(RecruitmentActivityModel):
    current: int
    target: int
    progress_pct: float
    remaining: int


class RecruitmentActivityComparison(RecruitmentActivityModel):
    metric: Literal["verification", "placement"]
    personal_average: float | None
    team_average: float | None
    months: int
    period_start: date
    period_end: date
    people: int


class RecruitmentActivitySummaryResponse(RecruitmentActivityModel):
    generated_at: datetime
    day: date
    month: date
    scope: RecruitmentActivityScope
    can_view_team_details: bool
    subject: RecruitmentActivityPerson | None = None
    selectable_people: list[RecruitmentActivityPerson] = Field(default_factory=list)
    metrics: list[RecruitmentActivityMetricCounts] = Field(default_factory=list)
    verification_progress: RecruitmentActivityProgress | None = None
    comparisons: list[RecruitmentActivityComparison] = Field(default_factory=list)


class RecruitmentActivityCandidate(RecruitmentActivityModel):
    id: int
    name: str
    href: str


class RecruitmentActivityJob(RecruitmentActivityModel):
    id: int
    title: str
    client_name: str
    href: str


class RecruitmentActivityDetailItem(RecruitmentActivityModel):
    candidate: RecruitmentActivityCandidate
    job: RecruitmentActivityJob
    credited_user: RecruitmentActivityPerson | None = None
    reached_at: datetime


class RecruitmentActivityDetailResponse(RecruitmentActivityModel):
    generated_at: datetime
    metric: RecruitmentActivityMetric
    window: RecruitmentActivityWindow
    page: int
    page_size: int
    total: int
    items: list[RecruitmentActivityDetailItem] = Field(default_factory=list)
