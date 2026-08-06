"""Order (Zamówienie od klienta) — perspektywa klienta z konkretnej rekrutacji.

Model biznesowy body-leasingu:
- Order = jeden PDF zamówienia od klienta (kontraktor, stanowisko, rate_client,
  daty)
- ZAWSZE pod konkretnym kandydackim ``Contract`` (1:N — jeden Contract ma wiele
  Orderów w czasie, np. przedłużenia 3msc → 6msc → 6msc)
- Pochodzi z konkretnego ``Job`` (rekrutacji) — `job_id` nullable bo dla
  legacy/ad-hoc orderów może brakować
- Może być bez MSA (`framework_contract_id` nullable)

Marża per Order = `rate_client - Contract.rate_candidate` (rate_candidate trzymany
na Contract; Order może mieć różny rate_client niż Contract.rate_client — np.
przedłużenie z podwyżką).
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
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
    """Lifecycle order/zamówienia."""

    draft = "draft"  # Auto-utworzony z hired hook lub manualnie, do uzupełnienia
    active = "active"  # Aktywne, kontraktor pracuje
    paused = "paused"  # Tymczasowo wstrzymane
    completed = "completed"  # Zakończone (end_date minęło lub kontraktor odszedł)
    cancelled = "cancelled"  # Anulowane przed startem


class ClientOrder(Base, TimestampMixin):
    """Zamówienie od klienta pod konkretnym kandydackim Contractem."""

    __tablename__ = "client_orders"
    __table_args__ = (
        CheckConstraint(
            "project_part IS NULL OR project_part IN "
            "('cz1', 'cz2', 'cz4', 'cz5', 'cz6')",
            name="ck_client_orders_project_part",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    """FK do kandydackiego Contract. Order ZAWSZE należy do jednego Contractu."""

    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    """Z której rekrutacji to zamówienie wzięło (nullable dla legacy)."""

    framework_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="RESTRICT"),
        nullable=True,
        index=True,
    )
    """MSA pod którą jest Order. Nullable bo klient może nie mieć MSA."""

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
    # Plan analytics PR 6: FAKT pierwszej aktywacji zamówienia (nie estymata).
    # Ustawiane raz — przy utworzeniu ze statusem active albo pierwszym
    # przejściu na active. Historyczne zamówienia sprzed migracji 0176 mają
    # NULL → raporty czasu wypełnienia oznaczają je jako partial, NIGDY nie
    # zgadują daty.
    filled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True, index=True)
    """``NULL`` = open-ended. Indeksowane — scheduler skanuje expiry."""

    # Rate_client per Order — może różnić się od Contract.rate_client przy
    # przedłużeniach z podwyżką. rate_candidate trzymamy na Contract (typically
    # stała przez całą współpracę z kontraktorem).
    # Numeric(12,3) — stawka klienta z PO może być dziesiętna z 3 miejscami
    # po przecinku (np. Alior 164.375 PLN/h — migracja 0149).
    rate_client: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 3), nullable=True
    )

    total_value: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    """Całkowita wartość kontraktu (rate_client × długość okresu) — calculated
    lub manualnie wpisane."""

    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)

    # „Część umowy" Centrum e-Zdrowia (ticket #3): slug cz1|cz2|cz4|cz5|cz6
    # (cz.3 celowo nie istnieje). Nullable — wymagane tylko w walidacji API/UI
    # dla client_id=115 (app/services/ezdrowie.py); inni klienci mają NULL.
    project_part: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)

    # PO PDF (Purchase Order od klienta)
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
    contract = relationship("Contract", back_populates="client_orders")
    job = relationship("Job", foreign_keys=[job_id])
    framework_contract = relationship(
        "ClientFrameworkContract", back_populates="orders"
    )
    creator = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<ClientOrder id={self.id} client={self.client_id} "
            f"contract={self.contract_id} title={self.title!r} status={self.status}>"
        )
