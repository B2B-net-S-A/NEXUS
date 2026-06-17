"""Document signature — one row per Autenti document_process lifecycle.

A contract may produce multiple ``document_signatures`` rows over time
(re-send after rejection, re-send after withdrawal). Phase 1 ships the
single-signer flow (candidate-only); Phase 6 will add a child
``document_signature_signers`` table for multi-party.

Status transitions managed by :mod:`app.services.autenti.webhook_handler`
(Phase 3) and :mod:`app.services.autenti.sender` (Phase 2). The state
machine is documented in plan §4 ("Inbound webhook flow").
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from typing import Any

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class SignatureStatus(str, enum.Enum):
    """Lifecycle of an Autenti document process from our point of view.

    ``draft`` — row created, no API call yet (transient, <1s).
    ``sending`` — background task in flight (HTML→PDF→upload→send).
    ``sent`` — Autenti accepted; signers were notified by email.
    ``in_progress`` — at least one signer acted (review/approve).
    ``completed`` — every required signer signed.
    ``rejected`` — a signer declined.
    ``withdrawn`` — sender withdrew the process.
    ``failed`` — API/network error after retries; ``last_error`` populated.
    ``expired`` — Autenti deadline elapsed without completion.
    """

    draft = "draft"
    sending = "sending"
    sent = "sent"
    in_progress = "in_progress"
    completed = "completed"
    rejected = "rejected"
    withdrawn = "withdrawn"
    failed = "failed"
    expired = "expired"


class DocumentSignature(Base, TimestampMixin):
    """One Autenti document_process keyed to a NEXUS contract."""

    __tablename__ = "document_signatures"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Linkage to NEXUS domain ────────────────────────────────────────────
    # Exactly one of (contract_id, client_framework_contract_id,
    # client_contract_amendment_id) must be set — enforced by DB CHECK
    # constraint `chk_signature_target_xor` (migracja 0091).
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    client_framework_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    client_contract_amendment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_contract_amendments.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    # The unsigned HTML snapshot persisted by /draft/finalize. Required so
    # we always know which exact snapshot was sent (contract draft can
    # change after sending if the recruiter resends).
    # Nullable when target is client framework contract / amendment (PDF
    # uploaded directly, no HTML snapshot).
    contract_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contract_documents.id", ondelete="RESTRICT"),
        nullable=True,
    )

    # ── Provider linkage (provider-agnostic — Faza 1, migracja 0133) ───────
    # ``provider`` discriminates which signing backend owns this row:
    #   ``autenti``        — legacy aggregator (deprecated, historical rows)
    #   ``szafir_sdk``     — KIR Szafir SDK, client-side card/token/mobile
    #   ``mszafir_oneshot``— KIR mSzafir One Shot, cloud one-time cert
    #   ``upload_validate``— Option B: signer uploads own-signed PAdES
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="autenti", server_default="autenti"
    )
    # Provider-side reference (Autenti process_id / mSzafir process ref / …).
    # Renamed from ``autenti_process_id`` in 0133 — UNIQUE constraint follows
    # the column in PG. NULL while ``status == draft`` (brief window).
    provider_ref: Mapped[Optional[str]] = mapped_column(
        String(64), unique=True, nullable=True
    )
    # Signature level per eIDAS — SES / AdES / QES. Free-form String(16)
    # (NOT enum) so adding levels never needs ``ALTER TYPE``. For the in-house
    # QES rail this is always ``QES``. Renamed from ``autenti_signature_type``.
    signature_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="SES", server_default="SES"
    )
    # mSzafir cloud signing-session id (pas 2). NULL for Szafir SDK / upload.
    signing_session_id: Mapped[Optional[str]] = mapped_column(
        String(255), nullable=True
    )
    # How the signer was identified: ``card`` | ``mobile`` | ``bank`` |
    # ``mobywatel`` | ``edowod_nfc``. Captured for audit; raw identity data
    # stays with the QTSP (RODO).
    identity_provider: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Achieved PAdES level reported by validation: ``B-B`` | ``B-T`` |
    # ``B-LT`` | ``B-LTA``. NULL until first validation.
    signature_level: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # EU DSS / pyHanko validation report ("is this QES?"). Durable evidence.
    validation_report: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )

    # ── Backward-compat aliases (deprecated — remove after FE migration) ────
    # Existing Autenti code (sender/webhook_handler) reads & writes the old
    # attribute names. Property+setter aliases keep it working unchanged while
    # the column is renamed underneath.
    @property
    def autenti_process_id(self) -> Optional[str]:
        return self.provider_ref

    @autenti_process_id.setter
    def autenti_process_id(self, value: Optional[str]) -> None:
        self.provider_ref = value

    @property
    def autenti_signature_type(self) -> str:
        return self.signature_type

    @autenti_signature_type.setter
    def autenti_signature_type(self, value: str) -> None:
        self.signature_type = value

    # ── State machine ──────────────────────────────────────────────────────
    status: Mapped[SignatureStatus] = mapped_column(
        Enum(SignatureStatus, name="signaturestatus"),
        nullable=False,
        default=SignatureStatus.draft,
        index=True,
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Sender (NEXUS user who clicked "Send") ─────────────────────────────
    # NEVER NULL — audit trail anchor. Independent of who sent on the
    # Autenti side (which may be the org for ``bpa`` scope).
    sender_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    # ── Signer snapshot (denormalized) ─────────────────────────────────────
    # Candidate JDG fields can change after we send — keep a frozen copy
    # so ``GET /signatures/{id}`` always shows what was sent, not what
    # the candidate currently has.
    signer_email: Mapped[str] = mapped_column(String(255), nullable=False)
    signer_first_name: Mapped[str] = mapped_column(String(120), nullable=False)
    signer_last_name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Mandatory for AdES (SMS verification). Optional for SES/QES.
    signer_phone: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)

    # ── Output ─────────────────────────────────────────────────────────────
    # Pointer to the signed PDF stored locally via storage_service. NULL
    # until ``SIGNING_PROCESS_COMPLETED`` webhook fires AND download
    # succeeds (sweeper retries on download fail).
    signed_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contract_documents.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Optional hosted URL inside Autenti's vault — fallback when our local
    # download fails. The recruiter can always click through to Autenti.
    signed_document_url: Mapped[Optional[str]] = mapped_column(
        String(1000), nullable=True
    )

    # ── Audit ──────────────────────────────────────────────────────────────
    # Free-form text describing the last failure (if any). Surfaced to the
    # UI so recruiters see actionable error messages.
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )

    # ── Relationships ──────────────────────────────────────────────────────
    contract = relationship("Contract", foreign_keys=[contract_id])
    client_framework_contract = relationship(
        "ClientFrameworkContract", foreign_keys=[client_framework_contract_id]
    )
    client_contract_amendment = relationship(
        "ClientContractAmendment", foreign_keys=[client_contract_amendment_id]
    )
    contract_document = relationship(
        "ContractDocument", foreign_keys=[contract_document_id]
    )
    signed_document = relationship(
        "ContractDocument", foreign_keys=[signed_document_id]
    )
    sender = relationship("User", foreign_keys=[sender_user_id])
    events = relationship(
        "DocumentSignatureEvent",
        back_populates="signature",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DocumentSignatureEvent.received_at.asc()",
    )

    @property
    def target_kind(self) -> str:
        """Discriminator dla UI/logu: ``contract`` / ``framework`` / ``amendment``."""
        if self.contract_id is not None:
            return "contract"
        if self.client_framework_contract_id is not None:
            return "framework"
        if self.client_contract_amendment_id is not None:
            return "amendment"
        return "unknown"

    def __repr__(self) -> str:
        target = (
            f"contract={self.contract_id}"
            if self.contract_id
            else (
                f"framework={self.client_framework_contract_id}"
                if self.client_framework_contract_id
                else f"amendment={self.client_contract_amendment_id}"
            )
        )
        return (
            f"<DocumentSignature id={self.id} {target} "
            f"provider={self.provider} ref={self.provider_ref} "
            f"status={self.status.value}>"
        )
