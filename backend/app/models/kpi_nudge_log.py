"""KPI Coach — log wysłanych nudge'y (dedup + historia dla usera).

Dedup key: (user_id, kpi_id, nudge_type, period_bucket).
  period_bucket:
    day   → "YYYY-MM-DD"  (np. "2026-04-21")
    week  → "YYYY-Www"    (ISO week, np. "2026-W17")
    month → "YYYY-MM"     (np. "2026-04")
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import BigInteger, DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class KpiNudgeType(str, enum.Enum):
    praise_hit = "praise_hit"
    remind_behind = "remind_behind"
    eod_summary = "eod_summary"
    streak_bonus = "streak_bonus"


class KpiNudgeChannel(str, enum.Enum):
    toast = "toast"
    notification = "notification"
    slack = "slack"


class KpiNudgeLog(Base):
    """Pojedynczy wysłany nudge. Append-only, brak updated_at."""

    __tablename__ = "kpi_nudge_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    kpi_id: Mapped[str] = mapped_column(String(64), nullable=False)
    nudge_type: Mapped[KpiNudgeType] = mapped_column(
        Enum(KpiNudgeType, name="kpinudgetype"), nullable=False
    )
    channel: Mapped[KpiNudgeChannel] = mapped_column(
        Enum(KpiNudgeChannel, name="kpinudgechannel"), nullable=False
    )
    message_variant: Mapped[int] = mapped_column(Integer, nullable=False)
    period_bucket: Mapped[str] = mapped_column(String(20), nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<KpiNudgeLog user={self.user_id} kpi={self.kpi_id} "
            f"type={self.nudge_type.value} bucket={self.period_bucket}>"
        )
