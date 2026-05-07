"""Append-only audit log for Autenti webhook events.

Idempotency-by-DB: ``event_id`` is unique. Replays of the same webhook
payload (Autenti retries) become INSERT failures, caught by the handler
and converted into ``{"status": "duplicate"}`` responses (plan §4).

Each row stores the full decoded JWT payload for forensics — stale
notifications, missed transitions, and out-of-order delivery are
debuggable from this table alone.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DocumentSignatureEvent(Base):
    """One Autenti webhook event tied to a ``document_signatures`` row."""

    __tablename__ = "document_signature_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    signature_id: Mapped[int] = mapped_column(
        ForeignKey("document_signatures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Idempotency key ────────────────────────────────────────────────────
    # Autenti includes a unique ``jti`` / event identifier in every webhook.
    # Unique constraint at DB level guarantees insert-time deduplication.
    event_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)

    # ── Categorization ─────────────────────────────────────────────────────
    # Free-form string from Autenti (``SIGNING_PROCESS_COMPLETED``,
    # ``DOCUMENT_PROCESS_REJECTED``, etc.) — kept open-ended so new types
    # don't require a migration.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Optional ``status`` field present in some payloads (``COMPLETED``,
    # ``DOCUMENT_PROCESS_WITHDRAWN``, …). Nullable.
    status: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    # ── Forensics ──────────────────────────────────────────────────────────
    # Full decoded JWT payload (post-verification). JSONB so we can later
    # query ``payload->>'process_id'`` etc. without joins.
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="NOW()",
    )
    # NULL until the handler ran cleanly (so a crash mid-handler is
    # detectable; replay logic can re-run on processed_at IS NULL rows).
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # ── Relationships ──────────────────────────────────────────────────────
    signature = relationship("DocumentSignature", back_populates="events")

    def __repr__(self) -> str:
        return (
            f"<DocumentSignatureEvent id={self.id} sig={self.signature_id} "
            f"type={self.event_type} processed={self.processed_at is not None}>"
        )
