"""Karta rekomendacji pary (kandydat, rekrutacja) — 0413.

Opis kolumn: ``app/services/recommendation_card_schema.py``. Reguły składania
karty: ``app/services/recommendation_cards.py``.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import ForeignKey, Index, Integer, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class RecommendationCard(Base, TimestampMixin):
    __tablename__ = "recommendation_cards"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_recommendation_cards_pair"),
        Index("ix_recommendation_cards_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    fields_notes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    fields_manual: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    note_answers: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
