from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel

from app.models.contract_amendment import ContractAmendmentType


class ContractAmendmentCreate(BaseModel):
    amendment_type: ContractAmendmentType
    effective_date: date
    reason: Optional[str] = None
    document_id: Optional[int] = None

    # Target fields — only the ones relevant for the given amendment_type
    # will be applied to the contract. Everything else is captured in
    # old_values / new_values for audit.
    new_end_date: Optional[date] = None
    new_rate_candidate: Optional[Decimal] = None
    new_rate_client: Optional[Decimal] = None
    new_rate_unit: Optional[str] = None
    new_billing_hours_per_month: Optional[int] = None
    new_project_name: Optional[str] = None
    new_team_name: Optional[str] = None


class AmendmentDocument(BaseModel):
    """Plik aneksu w Dokumentach kontraktu."""

    id: int
    filename: str
    #: Skan z podpisami wgrany przez człowieka, a nie DOCX wygenerowany przez
    #: NEXUS (ten jest wersją roboczą, bez podpisów).
    is_signed_scan: bool = False


class ContractAmendmentResponse(BaseModel):
    id: int
    contract_id: int
    amendment_type: ContractAmendmentType
    old_values: Optional[Any] = None
    new_values: Optional[Any] = None
    effective_date: date
    reason: Optional[str] = None
    document_id: Optional[int] = None
    created_by: Optional[int] = None
    created_by_email: Optional[str] = None
    created_at: datetime
    # Zakładka „Aneksy” jako tabela (13.10.2026) — pola dokładane, stare zostają.
    created_by_name: Optional[str] = None
    #: ``generator`` = aneks podpisany w Generatorze aneksów, ``manual`` =
    #: dodany przyciskami w kontrakcie.
    source: str = "manual"
    b2b_document_id: Optional[int] = None
    #: ``in_force`` albo ``signed_pending`` (dzień wejścia w życie nie nadszedł).
    state: str = "in_force"
    document: Optional[AmendmentDocument] = None

    model_config = {"from_attributes": True}


class ContractAnnexDocument(BaseModel):
    """Aneks z Generatora aneksów, którego historia kontraktu jeszcze (albo
    wcale) nie zapisała: czeka na podpis, anulowany, podpisany bez zmiany
    w kontrakcie. Rzut dokumentu — nie wiersz ``contract_amendments``."""

    document_id: int
    document_type: str
    type_label: str
    state: str
    effective_date: Optional[date] = None
    #: ``annex_summary.annex_change`` — kwoty tylko z wglądem w stawki klienta.
    change: Optional[dict] = None
    cancelled_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    created_by_name: Optional[str] = None
