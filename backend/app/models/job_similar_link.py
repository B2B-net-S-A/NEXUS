"""Podobne rekrutacje (migracja 0341).

Wiersz jest kierunkowy — ``job_id`` przyjmuje przepięcia z ``similar_job_id`` —
ale ``services/job_similarity.link_jobs`` zakłada zawsze oba kierunki naraz,
bo podobieństwo requestu jest symetryczne. Osoby wysłane do klienta w jednej
rekrutacji trafiają do „Do przejrzenia" drugiej jako propozycja ``reassign``.

Bliźniak (0615, 28.10.2026) to ten sam wiersz z ``kind = 'twin'``: osoba
przechodzi na „Zweryfikowany” po screeningu pod oba bliźniaki naraz.
``question_pairs`` z perspektywy wiersza: ``[{"own": "q3", "other": "q1"}]``
— ``own`` to pytanie ``job_id``, ``other`` — ``similar_job_id``; wiersz
lustrzany ma pary odwrócone.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
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


class JobSimilarLink(Base):
    __tablename__ = "job_similar_links"
    __table_args__ = (
        UniqueConstraint("job_id", "similar_job_id", name="uq_job_similar_links_pair"),
        CheckConstraint(
            "job_id <> similar_job_id", name="ck_job_similar_links_not_self"
        ),
        Index("ix_job_similar_links_similar_job_id", "similar_job_id"),
        CheckConstraint(
            "kind IN ('similar', 'twin')", name="ck_job_similar_links_kind"
        ),
        Index(
            "ix_job_similar_links_twins",
            "job_id",
            postgresql_where=text("kind = 'twin'"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    similar_job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="similar", server_default="similar"
    )
    question_pairs: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSONB, nullable=True
    )


class JobTwinDismissal(Base):
    """Para otwartych rekrutacji, którą HoR albo admin oznaczył „To nie bliźniak”.

    Para nieuporządkowana zapisana jako (mniejszy id, większy id)."""

    __tablename__ = "job_twin_dismissals"
    __table_args__ = (
        UniqueConstraint(
            "job_low_id", "job_high_id", name="uq_job_twin_dismissals_pair"
        ),
        CheckConstraint(
            "job_low_id < job_high_id", name="ck_job_twin_dismissals_order"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    job_low_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    job_high_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    dismissed_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
