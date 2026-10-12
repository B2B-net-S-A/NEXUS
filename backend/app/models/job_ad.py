"""Ogłoszenie rekrutacji do wklejenia na portale — 0430.

Kolumny i powód istnienia: ``app/services/job_ad_schema.py``.
Logika: ``app/services/job_ad/``, trasy: ``app/api/job_ads.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class JobAd(Base, TimestampMixin):
    __tablename__ = "job_ads"
    __table_args__ = (
        CheckConstraint("lang IN ('pl', 'en')", name="ck_job_ads_lang"),
        CheckConstraint("source IN ('ai', 'template')", name="ck_job_ads_source"),
    )

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    lang: Mapped[str] = mapped_column(
        String(2), nullable=False, default="pl", server_default=text("'pl'")
    )
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    tech: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    # „template” = model był niedostępny, treść złożona z pól rekrutacji.
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ai", server_default=text("'ai'")
    )
    material_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    generated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
