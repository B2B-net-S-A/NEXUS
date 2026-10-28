"""Połączenie wtyczki LinkedIn z kontem NEXUSA (migracja 0607).

Wtyczka nie dostaje JWT użytkownika: ten otwiera całe API, a wtyczka
potrzebuje tylko tras ``/api/extension/*``. Dostaje własny klucz
``nxe_v1_<id>_<sekret>``, który żadna inna trasa nie czyta, więc wyciek klucza
z przeglądarki nie daje dostępu do reszty NEXUSA. DDL:
``app/services/linkedin_extension_schema.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.user import User


class LinkedinExtensionConnection(Base):
    __tablename__ = "linkedin_extension_connections"

    # Jawne id ``v1$<hex>`` — po nim idzie SELECT, wolno je logować.
    key_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    secret_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    # Wersja uprawnień konta z chwili połączenia; inna = wtyczka odłączona.
    authorization_version: Mapped[int] = mapped_column(Integer, nullable=False)
    extension_version: Mapped[Optional[str]] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    revoked_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    usage_day: Mapped[Optional[date]] = mapped_column(Date)
    reads_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    adds_today: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="joined")
