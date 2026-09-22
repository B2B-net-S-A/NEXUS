"""Podobne rekrutacje (migracja 0341).

Wiersz jest kierunkowy — ``job_id`` przyjmuje przepięcia z ``similar_job_id`` —
ale ``services/job_similarity.link_jobs`` zakłada zawsze oba kierunki naraz,
bo podobieństwo requestu jest symetryczne. Osoby wysłane do klienta w jednej
rekrutacji trafiają do „Do przejrzenia" drugiej jako propozycja ``reassign``.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    UniqueConstraint,
    func,
)
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
