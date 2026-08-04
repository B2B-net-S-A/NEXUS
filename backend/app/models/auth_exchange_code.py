"""One-time authorization-exchange codes for Microsoft SSO callback.

Rationale: putting Nexus access/refresh tokens directly in the redirect URL
query string (``?token=...&refresh=...``) leaks them into proxy logs, browser
history, and Sentry breadcrumbs. Instead the OAuth callback persists the
tokens here under a short-lived UUID and redirects with ``?code=<uuid>``.
The frontend POSTs the code to ``/api/auth/microsoft/exchange`` and gets the
tokens back as a JSON body — never in any URL.

Lifecycle:
- Created in callback (``app/api/auth_microsoft.py``).
- TTL 60 seconds (``expires_at = now + 60s``); atomically deleted on the first
  valid POST whose authorization version still matches the active user.
- Replay (POST with same code twice) returns 410 Gone.
- Cleanup of expired/legacy-consumed rows is opportunistic — no janitor needed at
  this volume; rows are tiny (~300 bytes each).

Base schema lives in migration ``0081_user_oauth_fields``; authorization-version
binding is added by ``0210_role_dashboard_rbac_cutover``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AuthExchangeCode(Base):
    __tablename__ = "auth_exchange_codes"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    access_token: Mapped[str] = mapped_column(Text, nullable=False)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)
    issued_authorization_version: Mapped[int] = mapped_column(
        BigInteger,
        nullable=False,
        default=1,
        server_default="1",
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    user = relationship("User", foreign_keys=[user_id])
