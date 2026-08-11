"""Normalized, auditable language facts for candidate profiles."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateLanguage(Base, TimestampMixin):
    """One normalized language fact, including soft-deleted history.

    ``candidate_id`` + ``language_code`` is unique even after tombstoning. A
    later full-list PUT reactivates the same row instead of creating parallel
    facts for one language. ``version`` is the row-level audit version; the
    candidate's ``languages_version`` is the collection-level OCC token.
    """

    __tablename__ = "candidate_languages"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "language_code",
            name="uq_candidate_languages_candidate_code",
        ),
        CheckConstraint(
            "language_code ~ '^[a-z][a-z0-9-]{1,15}$'",
            name="ck_candidate_languages_code",
        ),
        CheckConstraint(
            "cefr_level IS NULL OR cefr_level IN ('A1', 'A2', 'B1', 'B2', 'C1', 'C2')",
            name="ck_candidate_languages_cefr",
        ),
        CheckConstraint(
            """
            (is_native IS TRUE AND is_level_unknown IS FALSE AND cefr_level IS NULL)
            OR
            (is_native IS FALSE AND is_level_unknown IS TRUE AND cefr_level IS NULL)
            OR
            (is_native IS FALSE AND is_level_unknown IS FALSE AND cefr_level IS NOT NULL)
            """,
            name="ck_candidate_languages_proficiency_state",
        ),
        CheckConstraint(
            """
            provenance IN (
                'manual', 'cv', 'traffit', 'talent_radar', 'tr_legacy',
                'csv', 'legacy', 'unknown'
            )
            """,
            name="ck_candidate_languages_provenance",
        ),
        CheckConstraint("version > 0", name="ck_candidate_languages_version_positive"),
        Index(
            "ix_candidate_languages_candidate_active",
            "candidate_id",
            "language_code",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    language_code: Mapped[str] = mapped_column(String(16), nullable=False)
    language_name: Mapped[str] = mapped_column(String(100), nullable=False)
    cefr_level: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    is_native: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    is_level_unknown: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    provenance: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="unknown",
        server_default="unknown",
    )
    manual_lock: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="false",
    )
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    candidate = relationship("Candidate", back_populates="language_facts")
