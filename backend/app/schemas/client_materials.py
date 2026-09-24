"""Pydantic schemas for the client "Materiały" sub-tab.

Covers:
  - ClientOnePager: metadata-only responses (no file bytes; download goes
    through the dedicated endpoint)
  - ClientContractTerms: structured MSA clauses (off-limits, internalization,
    payment, warranty) — single row per client, edited via upsert
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, model_validator


class ClientOnePagerResponse(BaseModel):
    id: int
    client_id: int
    title: str
    description: Optional[str] = None
    version: Optional[str] = None
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    uploaded_by: Optional[int] = None
    uploaded_by_email: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ClientContractTermsBase(BaseModel):
    # Off-limits
    off_limits_months: Optional[int] = None
    off_limits_scope: Optional[str] = None
    off_limits_notes: Optional[str] = None

    # Internalization
    internalization_fee_pct: Optional[Decimal] = None
    internalization_min_months: Optional[int] = None
    internalization_notice_days: Optional[int] = None
    internalization_notes: Optional[str] = None

    # Payment
    payment_net_days: Optional[int] = None
    payment_currency: Optional[str] = None
    payment_invoice_cycle: Optional[str] = None
    payment_late_fees: Optional[str] = None
    payment_notes: Optional[str] = None

    # Termination & warranty
    notice_period_days: Optional[int] = None
    warranty_replacement_days: Optional[int] = None
    warranty_notes: Optional[str] = None

    # Free-text
    other_clauses: Optional[str] = None


# Lustro długości kolumn `client_contract_terms` — za długa wartość dawała
# surowy błąd bazy (500 bez CORS) zamiast czytelnego 422 (audyt S3).
_TERMS_MAX_LENGTH = {
    "off_limits_scope": (500, "Zakres off-limits"),
    "payment_currency": (3, "Waluta płatności"),
    "payment_invoice_cycle": (50, "Cykl fakturowania"),
    "payment_late_fees": (500, "Odsetki za opóźnienie"),
}


class ClientContractTermsUpsert(ClientContractTermsBase):
    @model_validator(mode="after")
    def _fits_columns(self) -> "ClientContractTermsUpsert":
        for field, (limit, label) in _TERMS_MAX_LENGTH.items():
            value = getattr(self, field)
            if value is not None and len(value) > limit:
                raise ValueError(f"{label}: najwyżej {limit} znaków.")
        fee = self.internalization_fee_pct
        if fee is not None and not (Decimal("0") <= fee <= Decimal("999.99")):
            raise ValueError("Opłata za internalizację: od 0 do 999,99%.")
        return self


class ClientContractTermsResponse(ClientContractTermsBase):
    id: int
    client_id: int
    updated_by: Optional[int] = None
    updated_by_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
