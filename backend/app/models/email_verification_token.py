"""Email verification token (DB-backed, hashed).

Wystawiany przy self-service rejestracji (POST /api/auth/register). Plain token
istnieje wyłącznie w wysłanym mailu; w DB trzymamy SHA-256 hash — lookup po
unikalnym indeksie ``token_hash``. Token jest jednorazowy (``used_at`` ustawiany
atomic-update'em w ``services/email_verification.py:verify_and_consume_token``),
TTL standardowo 24 h ustawiany przez serwis.

Bliźniaczy do :class:`app.models.password_reset_token.PasswordResetToken` —
osobna tabela bo cykl życia i semantyka są inne (potwierdzenie adresu vs reset
hasła), choć mechanika (hash + expiry + single-use) jest identyczna.

Tabela utworzona w migracji ``0139_email_verification``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class EmailVerificationToken(Base, TimestampMixin):
    """One-time, time-limited token potwierdzający adres email po rejestracji."""

    __tablename__ = "email_verification_tokens"

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

    # Audit: IP z którego przyszła rejestracja (request.client.host).
    requested_ip: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)

    # Relationship — tylko dla audytu/debugowania (User nie potrzebuje listy
    # swoich tokenów w runtime).
    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<EmailVerificationToken id={self.id} user={self.user_id} "
            f"expires={self.expires_at} used={self.used_at is not None}>"
        )
