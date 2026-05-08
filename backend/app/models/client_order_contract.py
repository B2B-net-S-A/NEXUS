"""M:N link Order ↔ Candidate Contract.

Dlaczego osobna tabela zamiast bezpośredniego FK na ``contracts.client_order_id``:
- ten sam ``Contract`` mógłby teoretycznie obsługiwać kilka orderów
  (rzadkie ale możliwe — kontraktor równolegle pomaga w innym SOW)
- audit trail (``assigned_at``, ``assigned_by_user_id``) per linkowanie
- soft remove bez kasowania samego kontraktu kandydackiego
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ClientOrderContract(Base):
    """Wiązanie Order ↔ kandydacki Contract."""

    __tablename__ = "client_order_contracts"
    __table_args__ = (
        UniqueConstraint("order_id", "contract_id", name="uq_order_contract"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("client_orders.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assigned_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    order = relationship("ClientOrder", back_populates="contract_links")
    contract = relationship("Contract", foreign_keys=[contract_id])
    assigned_by = relationship("User", foreign_keys=[assigned_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<ClientOrderContract order={self.order_id} contract={self.contract_id}>"
        )
