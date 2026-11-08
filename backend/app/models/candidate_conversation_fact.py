"""Rejestr faktów z rozmów (0668) — DDL w ``services/conversation_facts_schema.py``."""

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CandidateConversationFact(Base):
    __tablename__ = "candidate_conversation_facts"
    __table_args__ = (
        Index("ix_candidate_conversation_facts_candidate", "candidate_id"),
        Index(
            "ux_candidate_conversation_facts_sheet",
            "candidate_id",
            "job_id",
            "kind",
            "value_key",
            unique=True,
            postgresql_where=text("source = 'sheet' AND retired_at IS NULL"),
        ),
        Index(
            "ux_candidate_conversation_facts_note",
            "candidate_id",
            "kind",
            "value_key",
            unique=True,
            postgresql_where=text("source = 'note_ai' AND retired_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    # skill | domain | certification | regulation
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_key: Mapped[str] = mapped_column(Text, nullable=False)
    # Nazwy ze słownika; puste = fakt liczy się tylko w swojej rekrutacji.
    canonical_terms: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    # confirmed | absent; `absent` wyłącznie ze źródła `sheet`.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # sheet | note_ai
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="SET NULL"), nullable=True
    )
    note_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    evidence: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # Dzień rozmowy, nie chwila zapisu wiersza: historia dostaje datę arkusza.
    noted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Bieg skryptu historii, po którym da się cofnąć zapis.
    batch: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    retired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
