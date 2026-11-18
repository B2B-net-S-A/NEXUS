"""Bot Cpro: biegi rutyny „NEXUS Cpro” w Grok Bocie (0732).

CHECK-i i indeks jak w ``app/services/cpro_bot/schema.py`` (strażnik dryfu
schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services.cpro_bot import schema


class CproBotRun(Base):
    """Bieg bota Cpro: jednorazowy token, karty, zlecenie i wynik każdej karty."""

    __tablename__ = "cpro_bot_runs"
    __table_args__ = (
        CheckConstraint(schema.CK_RUN_STATUS, name="ck_cpro_bot_runs_status"),
        CheckConstraint(schema.CK_STAGE_IDS, name="ck_cpro_bot_runs_stage_ids"),
        Index("ix_cpro_bot_runs_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="started", server_default="started"
    )
    #: ``False`` = próba: bot zostawia ofertę jako szkic (DRAFT) i nie wysyła.
    submit: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    #: Karty (``candidate_stages.id`` w kolejce Cpro) objęte biegiem.
    stage_ids: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: Zlecenie wysłane botowi (pozycje formularza Cpro).
    request: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    #: Wynik z raportu: ``{"items": {"<stage_id>": {...}}, "counts": {...}}``.
    report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    error: Mapped[Optional[str]] = mapped_column(String(255))
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    received_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
