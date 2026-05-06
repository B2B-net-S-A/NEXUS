"""Password reset token (DB-backed, hashed).

Plain token istnieje wyłącznie w wysłanym mailu. W DB trzymamy SHA-256
hash — lookup po unikalnym indeksie ``token_hash``. Token jest jednorazowy
(``used_at`` ustawiamy atomic-update'em w
``services/password_reset.py:verify_and_consume_token``), TTL standardowo
60 min ustawiany przez serwis.

Tabela utworzona w migracji ``0078_password_reset_infrastructure``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class PasswordResetToken(Base, TimestampMixin):
    """One-time, time-limited token uprawniający do ustawienia nowego hasła."""

    __tablename__ = "password_reset_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # SHA-256 hex digest (64 znaki). Lookup po UNIQUE INDEX — brak timing leak.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)

    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    # Single-use guard. ``verify_and_consume_token`` ustawia atomic
    # UPDATE ... WHERE used_at IS NULL RETURNING * — race-safe.
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Audit: IP z którego przyszło żądanie (request.client.host).
    requested_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # Gdy admin wysłał link w imieniu usera ("Wyślij link resetowy") — id admina.
    requested_by_admin_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships — tylko dla audytu/debugowania, nie back_populates (User nie
    # potrzebuje listy swoich tokenów w runtime).
    user = relationship("User", foreign_keys=[user_id])
    requested_by_admin = relationship("User", foreign_keys=[requested_by_admin_id])

    def __repr__(self) -> str:
        return (
            f"<PasswordResetToken id={self.id} user={self.user_id} "
            f"expires={self.expires_at} used={self.used_at is not None}>"
        )
