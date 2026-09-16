"""Umowa wykonawcza Centrum e-Zdrowia — drugi poziom pod umową ramową (częścią).

Struktura dwupoziomowa (ticket 09.2026): umowa ramowa = część zamówienia
(``client_framework_contracts.project_part``: cz1|cz2|cz4|cz5|cz6) → 0..N umów
wykonawczych. Konsultant jest przypisywany do KONKRETNEJ umowy wykonawczej
(``client_orders.executive_contract_id`` / ``client_order_groups.executive_contract_id``),
nie do samej części — do tej pory system nie rozróżniał, że pod jedną częścią
może żyć więcej niż jedna umowa wykonawcza.

Numery „DO UMOWY RAMOWEJ" widniejące na dokumentach umów wykonawczych są
błędne (zamienione numery) — przypisanie do części pochodzi WYŁĄCZNIE z tej
tabeli (zasiew w migracji 0312 + ręczne dodanie w UI), nigdy z parsowania
treści dokumentu.

Funkcja dotyczy wyłącznie klienta 115 (bramka ``app.services.ezdrowie``);
u pozostałych klientów tabela pozostaje pusta.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

EXECUTIVE_CONTRACT_STATUS_ACTIVE = "active"
EXECUTIVE_CONTRACT_STATUS_ENDED = "ended"
EXECUTIVE_CONTRACT_STATUSES: tuple[str, ...] = (
    EXECUTIVE_CONTRACT_STATUS_ACTIVE,
    EXECUTIVE_CONTRACT_STATUS_ENDED,
)
EXECUTIVE_CONTRACT_STATUS_LABELS: dict[str, str] = {
    EXECUTIVE_CONTRACT_STATUS_ACTIVE: "Aktywna",
    EXECUTIVE_CONTRACT_STATUS_ENDED: "Zakończona",
}


class ClientExecutiveContract(Base, TimestampMixin):
    """Umowa wykonawcza pod umową ramową (częścią) jednego klienta."""

    __tablename__ = "client_executive_contracts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'ended')",
            name="ck_client_executive_contracts_status",
        ),
        CheckConstraint(
            "char_length(btrim(number)) > 0",
            name="ck_client_executive_contracts_number_nonempty",
        ),
        UniqueConstraint(
            "client_id", "number", name="ux_client_executive_contracts_client_number"
        ),
        Index(
            "ix_client_executive_contracts_framework",
            "framework_contract_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    framework_contract_id: Mapped[int] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="RESTRICT"),
        nullable=False,
    )
    """Umowa ramowa (część), pod którą wisi ta umowa wykonawcza. RESTRICT —
    usunięcie części nie może osierocić przypisań konsultantów."""

    number: Mapped[str] = mapped_column(String(64), nullable=False)
    """Numer nadany przez klienta, np. ``CeZ/242/2025``. Unikalny per klient."""

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default=EXECUTIVE_CONTRACT_STATUS_ACTIVE
    )
    """``active`` (domyślny dla nowo dodanej umowy — ticket) albo ``ended``."""

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    client = relationship("Client")
    framework_contract = relationship(
        "ClientFrameworkContract", back_populates="executive_contracts"
    )
    creator = relationship("User", foreign_keys=[created_by_user_id])
    orders = relationship(
        "ClientOrder",
        back_populates="executive_contract",
        order_by="ClientOrder.start_date.desc()",
    )
    order_groups = relationship(
        "ClientOrderGroup",
        back_populates="executive_contract",
        order_by="ClientOrderGroup.start_date.desc()",
    )

    def __repr__(self) -> str:
        return (
            f"<ClientExecutiveContract id={self.id} client={self.client_id} "
            f"number={self.number!r} status={self.status}>"
        )
