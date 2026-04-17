"""Contract amendment — extension, rate change, scope change, termination."""

import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractAmendmentType(str, enum.Enum):
    extension = "extension"
    rate_change = "rate_change"
    scope_change = "scope_change"
    early_termination = "early_termination"


class ContractAmendment(Base, TimestampMixin):
    """Historia zmian umowy — każdy aneks to snapshot old → new."""

    __tablename__ = "contract_amendments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    amendment_type: Mapped[ContractAmendmentType] = mapped_column(
        Enum(ContractAmendmentType, name="contractamendmenttype"), nullable=False
    )
    old_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    new_values: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contract_documents.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id"), nullable=True
    )

    contract = relationship("Contract", back_populates="amendments")

    def __repr__(self) -> str:
        return (
            f"<ContractAmendment id={self.id} contract={self.contract_id} "
            f"type={self.amendment_type}>"
        )
