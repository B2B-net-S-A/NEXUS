"""Oznaczenie publikacji ogłoszenia na portalu — 0431.

Kolumny i powód istnienia: ``app/services/job_ad_publication_schema.py``.
Logika: ``app/services/job_ad/publications.py``, trasy: ``app/api/job_ads.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class JobAdPublication(Base, TimestampMixin):
    __tablename__ = "job_ad_publications"
    __table_args__ = (
        CheckConstraint(
            "portal IN ('pracuj', 'jjit')", name="ck_job_ad_publications_portal"
        ),
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    portal: Mapped[str] = mapped_column(String(16), primary_key=True)
    url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    # Odcisk treści ogłoszenia z chwili oznaczenia; inny niż bieżący =
    # „do aktualizacji”.
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Zdjęte z portalu — wiersz zostaje jako ślad.
    removed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    removed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
