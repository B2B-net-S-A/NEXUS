"""Własny pulpit startowy — jeden układ kafelków na osobę (0336).

Kształt ``layout`` pilnuje ``app/services/dashboard_tiles.py``; ta klasa jest
wyłącznie przechowalnią. Wiersz powstaje przy pierwszym zapisie — brak wiersza
znaczy „pusty pulpit", nie błąd.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserDashboard(Base):
    __tablename__ = "user_dashboards"
    __table_args__ = (
        CheckConstraint("version >= 0", name="ck_user_dashboards_version"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    layout: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default='{"tiles": []}'
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
