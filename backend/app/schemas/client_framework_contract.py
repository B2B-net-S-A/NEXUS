"""Schemas dla `ClientFrameworkContract` (umowa ramowa / MSA)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from app.models.client_framework_contract import (
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)


class ClientFrameworkContractCreate(BaseModel):
    """POST `/api/clients/{client_id}/framework-contracts` (multipart `metadata`)."""

    name: str = Field(..., min_length=1, max_length=255)
    status: FrameworkContractStatus = FrameworkContractStatus.draft
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    signed_via: FrameworkContractSignedVia = FrameworkContractSignedVia.upload
    currency: Optional[str] = Field(None, max_length=3)
    parent_contract_id: Optional[int] = None
    contract_terms_id: Optional[int] = None
    notes: Optional[str] = None


class ClientFrameworkContractUpdate(BaseModel):
    """PATCH metadata — plik wymaga osobnego endpointu (`/file`) jeśli zmiana."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    status: Optional[FrameworkContractStatus] = None
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    signed_via: Optional[FrameworkContractSignedVia] = None
    currency: Optional[str] = Field(None, max_length=3)
    parent_contract_id: Optional[int] = None
    contract_terms_id: Optional[int] = None
    notes: Optional[str] = None


class ClientFrameworkContractRead(BaseModel):
    id: int
    client_id: int
    name: str
    status: FrameworkContractStatus
    effective_date: Optional[date]
    expiry_date: Optional[date]
    signed_via: FrameworkContractSignedVia
    currency: Optional[str]
    parent_contract_id: Optional[int]
    contract_terms_id: Optional[int]
    filename: Optional[str]
    has_file: bool
    content_type: Optional[str]
    size_bytes: Optional[int]
    uploaded_by: Optional[int]
    uploaded_at: Optional[datetime]
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime
    amendments_count: int = 0
    days_to_expiry: Optional[int] = None

    model_config = {"from_attributes": True}


class ClientFrameworkContractListResponse(BaseModel):
    items: list[ClientFrameworkContractRead]
    total: int
