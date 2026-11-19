"""Public API contracts for the client portfolio directory."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

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
    active_contracts_count: int = 0
    # ``scope`` = the row counts only contracts pinned to this scope's MSA
    # through their orders; ``client`` = the whole client (minus contracts
    # pinned to another scope of the same client).
    consultants_scope: Literal["scope", "client"] = "client"
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


ClientListState = Literal["working", "idle", "archive"]


class ClientListStateCounts(BaseModel):
    """Widoczni klienci w każdym stanie listy (wyszukiwanie ich nie zmienia)."""

    working: int = 0
    idle: int = 0
    archive: int = 0


class ClientListDeliveryLead(BaseModel):
    name: str
    is_head: bool = False


class ClientListConsultantAttention(BaseModel):
    """Obecni konsultanci ze znacznikiem „Wymaga uwagi” — te same reguły co
    zakładka Konsultanci w profilu (``services/consultant_order_state.py``)."""

    total: int = 0
    order_ending: int = 0
    order_ending_first: Optional[date] = None
    no_current_order: int = 0
    notice: int = 0


class ClientListItem(BaseModel):
    """Jeden klient na liście „Klienci” (makieta 19.11.2026, wariant A).

    ``state`` liczy się z faktów: ``working`` = ktoś od nas pracuje albo
    zaczyna u klienta, albo trwa rekrutacja; bez tego zakładka portfela
    (aktywni/relacyjni → ``idle``, nieaktywni → ``archive``).
    """

    client_id: int
    display_name: str
    legal_name: Optional[str] = None
    industry: Optional[str] = None
    state: ClientListState
    active_consultants: int = 0
    planned_consultants: int = 0
    open_jobs: int = 0
    # Miesięczna marża w PLN — ta sama liczba co „Aktywne MRR” profilu.
    # ``None`` = kwoty niewidoczne dla tej osoby albo brak kursu waluty.
    monthly_margin: Optional[int] = None
    monthly_margin_unpriced: int = 0
    delivery_leads: list[ClientListDeliveryLead] = Field(default_factory=list)
    framework_effective_date: Optional[date] = None
    framework_expiry_date: Optional[date] = None
    has_framework_period: bool = False
    framework_count: int = 0
    consultant_attention: ClientListConsultantAttention = Field(
        default_factory=ClientListConsultantAttention
    )
    # Zakładka albo daty umowy ustawione ręcznie, inaczej niż manifest —
    # informacja do „Porządków portfela”, nie do listy.
    manually_placed: bool = False


class ClientListResponse(BaseModel):
    items: list[ClientListItem]
    total: int
    page: int
    page_size: int
    state_counts: ClientListStateCounts
    # Czy ta osoba może zobaczyć kwoty na liście (kolumna „Marża / mc”).
    amounts_visible: bool = False
    manually_placed_count: int = 0
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
