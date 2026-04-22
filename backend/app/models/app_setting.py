"""Global app-level key/value settings.

Single-row-per-key store for organization-wide UI/product settings that a
designated admin configures for everyone. Per-user overrides live on the
frontend (zustand + localStorage) — the `AppSetting.value` JSONB is always
the *default* everyone else starts from.

Today this only holds `candidates_columns`. Expect more keys to join later
(SLA thresholds, default currency, feature toggles).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    updater = relationship("User", foreign_keys=[updated_by])

    def __repr__(self) -> str:
        return f"<AppSetting key={self.key}>"
