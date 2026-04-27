"""Magic-link token dla self-service deklaracji „Otwartość".

Token jest jednokrotny (`used_at` set on first successful POST), TTL 30 dni
(`expires_at`). Rekruter generuje, kandydat klika link i przez publiczny
formularz aktualizuje swoje preferencje engagement.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.core.database import Base

if TYPE_CHECKING:  # pragma: no cover
    from app.models.candidate import Candidate
    from app.models.user import User


class EngagementDeclarationToken(Base):
    __tablename__ = "engagement_declaration_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token: Mapped[str] = mapped_column(String(48), unique=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    candidate: Mapped["Candidate"] = relationship("Candidate", lazy="joined")
    creator: Mapped[Optional["User"]] = relationship("User", lazy="joined")
