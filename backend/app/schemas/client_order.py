"""Schemas dla `ClientOrder` (Statement of Work / Zamówienie)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, Field

from app.models.client_order import ClientOrderStatus


class ClientOrderCreate(BaseModel):
    """POST `/api/clients/{client_id}/orders` (multipart `metadata`)."""

    framework_contract_id: int
    title: str = Field(..., min_length=1, max_length=255)
    description: Optional[str] = None
    status: ClientOrderStatus = ClientOrderStatus.draft
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    positions_count: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None


class ClientOrderUpdate(BaseModel):
    title: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    status: Optional[ClientOrderStatus] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    total_value: Optional[Decimal] = Field(None, ge=0, max_digits=12, decimal_places=2)
    currency: Optional[str] = Field(None, max_length=3)
    positions_count: Optional[int] = Field(None, ge=0)
    notes: Optional[str] = None


class OrderContractLink(BaseModel):
    """Link kandydackiego Contract do Order."""

    contract_id: int


class OrderContractLinkRead(BaseModel):
    id: int
    contract_id: int
    candidate_id: Optional[int] = None
    candidate_name: Optional[str] = None
    rate_client: Optional[int] = None
    rate_candidate: Optional[int] = None
    monthly_margin: Optional[int] = None
    contract_status: Optional[str] = None
    contract_start_date: Optional[date] = None
    contract_end_date: Optional[date] = None
    assigned_at: datetime

    model_config = {"from_attributes": True}


class ClientOrderRead(BaseModel):
    id: int
    client_id: int
    framework_contract_id: int
    title: str
    description: Optional[str]
    status: ClientOrderStatus
    start_date: Optional[date]
    end_date: Optional[date]
    total_value: Optional[Decimal]
    currency: Optional[str]
    positions_count: Optional[int]
    filename: Optional[str]
    has_file: bool
    content_type: Optional[str]
    size_bytes: Optional[int]
    created_by_user_id: Optional[int]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime

    # Computed:
    linked_contracts_count: int = 0
    filled_positions: int = 0
    monthly_margin_total: Optional[int] = None
    monthly_margin_pct: Optional[float] = None
    days_to_end: Optional[int] = None

    model_config = {"from_attributes": True}


class ClientOrderWithContractsRead(ClientOrderRead):
    """Pełny odczyt z linkowanymi candidate contracts."""

    contracts: list[OrderContractLinkRead] = []


class ClientOrderListResponse(BaseModel):
    items: list[ClientOrderRead]
    total: int
