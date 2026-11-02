"""Panel klienta pod linkiem z CV (0629) — ``services/client_panel_schema.py``."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientPanel(Base):
    __tablename__ = "client_panels"
    __table_args__ = (
        UniqueConstraint("job_id", name="uq_client_panels_job"),
        Index(
            "uq_client_panels_token",
            "token_sha256",
            unique=True,
            postgresql_where=text("token_sha256 IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    show_rate: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    show_other_candidates: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    allow_actions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Token liczy się z sekretu aplikacji i tej wartości, w bazie jest tylko
    # jego skrót. Zmiana wartości = „Odwołaj link”.
    token_nonce: Mapped[Optional[str]] = mapped_column(String(32))
    token_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ClientPanelCandidate(Base):
    __tablename__ = "client_panel_candidates"
    __table_args__ = (
        UniqueConstraint(
            "panel_id", "candidate_id", name="uq_client_panel_candidates_pair"
        ),
        UniqueConstraint("public_id", name="uq_client_panel_candidates_public"),
        Index("ix_client_panel_candidates_candidate", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    panel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("client_panels.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    public_id: Mapped[str] = mapped_column(String(16), nullable=False)
    hidden: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    rejected_evidence: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    shared_document_ids: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ClientPanelRequest(Base):
    __tablename__ = "client_panel_requests"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('question', 'interview', 'not_fit', 'requirements_change')",
            name="ck_client_panel_requests_kind",
        ),
        CheckConstraint(
            "status IN ('open', 'answered', 'closed')",
            name="ck_client_panel_requests_status",
        ),
        Index("ix_client_panel_requests_panel_created", "panel_id", "created_at"),
        Index("ix_client_panel_requests_job_status", "job_id", "status"),
        Index("ix_client_panel_requests_candidate", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    panel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("client_panels.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE")
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    # Imię i adres wpisane przez autora, niezweryfikowane.
    author_name: Mapped[str] = mapped_column(String(120), nullable=False)
    author_email: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[Optional[str]] = mapped_column(String(2000))
    reasons: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    slot_request_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("client_interview_slot_requests.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="open", server_default="open"
    )
    answer: Mapped[Optional[str]] = mapped_column(String(4000))
    answered_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClientPanelView(Base):
    __tablename__ = "client_panel_views"
    __table_args__ = (
        CheckConstraint(
            "action IN ('open', 'candidate', 'requirement', 'tab', 'file')",
            name="ck_client_panel_views_action",
        ),
        Index("ix_client_panel_views_panel_created", "panel_id", "created_at"),
        Index("ix_client_panel_views_created", "created_at"),
        Index("ix_client_panel_views_candidate", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    panel_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("client_panels.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE")
    )
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(String(120))
    # SHA-256 z IP i soli dnia; surowe IP nie trafia do bazy.
    ip_hash: Mapped[Optional[str]] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
