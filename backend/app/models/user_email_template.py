"""User email template — per-user library for M365 outreach composition.

Created in Phase 4.5 of the M365 plan. Kept separate from the legacy
`email_templates` table (rejection emails, see `app.models.email_template`)
so the rejection flow's `category` / `is_default` semantics stay intact.

Rendered with a Jinja2 SandboxedEnvironment at /api/user-email-templates/{id}/render
— see `app.api.user_email_templates`.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class UserEmailTemplate(Base, TimestampMixin):
    """Per-user email template for M365 outreach.

    `is_shared=True` makes the template visible to every other user in the
    org (read-only for non-owners — owner remains sole editor/deleter).
    """

    __tablename__ = "user_email_templates"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    user_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(String(998), nullable=True)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)

    # Auto-detected on create/update from Jinja2 AST. Stored as a list so the
    # UI can render "available variables" chips without re-parsing the body
    # on every render.
    variables: Mapped[List[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )

    is_shared: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # TimestampMixin provides created_at + updated_at.
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]

    owner = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<UserEmailTemplate id={self.id} name={self.name!r} "
            f"user_id={self.user_id} shared={self.is_shared}>"
        )
