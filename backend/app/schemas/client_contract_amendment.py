"""Schemas dla `ClientContractAmendment` (aneks do MSA)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ClientContractAmendmentCreate(BaseModel):
    """POST `/api/clients/{client_id}/framework-contracts/{contract_id}/amendments`."""

    name: str = Field(..., min_length=1, max_length=255)
    effective_date: date
    changes_summary: Optional[str] = None
    old_terms: Optional[dict[str, Any]] = None
    new_terms: Optional[dict[str, Any]] = None


class ClientContractAmendmentRead(BaseModel):
    id: int
    framework_contract_id: int
    name: str
    effective_date: date
    changes_summary: Optional[str]
    old_terms: Optional[dict[str, Any]]
    new_terms: Optional[dict[str, Any]]
    filename: Optional[str]
    has_file: bool
    content_type: Optional[str]
    size_bytes: Optional[int]
    uploaded_by: Optional[int]
    uploaded_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
