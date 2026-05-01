"""Pydantic schemas for required documents (templates + per-client instances).

Templates są globalnymi szablonami (NDA, RODO, off-limits, payment terms),
instancje per-klient mają plik, status i metadata uploadu.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.client_required_document import ClientDocStatus


# ── Templates ────────────────────────────────────────────────────────────────


class RequiredDocumentTemplateBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_default: bool = True
    sort_order: int = 0


class RequiredDocumentTemplateCreate(RequiredDocumentTemplateBase):
    pass


class RequiredDocumentTemplatePatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_default: Optional[bool] = None
    sort_order: Optional[int] = None


class RequiredDocumentTemplateResponse(RequiredDocumentTemplateBase):
    id: int
    created_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Per-client instances ─────────────────────────────────────────────────────


class ClientRequiredDocumentBase(BaseModel):
    name: str
    description: Optional[str] = None
    is_mandatory: bool = True
    notes: Optional[str] = None


class ClientRequiredDocumentCreate(ClientRequiredDocumentBase):
    template_id: Optional[int] = None  # None = ad-hoc, value = derived from template


class ClientRequiredDocumentPatch(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_mandatory: Optional[bool] = None
    status: Optional[ClientDocStatus] = None
    notes: Optional[str] = None


class ApplyTemplatesRequest(BaseModel):
    """Bulk-utworzenie instancji z szablonów. None = wszystkie is_default=true."""

    template_ids: Optional[list[int]] = None


class ClientRequiredDocumentResponse(ClientRequiredDocumentBase):
    id: int
    client_id: int
    template_id: Optional[int] = None
    status: ClientDocStatus

    filename: Optional[str] = None
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None

    uploaded_by: Optional[int] = None
    uploaded_by_email: Optional[str] = None
    uploaded_at: Optional[datetime] = None

    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
