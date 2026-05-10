"""Schemas dla `ClientOrder` (zamówienie od klienta pod kandydackim Contract)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.client_order import ClientOrderStatus


class ClientOrderCreate(BaseModel):
    """POST `/api/clients/{client_id}/orders` — Flow A "Dodaj przedłużenie".

    Tworzy Order pod istniejącym kandydackim Contractem.
    """

    contract_id: int  # Required: każdy Order pod konkretnym Contract
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: ClientOrderStatus = ClientOrderStatus.draft
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_client: Optional[int] = Field(None, ge=0)
    """Może być różny od Contract.rate_client (przedłużenie z podwyżką)."""
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    framework_contract_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None


class ClientOrderUpdate(BaseModel):
    """PATCH metadata orderu — plik wymaga osobnego PUT `/file`."""

    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ClientOrderStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_client: Optional[int] = Field(None, ge=0)
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    framework_contract_id: Optional[int] = None
    job_id: Optional[int] = None
    notes: Optional[str] = None


class ClientOrderRead(BaseModel):
    id: int
    client_id: int
    contract_id: int
    job_id: Optional[int]
    framework_contract_id: Optional[int]
    title: str
    description: Optional[str]
    status: ClientOrderStatus
    start_date: Optional[date]
    end_date: Optional[date]
    rate_client: Optional[int]
    total_value: Optional[Decimal]
    currency: Optional[str]
    filename: Optional[str]
    has_file: bool
    content_type: Optional[str]
    size_bytes: Optional[int]
    created_by_user_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Computed (z join'a Contract → Candidate + Job):
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    contract_status: Optional[str] = None
    job_title: Optional[str] = None
    monthly_margin: Optional[int] = None
    """rate_client (z Order) - rate_candidate (z Contract), normalizowane do mc."""
    days_to_end: Optional[int] = None

    model_config = {"from_attributes": True}


class ContractWithOrdersRead(BaseModel):
    """Wynik `GET /api/clients/{client_id}/orders` — grupowane po Contract.

    Każdy wiersz = jeden kontraktor (Contract), pod nim historia Orderów (timeline).
    """

    contract_id: int
    candidate_id: int
    candidate_name: str
    contract_status: str
    contract_start_date: Optional[date]
    contract_end_date: Optional[date]
    rate_candidate: Optional[int]  # we płacimy

    # Initial Job z którego powstał Contract
    initial_job_id: Optional[int]
    initial_job_title: Optional[str]

    # Pozycja na obecnym kontrakcie (z Order najnowszego)
    latest_order_id: Optional[int] = None
    latest_order_end_date: Optional[date] = None
    latest_order_rate_client: Optional[int] = None
    latest_order_monthly_margin: Optional[int] = None
    days_to_latest_end: Optional[int] = None

    orders: list[ClientOrderRead] = []


class ClientOrdersGroupedResponse(BaseModel):
    """`GET /api/clients/{client_id}/orders` response."""

    contractors: list[ContractWithOrdersRead]
    total_contractors: int
