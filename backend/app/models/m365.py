"""Microsoft 365 integration models.

Three tables:
- m365_connections: one per user, holds encrypted OAuth tokens + delta cursors.
- emails: every message synced from Graph, linked to candidates when matched.
- email_attachments: files (CV, images) referenced by an email.

`calendar_events` is reused (existing table); the migration adds two extra
columns (`m365_series_master_id`, `m365_change_key`) — see migration file,
not modeled here because the ORM class already maps the full row.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class EmailDirection(str, enum.Enum):
    sent = "sent"
    received = "received"
    draft = "draft"


class EmailMatchMethod(str, enum.Enum):
    """How the email was linked to a candidate.

    `unmatched` is stored instead of NULL so the matcher can record that it
    looked at the message and decided against a link (prevents re-matching on
    every sync pass).
    """

    strict = "strict"
    smart_domain = "smart_domain"
    smart_thread = "smart_thread"
    smart_name = "smart_name"
    manual = "manual"
    unmatched = "unmatched"


class M365SyncStatus(str, enum.Enum):
    idle = "idle"
    running = "running"
    error = "error"
    # Tokens cannot be decrypted (e.g. M365_TOKEN_ENCRYPTION_KEY rotated).
    # Connection is unusable until user re-runs the OAuth flow.
    reconnect_required = "reconnect_required"


class M365Connection(Base, TimestampMixin):
    """Per-user OAuth2 connection to Microsoft 365.

    Unique on user_id — a single Nexus user maps to exactly one mailbox. If a
    user needs multiple mailboxes, they can disconnect/reconnect; shared
    mailboxes are a Phase 3 feature.
    """

    __tablename__ = "m365_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )

    # Actual tenant guid returned by Microsoft (not "common"). Useful for
    # multi-tenant audit and for future tenant-wide operations.
    tenant_id: Mapped[str] = mapped_column(String(100), nullable=False)
    # Primary SMTP / UPN of the mailbox we sync. Displayed in the UI.
    mailbox_upn: Mapped[str] = mapped_column(String(255), nullable=False)

    # Fernet-encrypted tokens. Never log, never return via API.
    access_token_ct: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token_ct: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    scopes_granted: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Opaque @odata.deltaLink strings — we pass them back verbatim.
    # `delta_token_messages` is deprecated (Phase 2.5): it was shared by both
    # Inbox and SentItems syncs so each folder kept overwriting the other's
    # cursor. Kept temporarily for rollback safety; new code reads/writes
    # `delta_token_inbox` and `delta_token_sent`.
    delta_token_messages: Mapped[Optional[str]] = mapped_column(Text)
    delta_token_inbox: Mapped[Optional[str]] = mapped_column(Text)
    delta_token_sent: Mapped[Optional[str]] = mapped_column(Text)
    delta_token_events: Mapped[Optional[str]] = mapped_column(Text)

    # Phase 2.2 — count successful refresh_tokens() calls. Used for anomaly
    # detection (>10/hr signals a refresh loop bug).
    refresh_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Phase 2.4 — track delta cursor invalidations. If >3 within 24h we stop
    # syncing this connection until manually intervened.
    delta_reset_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    delta_last_reset_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # Backfill high-water mark (oldest message date we've synced through).
    synced_through: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[M365SyncStatus] = mapped_column(
        Enum(M365SyncStatus, name="m365syncstatus"),
        default=M365SyncStatus.idle,
        nullable=False,
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    # NULL while initial 12-month backfill is running; set when done.
    backfill_completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # Soft-disconnect without row delete (preserves history).
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<M365Connection id={self.id} user_id={self.user_id} "
            f"upn={self.mailbox_upn} active={self.is_active}>"
        )


class Email(Base, TimestampMixin):
    """A message synced from Microsoft Graph.

    One row per unique m365_message_id. We store body (HTML + text) so the UI
    does not hit Graph on every open — acceptable because the mailbox owner
    already consented to local persistence by connecting.
    """

    __tablename__ = "emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Owner of the mailbox this message came from.
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Link to candidate — nullable for unmatched messages.
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Graph IDs. `m365_message_id` is the immutable Graph id; the RFC-level
    # `internetMessageId` is kept as a secondary identity for cross-account
    # threading and manual rematching.
    m365_message_id: Mapped[str] = mapped_column(
        String(255), nullable=False, unique=True, index=True
    )
    m365_internet_message_id: Mapped[Optional[str]] = mapped_column(
        String(998), nullable=True, index=True
    )
    m365_conversation_id: Mapped[str] = mapped_column(
        String(255), nullable=False, index=True
    )

    subject: Mapped[Optional[str]] = mapped_column(String(998))
    from_address: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    from_name: Mapped[Optional[str]] = mapped_column(String(255))
    # Shape: [{"address": str, "name": str?}, ...]
    to_addresses: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)
    cc_addresses: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Body is server-side sanitized (bleach) before insert; FE does a second
    # pass via DOMPurify on render.
    body_html: Mapped[Optional[str]] = mapped_column(Text)
    body_text: Mapped[Optional[str]] = mapped_column(Text)
    body_preview: Mapped[Optional[str]] = mapped_column(String(255))

    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )

    direction: Mapped[EmailDirection] = mapped_column(
        Enum(EmailDirection, name="emaildirection"),
        default=EmailDirection.received,
        nullable=False,
    )
    has_attachments: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # True when Outlook category `M365_IGNORE_CATEGORY` is present; body/attachments
    # are NOT fetched for these (privacy opt-out) but the stub exists so we don't
    # re-fetch on every delta.
    is_private_filtered: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    match_method: Mapped[EmailMatchMethod] = mapped_column(
        Enum(EmailMatchMethod, name="emailmatchmethod"),
        default=EmailMatchMethod.unmatched,
        nullable=False,
    )
    match_confidence: Mapped[Optional[float]] = mapped_column(Float)
    matched_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    matched_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Verbatim Graph `categories` array — useful downstream for richer filters.
    raw_categories: Mapped[Optional[dict]] = mapped_column(JSONB, default=list)

    # Phase 2.6 — idempotency key for outbound sends (sender.send_new).
    # Format: sha256(user_id|sorted_recipients|subject|minute_bucket). NULL for
    # messages synced from Graph (matched on m365_message_id instead). A unique
    # partial index in migration 0102 enforces uniqueness only on NOT NULL.
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(128))

    # Phase 4.4 — postgres FTS column. Generated STORED in migration 0103 from
    # subject (weight A) + from_name/from_address (B) + body_text (C).
    # `Computed(..., persisted=True)` tells SQLAlchemy the column is DB-managed
    # so INSERT/UPDATE skip it; queries read it via the GIN index
    # ``ix_emails_search_vector``.
    search_vector: Mapped[Optional[str]] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('simple', coalesce(subject, '')), 'A') || "
            "setweight(to_tsvector('simple', "
            "coalesce(from_name, '') || ' ' || coalesce(from_address, '')), 'B') || "
            "setweight(to_tsvector('simple', coalesce(body_text, '')), 'C')",
            persisted=True,
        ),
        nullable=True,
    )

    # Relationships
    user = relationship("User", foreign_keys=[user_id])
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    attachments = relationship(
        "EmailAttachment",
        back_populates="email",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_emails_candidate_received", "candidate_id", "received_at"),
        Index("ix_emails_user_conversation", "user_id", "m365_conversation_id"),
        Index("ix_emails_user_received", "user_id", "received_at"),
    )

    def __repr__(self) -> str:
        return (
            f"<Email id={self.id} user={self.user_id} from={self.from_address} "
            f"subject={self.subject!r} match={self.match_method}>"
        )


class EmailAttachment(Base, TimestampMixin):
    """File (or inline image) referenced by a single Email.

    Files are stored on local filesystem under `UPLOAD_DIR/microsoft365/...` —
    see `app.services.m365.attachment_handler`.
    """

    __tablename__ = "email_attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    email_id: Mapped[int] = mapped_column(
        ForeignKey("emails.id", ondelete="CASCADE"), nullable=False, index=True
    )

    m365_attachment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_inline: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Relative path under STORAGE_ROOT — NULL if download was skipped (size cap).
    storage_path: Mapped[Optional[str]] = mapped_column(String(1000))
    # Set after download; used to dedupe across multiple emails (same CV attached
    # to reply chain = 1 physical file).
    sha256: Mapped[Optional[str]] = mapped_column(String(64), index=True)

    # CV pipeline integration.
    is_cv_candidate: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    cv_parse_attempted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    parsed_candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    parse_error: Mapped[Optional[str]] = mapped_column(Text)

    email = relationship("Email", back_populates="attachments")
    parsed_candidate = relationship("Candidate", foreign_keys=[parsed_candidate_id])

    def __repr__(self) -> str:
        return (
            f"<EmailAttachment id={self.id} email={self.email_id} "
            f"name={self.filename!r} cv={self.is_cv_candidate}>"
        )
