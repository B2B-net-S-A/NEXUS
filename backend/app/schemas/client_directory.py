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
    # ``effective_date`` / ``expiry_date`` / ``category`` are the EFFECTIVE
    # values: a manual placement override wins over the manifest / linked MSA.
    effective_date: Optional[date] = None
    expiry_date: Optional[date] = None
    category: PortfolioCategory
    # The manifest/base category (before any manual override). The UI compares it
    # with ``category`` to tell a genuine manual placement from a redundant one
    # and to clear an override that matches the manifest again.
    category_base: PortfolioCategory
    client_status: ClientStatus
    # Raw override state so the UI can flag a manually-placed row and prefill the
    # edit dialog exactly (``None`` means the row follows the manifest / MSA).
    category_override: Optional[PortfolioCategory] = None
    contract_start_override: Optional[date] = None
    contract_end_override: Optional[date] = None


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


class ClientPortfolioScopePlacementUpdate(BaseModel):
    """Manual placement overrides — never touch the manifest base columns.

    A field present in the request is applied to the matching ``*_override``
    column; ``null`` clears it (the row falls back to the manifest / linked
    MSA).  A field that is absent is left unchanged (partial update), so
    ``{"category": "active"}`` moves the tab without disturbing the dates.
    """

    category: Optional[PortfolioCategory] = None
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None


class ClientPortfolioScopeResponse(BaseModel):
    id: int
    client_id: int
    framework_contract_id: Optional[int] = None
    category: PortfolioCategory
    category_override: Optional[PortfolioCategory] = None
    contract_start_override: Optional[date] = None
    contract_end_override: Optional[date] = None
    label: Optional[str] = None
    source_system: str
    source_key: Optional[str] = None
    archived_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
