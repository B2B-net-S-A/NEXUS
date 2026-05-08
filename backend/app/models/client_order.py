"""Order (Statement of Work / Zamówienie) — konkretne zlecenie pod MSA.

Hierarchia: Klient → ClientFrameworkContract (MSA) → ClientOrder (SOW)
→ ClientOrderContract (M:N → kandydaccy Contract).

Order ma własny ``total_value`` (opcjonalny — kontraktowo uzgodniony budżet)
i status. Marża per order liczy się dynamicznie z linkowanych
``contracts.rate_client - contracts.rate_candidate`` (patrz
:func:`app.api.client_orders.compute_order_margin`).
"""

from __future__ import annotations

import enum
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Date,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ClientOrderStatus(str, enum.Enum):
    """Lifecycle order/SOW."""

    draft = "draft"
    active = "active"
    paused = "paused"
    completed = "completed"
    cancelled = "cancelled"


class ClientOrder(Base, TimestampMixin):
    """Zamówienie/SOW pod konkretną umową ramową klienta."""

    __tablename__ = "client_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    framework_contract_id: Mapped[int] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    status: Mapped[ClientOrderStatus] = mapped_column(
        Enum(ClientOrderStatus, name="clientorderstatus", create_type=False),
        nullable=False,
        default=ClientOrderStatus.draft,
        server_default="draft",
        index=True,
    )

    start_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    end_date: Mapped[Optional[date]] = mapped_column(
        Date, nullable=True, index=True
    )
    """``NULL`` = open-ended. Indeksowane — scheduler skanuje expiry."""

    total_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    positions_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    """Planowana liczba osób na orderze."""

    # PO PDF (Purchase Order od klienta) — opcjonalny załącznik
    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    client = relationship("Client", backref="orders")
    framework_contract = relationship(
        "ClientFrameworkContract", back_populates="orders"
    )
    creator = relationship("User", foreign_keys=[created_by_user_id])
    contract_links = relationship(
        "ClientOrderContract",
        back_populates="order",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ClientOrder id={self.id} client={self.client_id} "
            f"title={self.title!r} status={self.status}>"
        )
