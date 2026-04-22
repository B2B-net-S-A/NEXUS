"""Market rate benchmarks uploaded from industry reports (Hays, No Fluff Jobs,
Just Join IT…) or entered manually. Used by the contracts benchmark endpoint
to compare our contract rates against market medians for the same role.
"""

import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.contract import RateUnit


class SeniorityLevel(str, enum.Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    expert = "expert"
    principal = "principal"


class RateBenchmark(Base, TimestampMixin):
    __tablename__ = "rate_benchmarks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    role: Mapped[str] = mapped_column(String(160), nullable=False, index=True)
    seniority: Mapped[Optional[SeniorityLevel]] = mapped_column(
        Enum(SeniorityLevel, name="seniorityleveltype"), nullable=True, index=True
    )

    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    rate_unit: Mapped[RateUnit] = mapped_column(
        Enum(RateUnit, name="rateunit"), nullable=False
    )

    market_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    market_median: Mapped[int] = mapped_column(Integer, nullable=False)
    market_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    source: Mapped[str] = mapped_column(String(200), nullable=False)
    source_date: Mapped[date] = mapped_column(Date, nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    def __repr__(self) -> str:
        return (
            f"<RateBenchmark id={self.id} role={self.role!r} "
            f"seniority={self.seniority} median={self.market_median} {self.currency}>"
        )
