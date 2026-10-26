"""Wypełniony formularz CV klienta pary osoba × rekrutacja — 0522.

Kolumny i powód istnienia: ``app/services/client_form_schema.py``.
Wypełnianie: ``app/services/client_form_fill.py``, plik:
``app/services/client_form_render.py``, trasy: ``app/api/client_forms.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateClientForm(Base, TimestampMixin):
    __tablename__ = "candidate_client_forms"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "job_id", name="uq_candidate_client_forms_pair"
        ),
        Index("ix_candidate_client_forms_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    job_file_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("job_files.id", ondelete="SET NULL"), nullable=True
    )
    template_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    fields: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    extra_rows: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    missing_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default=text("0")
    )
    model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    filled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
