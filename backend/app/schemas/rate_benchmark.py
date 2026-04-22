"""Pydantic schemas for RateBenchmark — CRUD + CSV import response."""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.contract import RateUnit
from app.models.rate_benchmark import SeniorityLevel


class RateBenchmarkBase(BaseModel):
    role: str = Field(..., max_length=160)
    seniority: Optional[SeniorityLevel] = None
    currency: str = "PLN"
    rate_unit: RateUnit
    market_min: Optional[int] = None
    market_median: int
    market_max: Optional[int] = None
    source: str = Field(..., max_length=200)
    source_date: date
    location: Optional[str] = None
    notes: Optional[str] = None


class RateBenchmarkCreate(RateBenchmarkBase):
    pass


class RateBenchmarkUpdate(BaseModel):
    role: Optional[str] = None
    seniority: Optional[SeniorityLevel] = None
    currency: Optional[str] = None
    rate_unit: Optional[RateUnit] = None
    market_min: Optional[int] = None
    market_median: Optional[int] = None
    market_max: Optional[int] = None
    source: Optional[str] = None
    source_date: Optional[date] = None
    location: Optional[str] = None
    notes: Optional[str] = None


class RateBenchmarkResponse(RateBenchmarkBase):
    id: int
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class RateBenchmarkImportResult(BaseModel):
    created: int
    skipped: int
    errors: list[str] = []
