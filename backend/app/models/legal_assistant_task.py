"""Zamknięte zadanie asystenta prawnego — 0790.

Opis: ``app/services/legal/tasks_schema.py``. Zapis i odczyt:
``app/services/legal/tasks.py``.
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
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class LegalAssistantTask(Base):
    __tablename__ = "legal_assistant_tasks"
    __table_args__ = (
        UniqueConstraint("task_key", name="uq_legal_assistant_tasks_key"),
        CheckConstraint(
            "status IN ('done', 'dismissed')", name="ck_legal_assistant_tasks_status"
        ),
        Index("ix_legal_assistant_tasks_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    task_key: Mapped[str] = mapped_column(String(160), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True
    )
    letter_kind: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
