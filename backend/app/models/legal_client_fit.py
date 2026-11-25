"""Zgodność umów B2B z umową ramową klienta (0791).

CHECK-i i indeksy jak w ``app/services/legal_client_fit/schema.py`` (strażnik
dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services.legal_client_fit import schema


class LegalClientFitCheck(Base):
    """Stan ostatniego sprawdzenia umów B2B klienta z jego umową ramową."""

    __tablename__ = "legal_client_fit_checks"
    __table_args__ = (
        UniqueConstraint("client_id", name="uq_legal_client_fit_checks_client"),
        CheckConstraint(schema.CK_STATUS, name="ck_legal_client_fit_checks_status"),
        CheckConstraint(schema.CK_TRIGGER, name="ck_legal_client_fit_checks_trigger"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    status_message: Mapped[Optional[str]] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(String(16), nullable=False)
    requested_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    #: Odcisk umów, aneksów i wzoru, z których powstały ustalenia.
    source_fingerprint: Mapped[Optional[str]] = mapped_column(String(64))
    template_label: Mapped[Optional[str]] = mapped_column(String(schema.LABEL_MAX))
    model: Mapped[Optional[str]] = mapped_column(String(schema.MODEL_MAX))
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    checked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class LegalClientFitFinding(Base):
    """Ustalenie jednego tematu: wymóg klienta ↔ nasz wzór umowy B2B."""

    __tablename__ = "legal_client_fit_findings"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "topic", name="uq_legal_client_fit_findings_topic"
        ),
        CheckConstraint(schema.CK_STATE, name="ck_legal_client_fit_findings_state"),
        CheckConstraint(
            schema.CK_SOURCE_KIND, name="ck_legal_client_fit_findings_source_kind"
        ),
        CheckConstraint(
            schema.CK_OUR_SIDE, name="ck_legal_client_fit_findings_our_side"
        ),
        CheckConstraint(
            schema.CK_OUR_PAIR, name="ck_legal_client_fit_findings_our_pair"
        ),
        CheckConstraint(schema.CK_LAWYER, name="ck_legal_client_fit_findings_lawyer"),
        Index("ix_legal_client_fit_findings_state", "state", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    topic: Mapped[str] = mapped_column(String(schema.TOPIC_MAX), nullable=False)
    state: Mapped[str] = mapped_column(String(8), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    client_quote: Mapped[str] = mapped_column(Text, nullable=False)
    client_ref: Mapped[str] = mapped_column(
        String(schema.CLIENT_REF_MAX), nullable=False
    )
    client_source_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    client_source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    our_quote: Mapped[Optional[str]] = mapped_column(Text)
    our_ref: Mapped[Optional[str]] = mapped_column(String(schema.OUR_REF_MAX))
    next_step: Mapped[Optional[str]] = mapped_column(Text)
    annex_text: Mapped[Optional[str]] = mapped_column(Text)
    lawyer_review: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=sql_text("'[]'::jsonb")
    )
    clause_draft_text: Mapped[Optional[str]] = mapped_column(Text)
    clause_draft_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    clause_draft_requested_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
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
