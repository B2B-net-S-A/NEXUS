"""FX rate cache (NBP daily rates → PLN)."""

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class FxRate(Base, TimestampMixin):
    __tablename__ = "fx_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    rate_to_pln: Mapped[Decimal] = mapped_column(Numeric(14, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, default="NBP")

    def __repr__(self) -> str:
        return (
            f"<FxRate {self.currency}={self.rate_to_pln} "
            f"on {self.effective_date} ({self.source})>"
        )
