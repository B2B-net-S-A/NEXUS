"""Niedokończony formularz „Nowa rekrutacja” na koncie autora — 0415.

Kolumny i powód istnienia: ``app/services/job_intake_form_schema.py``.
Trasy: ``app/api/job_intake_forms.py``.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class JobIntakeForm(Base, TimestampMixin):
    __tablename__ = "job_intake_forms"
    __table_args__ = (
        Index("ix_job_intake_forms_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    label: Mapped[str] = mapped_column(
        String(255), nullable=False, default="", server_default=text("''")
    )
    source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="manual", server_default=text("'manual'")
    )
    request_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    form: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
