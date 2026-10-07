"""Wersja formularza screeningu pary (kandydat, rekrutacja) — 0424.

Opis kolumn i słowników: ``app/services/screening_form_schema.py``. Reguły:
``app/services/screening_form.py`` (zapis) i ``screening_form_rules.py``
(migawka, różnice). Tabelę czytają wyłącznie ludzie — żaden model AI.
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScreeningFormVersion(Base):
    __tablename__ = "screening_form_versions"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "job_id",
            "version_no",
            name="uq_screening_form_versions_pair_no",
        ),
        Index("ix_screening_form_versions_job", "job_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    process_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_processes.id", ondelete="SET NULL")
    )
    stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="SET NULL")
    )
    note_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("notes.id", ondelete="SET NULL")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    attempt_no: Mapped[Optional[int]] = mapped_column(Integer)
    # baseline | external | save | restore | undo | fix_requested (CHECK).
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    # form | note_import (CHECK).
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="form", server_default="form"
    )
    restored_from_version: Mapped[Optional[int]] = mapped_column(Integer)
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    changes: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    meta: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
