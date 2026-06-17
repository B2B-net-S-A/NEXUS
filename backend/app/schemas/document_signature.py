"""Pydantic schemas for the Autenti signature flow.

Request schemas mirror the API contracts in plan §4. Response schemas
shape what the FE renders in the envelope card / timeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.models.document_signature import SignatureStatus

SignatureType = Literal["SES", "AdES", "QES"]
# In-house QES rail providers (Faza 1, migracja 0133).
SigningProvider = Literal["szafir_sdk", "mszafir_oneshot", "upload_validate", "autenti"]


# ── Request bodies ─────────────────────────────────────────────────────────


class AutentiSendRequest(BaseModel):
    """``POST /api/autenti/contracts/{contract_id}/send`` body."""

    signature_type: SignatureType = "SES"
    expires_in_days: int = Field(default=14, ge=1, le=90)
    # Optional cover message shown to the signer in the Autenti email.
    # Defaults to a hardcoded PL string in :func:`sender._build_create_payload`
    # (Phase 2). Markdown not supported — Autenti renders as plain text.
    message_pl: Optional[str] = Field(default=None, max_length=2000)
    # Where to redirect the signer back after they finish. Defaults to
    # ``settings.PUBLIC_BASE_URL`` plus a "thanks" page when omitted.
    return_url: Optional[str] = Field(default=None, max_length=1000)


class SignForSignatureRequest(BaseModel):
    """``POST /api/signing/contracts/{contract_id}/send-for-signature`` body.

    In-house QES rail (Faza 2+). Defaults to QES via the Szafir SDK pas;
    the consultant may fall back to mSzafir One Shot on the signing page.
    """

    signature_type: SignatureType = "QES"
    provider: Literal["szafir_sdk", "mszafir_oneshot", "upload_validate"] = "szafir_sdk"
    expires_in_days: int = Field(default=14, ge=1, le=90)
    # Imienny reprezentant spółki podpisujący stronę B2B Network (kartą przez
    # Szafir). ``None`` = strona firmy nieuruchamiana w tym wywołaniu.
    company_signer_user_id: Optional[int] = None
    # Optional Polish cover message shown to the signer in the e-mail.
    message_pl: Optional[str] = Field(default=None, max_length=2000)


class SignForSignatureResponse(BaseModel):
    """``POST /api/signing/contracts/{id}/send-for-signature`` → 202.

    Returns the shareable public signing link synchronously so the recruiter
    can hand it to the consultant immediately.
    """

    signature_id: int
    contract_id: int
    status: SignatureStatus
    sign_url: str


# ── Response shapes ────────────────────────────────────────────────────────


class AutentiSendResponse(BaseModel):
    """``POST /send`` returns 202 Accepted with the new row's id."""

    signature_id: int
    contract_id: int
    status: SignatureStatus


class DocumentSignatureEventResponse(BaseModel):
    """One row from the ``document_signature_events`` table."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    event_id: str
    event_type: str
    status: Optional[str] = None
    received_at: datetime
    processed_at: Optional[datetime] = None
    # ``payload`` is intentionally NOT included by default — it's verbose
    # and may contain PII. The detail endpoint can opt-in to a richer view
    # (Phase 3 will introduce ``include_payload=True`` query param).


class DocumentSignatureResponse(BaseModel):
    """Single row + denormalized signer + sender label for UI rendering."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    contract_id: Optional[int] = None
    contract_document_id: Optional[int] = None
    # Provider-agnostic fields (Faza 1, migracja 0133).
    provider: str = "autenti"
    provider_ref: Optional[str] = None
    signature_type: str
    signing_session_id: Optional[str] = None
    identity_provider: Optional[str] = None
    signature_level: Optional[str] = None
    validation_report: Optional[dict[str, Any]] = None
    status: SignatureStatus
    sent_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    sender_user_id: int
    signer_email: str
    signer_first_name: str
    signer_last_name: str
    signer_phone: Optional[str] = None
    signed_document_id: Optional[int] = None
    signed_document_url: Optional[str] = None
    last_error: Optional[str] = None
    retry_count: int
    created_at: datetime
    updated_at: datetime

    # ── Backward-compat aliases (deprecated — drop after FE migration) ──────
    # Existing FE (`autentiApi`) reads ``autenti_process_id`` /
    # ``autenti_signature_type``. Expose them as computed fields mapped onto
    # the renamed columns so nothing breaks before the FE swaps to the new
    # ``provider_ref`` / ``signature_type`` names.
    @computed_field  # type: ignore[prop-decorator]
    @property
    def autenti_process_id(self) -> Optional[str]:
        return self.provider_ref

    @computed_field  # type: ignore[prop-decorator]
    @property
    def autenti_signature_type(self) -> str:
        return self.signature_type


class DocumentSignatureDetailResponse(DocumentSignatureResponse):
    """Detail endpoint adds the timeline of events."""

    events: list[DocumentSignatureEventResponse] = Field(default_factory=list)


# ── Webhook ────────────────────────────────────────────────────────────────


class AutentiWebhookResponse(BaseModel):
    """``POST /api/autenti/webhook`` always returns 200; signal via field.

    Phase 3 will populate this. Phase 1 ships the schema alongside the
    models so FE-shared TypeScript types can be generated early.
    """

    status: Literal["ok", "duplicate", "ignored"]


# ── Helpers ────────────────────────────────────────────────────────────────


def serialize_payload_safely(payload: dict[str, Any]) -> dict[str, Any]:
    """Strip large/binary fields before persisting to JSONB.

    Webhook payloads from Autenti can contain inline base64 attachments on
    some events. We don't need them — :class:`DocumentSignature` already
    references the full PDF via ``signed_document_id``. Truncating keeps
    the JSONB row a manageable size.
    """
    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, str) and len(value) > 8000:
            cleaned[key] = value[:8000] + "...[truncated]"
        else:
            cleaned[key] = value
    return cleaned
