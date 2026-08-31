"""Durable decision state for consultant offboarding on MD orders.

Contract termination itself is an immutable business fact, while the remaining
MD pool needs a separate Delivery Lead decision.  Keeping that decision in its
own row makes retries idempotent, preserves the financial snapshot used by the
decision, and avoids overloading ``ClientOrder.status`` with a workflow state.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


OFFBOARDING_STATUS_PENDING = "pending"
OFFBOARDING_STATUS_RESOLVED = "resolved"
OFFBOARDING_STATUSES: tuple[str, ...] = (
    OFFBOARDING_STATUS_PENDING,
    OFFBOARDING_STATUS_RESOLVED,
)

OFFBOARDING_RESOLUTION_REMOVE = "remove"
OFFBOARDING_RESOLUTION_TRANSFER = "transfer"
OFFBOARDING_RESOLUTION_RESTORE = "restore"
"""Wspolpraca jednak trwa: linia wraca do aktywnej obsady, a pula MD zostaje
nienaruszona.  Rozstrzygniecie tej samej sprawy co ``remove``/``transfer``,
ale jedyne, ktore NIE dysponuje pula — bo nie ma czego rozdysponowac."""

OFFBOARDING_RESOLUTIONS: tuple[str, ...] = (
    OFFBOARDING_RESOLUTION_REMOVE,
    OFFBOARDING_RESOLUTION_TRANSFER,
    OFFBOARDING_RESOLUTION_RESTORE,
)

OFFBOARDING_RATE_BASIS_DEPARTING = "departing"
OFFBOARDING_RATE_BASIS_RECIPIENT = "recipient"
OFFBOARDING_RATE_BASES: tuple[str, ...] = (
    OFFBOARDING_RATE_BASIS_DEPARTING,
    OFFBOARDING_RATE_BASIS_RECIPIENT,
)


class ClientOrderOffboardingCase(Base, TimestampMixin):
    """One MD disposition decision for one order line and effective date.

    ``remaining_md_snapshot`` is populated from the historical per-line MD
    budget.  For newer groups whose pool belongs to the whole order it is zero
    and ``uses_shared_md_pool`` is true: terminating one consultant must never
    assign or subtract another consultant's shared budget implicitly.
    """

    __tablename__ = "client_order_offboarding_cases"
    __table_args__ = (
        UniqueConstraint(
            "order_id",
            "effective_date",
            name="uq_client_order_offboarding_order_effective",
        ),
        CheckConstraint(
            "status IN ('pending', 'resolved')",
            name="ck_client_order_offboarding_status",
        ),
        CheckConstraint(
            "resolution IS NULL OR resolution IN ('remove', 'transfer', 'restore')",
            name="ck_client_order_offboarding_resolution",
        ),
        CheckConstraint(
            "rate_basis IS NULL OR rate_basis IN ('departing', 'recipient')",
            name="ck_client_order_offboarding_rate_basis",
        ),
        CheckConstraint(
            "(status = 'pending' AND resolution IS NULL AND resolved_at IS NULL "
            "AND target_order_id IS NULL AND rate_basis IS NULL) "
            "OR (status = 'resolved' AND resolution IS NOT NULL "
            "AND resolved_at IS NOT NULL)",
            name="ck_client_order_offboarding_resolution_state",
        ),
        CheckConstraint(
            "resolution IS DISTINCT FROM 'transfer' OR rate_basis IS NOT NULL",
            name="ck_client_order_offboarding_transfer_target",
        ),
        CheckConstraint(
            "resolution IS DISTINCT FROM 'remove' "
            "OR (target_order_id IS NULL AND rate_basis IS NULL)",
            name="ck_client_order_offboarding_remove_target",
        ),
        # Osobne ograniczenie zamiast poszerzenia tego wyzej: nazwa ma nadal
        # mowic, ktorej decyzji pilnuje.  ``restore`` nie rozdysponowuje puli,
        # wiec nie ma ani odbiorcy, ani podstawy stawki.
        CheckConstraint(
            "resolution IS DISTINCT FROM 'restore' "
            "OR (target_order_id IS NULL AND rate_basis IS NULL)",
            name="ck_client_order_offboarding_restore_target",
        ),
        CheckConstraint("version >= 1", name="ck_client_order_offboarding_version"),
        CheckConstraint(
            "remaining_md_snapshot >= 0",
            name="ck_client_order_offboarding_remaining_nonnegative",
        ),
        Index(
            "ix_client_order_offboarding_pending",
            "client_id",
            "effective_date",
            postgresql_where=text("status = 'pending'"),
        ),
        Index(
            "ix_client_order_offboarding_contract_effective",
            "contract_id",
            "effective_date",
        ),
        Index("ix_client_order_offboarding_group", "order_group_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    order_id: Mapped[int] = mapped_column(
        ForeignKey("client_orders.id", ondelete="CASCADE"), nullable=False
    )
    order_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL"), nullable=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )

    effective_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default=OFFBOARDING_STATUS_PENDING,
        server_default=OFFBOARDING_STATUS_PENDING,
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    uses_shared_md_pool: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    remaining_md_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(16, 6), nullable=False, server_default="0"
    )
    rate_cost_snapshot: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    rate_revenue_snapshot: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    currency_snapshot: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    order_number_snapshot: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )

    resolution: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    target_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )
    rate_basis: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    resolution_payload: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    contract = relationship("Contract", foreign_keys=[contract_id])
    order = relationship("ClientOrder", foreign_keys=[order_id])
    target_order = relationship("ClientOrder", foreign_keys=[target_order_id])
    order_group = relationship("ClientOrderGroup", foreign_keys=[order_group_id])
    client = relationship("Client", foreign_keys=[client_id])
    resolver = relationship("User", foreign_keys=[resolved_by_user_id])
    creator = relationship("User", foreign_keys=[created_by_user_id])
    alerts = relationship(
        "DlAlert",
        back_populates="offboarding_case",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return (
            f"<ClientOrderOffboardingCase id={self.id} order={self.order_id} "
            f"status={self.status!r}>"
        )
