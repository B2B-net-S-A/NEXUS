"""Public API contracts for the client portfolio directory."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator

from app.models.client import ClientStatus
from app.models.client_directory import PortfolioCategory


class ClientDirectoryCategoryCounts(BaseModel):
    """Unique, visible clients in each portfolio category."""

    active: int = 0
    relationship: int = 0
    inactive: int = 0


class ClientDirectoryItem(BaseModel):
    """One directory row.

    A client may have more than one row because the row identity is a portfolio
    scope, not the client itself.  The counters above intentionally count
    distinct clients.
    """

    scope_id: int
    client_id: int
    msa_id: Optional[int] = None
    display_name: str
    legal_name: Optional[str] = None
    scope_label: Optional[str] = None
    industry: Optional[str] = None
    active_consultants_count: int = 0
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    category: PortfolioCategory
    client_status: ClientStatus


class ClientDirectoryResponse(BaseModel):
    items: list[ClientDirectoryItem]
    total_rows: int
    total_clients: int
    page: int
    page_size: int
    category_counts: ClientDirectoryCategoryCounts
    as_of: date


class ClientPortfolioScopeCreate(BaseModel):
    category: PortfolioCategory
    label: Optional[str] = Field(None, max_length=255)
    framework_contract_id: Optional[int] = None

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ClientPortfolioScopeUpdate(BaseModel):
    category: Optional[PortfolioCategory] = None
    label: Optional[str] = Field(None, max_length=255)
    framework_contract_id: Optional[int] = None

    @field_validator("category")
    @classmethod
    def reject_null_category(
        cls, value: Optional[PortfolioCategory]
    ) -> Optional[PortfolioCategory]:
        if value is None:
            raise ValueError("category cannot be null")
        return value

    @field_validator("label")
    @classmethod
    def normalize_label(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class ClientPortfolioScopeResponse(BaseModel):
    id: int
    client_id: int
    framework_contract_id: Optional[int] = None
    category: PortfolioCategory
    label: Optional[str] = None
    source_system: str
    source_key: Optional[str] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
