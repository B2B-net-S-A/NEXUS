"""Onboarding checklist item per contract."""

import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class OnboardingItemStatus(str, enum.Enum):
    pending = "pending"
    done = "done"
    na = "na"


class ContractOnboardingItem(Base, TimestampMixin):
    __tablename__ = "contract_onboarding_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[OnboardingItemStatus] = mapped_column(
        Enum(OnboardingItemStatus, name="onboardingitemstatus"),
        default=OnboardingItemStatus.pending,
        nullable=False,
    )
    assigned_to: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    order: Mapped[int] = mapped_column("order", Integer, nullable=False, default=0)

    contract = relationship("Contract", back_populates="onboarding_items")

    def __repr__(self) -> str:
        return (
            f"<ContractOnboardingItem id={self.id} contract={self.contract_id} "
            f"label={self.label!r} status={self.status}>"
        )
