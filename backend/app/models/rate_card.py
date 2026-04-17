"""Rate card — cennik stawek per klient × rola × seniority."""

from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin
from app.models.contract import RateUnit


class RateCard(Base, TimestampMixin):
    """Cennik dla kombinacji klient + rola + seniority.

    Używany jako auto-suggest przy tworzeniu kontraktu (B2) i w auto-hire
    flow (A2). Stawki min/max dają przedział negocjacyjny.
    """

    __tablename__ = "rate_cards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    role: Mapped[str] = mapped_column(String(255), nullable=False)
    seniority: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)

    rate_candidate_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate_candidate_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate_client_min: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    rate_client_max: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    currency: Mapped[str] = mapped_column(String(3), default="PLN", nullable=False)
    rate_unit: Mapped[RateUnit] = mapped_column(
        Enum(RateUnit, name="rateunit"),
        default=RateUnit.monthly,
        nullable=False,
    )

    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    client = relationship("Client")

    def __repr__(self) -> str:
        return (
            f"<RateCard id={self.id} client={self.client_id} "
            f"role={self.role!r} seniority={self.seniority}>"
        )
