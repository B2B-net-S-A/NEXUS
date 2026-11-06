"""Propozycje do słownika umiejętności (0658).

Jeden wiersz na rodzinę zapisów spoza słownika („excel”, „ms excel”,
„microsoft excel”). Liczy je co noc ``services/skill_proposals``, model
proponuje decyzję, a do słownika wchodzi dopiero to, co zatwierdzi Head of
Recruitment albo admin (D7: nic nie mapuje się samo).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class SkillProposal(Base):
    __tablename__ = "skill_proposals"
    __table_args__ = (
        UniqueConstraint("family_key", name="uq_skill_proposals_family_key"),
        CheckConstraint(
            "status IN ('open', 'accepted', 'rejected')",
            name="ck_skill_proposals_status",
        ),
        CheckConstraint(
            "decision IS NULL OR decision IN ('new', 'alias', 'generic', 'soft', 'noise')",
            name="ck_skill_proposals_decision",
        ),
        CheckConstraint(
            "confidence IS NULL OR confidence IN ('high', 'low')",
            name="ck_skill_proposals_confidence",
        ),
        Index("ix_skill_proposals_status_weight", "status", text("weight DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    family_key: Mapped[str] = mapped_column(String(200), nullable=False)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # [{"name": "ms excel", "count": 812, "cand": 721}] — count = profile + CV + wymagania.
    names: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    cand_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cv_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    job_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    decision: Mapped[Optional[str]] = mapped_column(String(10))
    canonical: Mapped[Optional[str]] = mapped_column(String(200))
    target_skill_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("skills.id", ondelete="SET NULL")
    )
    category: Mapped[Optional[str]] = mapped_column(String(64))
    replacements: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    confidence: Mapped[Optional[str]] = mapped_column(String(4))
    review_note: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="open", server_default="open"
    )
    model: Mapped[Optional[str]] = mapped_column(String(80))
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    classified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    curated_by: Mapped[Optional[str]] = mapped_column(String(255))
    curated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
