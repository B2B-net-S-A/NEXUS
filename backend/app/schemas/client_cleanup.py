"""Kształty API jednorazowego czyszczenia zakładki „Nieaktywni klienci"."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class CleanupSourceHit(BaseModel):
    code: str
    label: str
    count: int


class CleanupReason(BaseModel):
    """Jedno znalezione powiązanie, które wstrzymało usunięcie (lista B)."""

    code: str
    label: str
    count: int = 0
    effect: Optional[str] = None
    table: Optional[str] = None
    column: Optional[str] = None
    details: list[str] = Field(default_factory=list)


class CleanupClientEntry(BaseModel):
    client_id: int
    name: str
    legal_name: Optional[str] = None
    nip: Optional[str] = None
    status: Optional[str] = None
    external_source: Optional[str] = None
    external_id: Optional[str] = None
    sources: list[CleanupSourceHit] = Field(default_factory=list)
    reasons: list[CleanupReason] = Field(default_factory=list)


class CleanupPreviewResponse(BaseModel):
    evaluated_at: str
    candidates_count: int
    to_delete: list[CleanupClientEntry]
    held: list[CleanupClientEntry]
    kept: list[CleanupClientEntry]
    kept_by_source: dict[str, int]
    source_labels: dict[str, str]


class CleanupDeletedEntry(BaseModel):
    client_id: int
    name: str
    legal_name: Optional[str] = None
    nip: Optional[str] = None
    external_source: Optional[str] = None
    external_id: Optional[str] = None
    purged_at: Optional[str] = None


class CleanupReport(BaseModel):
    run_id: int
    executed_at: Optional[str] = None
    executed_by_name: Optional[str] = None
    candidates_count: int
    kept_count: int
    deleted_count: int
    held_count: int
    deleted: list[CleanupDeletedEntry]
    held: list[CleanupClientEntry]
    summary: dict[str, Any] = Field(default_factory=dict)


class CleanupStatusResponse(BaseModel):
    """``report`` jest pusty, dopóki operacja się nie odbyła."""

    report: Optional[CleanupReport] = None
    source_labels: dict[str, str]


class CleanupExecuteRequest(BaseModel):
    # Id z listy „do usunięcia" pokazanej w podglądzie. Serwer usuwa wyłącznie
    # przecięcie tej listy z klientami, którzy NADAL się kwalifikują.
    confirmed_client_ids: list[int] = Field(default_factory=list, max_length=5000)
