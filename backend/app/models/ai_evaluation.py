"""Blind, reference-only AI evaluation data model."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIEvalSet(Base):
    __tablename__ = "ai_eval_sets"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    feature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIEvalCase(Base):
    """A reference to source data; CV text is never copied into this table."""

    __tablename__ = "ai_eval_cases"
    __table_args__ = (
        UniqueConstraint(
            "eval_set_id", "candidate_id", "source_ref", name="uq_ai_eval_case_ref"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    eval_set_id: Mapped[int] = mapped_column(
        ForeignKey("ai_eval_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_ref: Mapped[str] = mapped_column(
        String(128), nullable=False, default="candidate.raw_cv_text"
    )
    slice_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIEvalRun(Base):
    __tablename__ = "ai_eval_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    eval_set_id: Mapped[int] = mapped_column(
        ForeignKey("ai_eval_sets.id", ondelete="CASCADE"), nullable=False, index=True
    )
    feature: Mapped[str] = mapped_column(String(64), nullable=False)
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default="offline")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    champion_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    champion_model: Mapped[str] = mapped_column(String(128), nullable=False)
    challenger_provider: Mapped[str] = mapped_column(String(32), nullable=False)
    challenger_model: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIEvalLabel(Base):
    """A nullable label row doubles as an explicit reviewer assignment."""

    __tablename__ = "ai_eval_labels"
    __table_args__ = (
        UniqueConstraint(
            "run_id", "case_id", "reviewer_id", name="uq_ai_eval_reviewer_case"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[int] = mapped_column(
        ForeignKey("ai_eval_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reviewer_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    preferred_variant: Mapped[Optional[str]] = mapped_column(String(1), nullable=True)
    rating_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rating_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIEvalOutput(Base):
    """Short-lived AES-256-GCM ciphertext; never plaintext or prompts."""

    __tablename__ = "ai_eval_outputs"
    __table_args__ = (
        UniqueConstraint("run_id", "case_id", "variant", name="uq_ai_eval_output"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_eval_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    case_id: Mapped[int] = mapped_column(
        ForeignKey("ai_eval_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    variant: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    output_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    deterministic_metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
