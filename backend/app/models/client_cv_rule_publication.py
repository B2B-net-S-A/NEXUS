"""Immutable recipes retained for explicit restoration after later edits."""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientCvRulePublication(Base):
    __tablename__ = "client_cv_rule_publications"

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), primary_key=True
    )
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    recipe: Mapped[dict] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=False
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    published_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
