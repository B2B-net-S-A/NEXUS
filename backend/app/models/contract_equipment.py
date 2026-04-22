"""Equipment handed over to a consultant per contract.

Covers laptops, phones, monitors, security tokens, keycards etc. — anything
we or the client supplies that has to be tracked through return. Used by the
contract-alerts task to surface upcoming returns before a contract ends.
"""

import enum
from datetime import date
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class EquipmentItemType(str, enum.Enum):
    laptop = "laptop"
    phone = "phone"
    monitor = "monitor"
    headset = "headset"
    docking_station = "docking_station"
    security_token = "security_token"
    keycard = "keycard"
    sim_card = "sim_card"
    other = "other"


class EquipmentOwner(str, enum.Enum):
    ours = "ours"
    client = "client"


class EquipmentReturnStatus(str, enum.Enum):
    pending = "pending"
    returned = "returned"
    lost = "lost"
    written_off = "written_off"


class ContractEquipment(Base, TimestampMixin):
    __tablename__ = "contract_equipment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )

    item_type: Mapped[EquipmentItemType] = mapped_column(
        Enum(EquipmentItemType, name="equipmentitemtype"), nullable=False
    )
    owner: Mapped[EquipmentOwner] = mapped_column(
        Enum(EquipmentOwner, name="equipmentowner"), nullable=False
    )

    brand_model: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    serial_number: Mapped[Optional[str]] = mapped_column(
        String(120), nullable=True, index=True
    )
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Deposit / security held (in smallest currency unit — PLN grosze, EUR cents…).
    deposit_amount: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    deposit_currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    handed_over_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    return_due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    returned_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    return_status: Mapped[EquipmentReturnStatus] = mapped_column(
        Enum(EquipmentReturnStatus, name="equipmentreturnstatus"),
        nullable=False,
        default=EquipmentReturnStatus.pending,
        server_default="pending",
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    contract = relationship("Contract", back_populates="equipment")

    def __repr__(self) -> str:
        return (
            f"<ContractEquipment id={self.id} contract={self.contract_id} "
            f"item={self.item_type} status={self.return_status}>"
        )
