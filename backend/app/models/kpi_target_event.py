"""Historia zmian celów KPI z edytora „Cele KPI" (migracja 0355, plan PR3).

Jeden wiersz na realną zmianę: odstępstwo roli (`scope="role"`) albo osobisty
cel (`scope="user"`). Bez historii zmiana progu wyścigu z nagrodą 1 500 zł
kończyłaby się na „ktoś coś zmienił". Nazwy osób są zdenormalizowane — konto
może zniknąć, historia nie. Wiersze nie są kasowane razem z osobą (SET NULL).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class KpiTargetEvent(Base):
    __tablename__ = "kpi_target_events"
    __table_args__ = (
        CheckConstraint("scope IN ('role', 'user')", name="ck_kpi_target_events_scope"),
        CheckConstraint(
            "action IN ('set', 'reset')", name="ck_kpi_target_events_action"
        ),
        Index("ix_kpi_target_events_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # role | user
    scope: Mapped[str] = mapped_column(String(8), nullable=False)
    role: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    subject_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    kpi_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # set | reset
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # {"target_value": {"from": 4, "to": 5}}
    changes: Mapped[Optional[dict]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
