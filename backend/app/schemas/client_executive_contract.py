"""Schematy struktury umów Centrum e-Zdrowia: umowa ramowa (część) → wykonawcze.

Kontrakt API (ticket 09.2026), współdzielony przez router
``client_executive_contracts``, profil klienta i grupy zamówień MD.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

ExecutiveContractStatus = Literal["active", "ended"]


class ExecutiveContractBrief(BaseModel):
    """Wąska projekcja do tagów i selektów (profil, zamówienie, karta MD)."""

    model_config = {"from_attributes": True}

    id: int
    number: str
    status: ExecutiveContractStatus
    framework_contract_id: int
    project_part: Optional[str] = None
    """Część umowy ramowej, pod którą wisi umowa (``cz1``…``cz6``)."""


class ExecutiveContractRead(ExecutiveContractBrief):
    notes: Optional[str] = None
    consultants_count: int = 0
    """Liczba kontraktów, których reprezentatywne zamówienie wskazuje tę umowę."""
    created_at: Optional[datetime] = None


class FrameworkPartRead(BaseModel):
    """Umowa ramowa będąca częścią (``project_part IS NOT NULL``)."""

    model_config = {"from_attributes": True}

    id: int
    name: str
    project_part: str
    status: str
    executive_contracts: list[ExecutiveContractRead] = Field(default_factory=list)


class ContractStructureResponse(BaseModel):
    framework_contracts: list[FrameworkPartRead]
    """W kolejności części: cz1, cz2, cz4, cz5, cz6."""


class ExecutiveContractCreate(BaseModel):
    framework_contract_id: int
    number: str = Field(..., min_length=1, max_length=64)
    notes: Optional[str] = None

    @field_validator("number")
    @classmethod
    def _strip_number(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Podaj numer umowy wykonawczej")
        return cleaned


class ExecutiveContractUpdate(BaseModel):
    """PATCH — pola nieprzysłane zostają bez zmian (``exclude_unset``)."""

    number: Optional[str] = Field(None, min_length=1, max_length=64)
    status: Optional[ExecutiveContractStatus] = None
    notes: Optional[str] = None

    @field_validator("number")
    @classmethod
    def _strip_number(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Podaj numer umowy wykonawczej")
        return cleaned


class CandidateRef(BaseModel):
    id: Optional[int] = None
    name: str


class ExecutiveContractReviewRow(BaseModel):
    """Konsultant do ręcznego przeglądu — bez umowy wykonawczej na
    reprezentatywnym zamówieniu (albo bez zamówienia w ogóle)."""

    contract_id: int
    candidate: CandidateRef
    start_date: Optional[date] = None
    bucket: Literal["active", "planned"]
    legacy_project_part: Optional[str] = None
    """Część z dotychczasowego ``project_part`` — tylko informacyjnie."""
    representative_order_id: Optional[int] = None
    suggested_framework_contract_id: Optional[int] = None
    """Umowa ramowa o tej samej części co legacy — WYŁĄCZNIE do podświetlenia
    nagłówka w selekcie; ekran nie preselekcjonuje żadnej umowy (ticket)."""


class ExecutiveContractReviewResponse(BaseModel):
    rows: list[ExecutiveContractReviewRow]
    total: int


class ExecutiveContractAssignmentRequest(BaseModel):
    contract_id: int
    executive_contract_id: int


class ExecutiveContractAssignmentResponse(BaseModel):
    contract_id: int
    order_id: int
    executive_contract: ExecutiveContractBrief
    created_draft: bool
    """``True`` gdy kontrakt nie miał zamówienia i przypisanie założyło szkic."""
