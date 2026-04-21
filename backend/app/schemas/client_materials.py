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

from pydantic import BaseModel


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


class ClientContractTermsUpsert(ClientContractTermsBase):
    pass


class ClientContractTermsResponse(ClientContractTermsBase):
    id: int
    client_id: int
    updated_by: Optional[int] = None
    updated_by_email: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
