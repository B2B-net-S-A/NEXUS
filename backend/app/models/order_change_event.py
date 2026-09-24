"""Dziennik rozliczeniowych zmian w zamówieniach (0308).

Źródło podzakładki „Zmiany" w Finanse → Zmiany w zamówieniach. Do 09.2026 nic
w systemie nie zapisywało STAREJ wartości stawki ani daty końca zamówienia:
``Activity order_updated`` i zdarzenie ``edycja_reczna`` niosą same nazwy pól.
Bez starej liczby dział finansowy nie ma czego porównać z poprzednim
rozliczeniem.

Wiersz powstaje w tej samej transakcji co zmiana (listener ``before_flush``
w ``services/order_change_audit.py``), więc nie da się zapisać zmiany stawki
bez śladu. Jeden wiersz = jedno pole jednego zamówienia (albo data końca
całej grupy zamówienia MD/kosztowego).

Tabela celowo nie ma kluczy obcych: wpis ma przeżyć usunięcie zamówienia
i konta osoby, która zmieniła stawkę, a zapis wewnątrz flusha nie może czekać
na blokady. Nie niesie imion i nazwisk — konsultanta dociąga odczyt przez
kontrakt.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

FIELD_RATE_COST = "rate_cost"
FIELD_RATE_REVENUE = "rate_revenue"
FIELD_END_DATE = "end_date"
ORDER_CHANGE_FIELDS: tuple[str, ...] = (
    FIELD_RATE_COST,
    FIELD_RATE_REVENUE,
    FIELD_END_DATE,
)

SOURCE_USER = "user"
SOURCE_SYSTEM = "system"


class OrderChangeEvent(Base):
    __tablename__ = "order_change_events"
    __table_args__ = (
        CheckConstraint(
            "field IN ('rate_cost', 'rate_revenue', 'end_date')",
            name="ck_order_change_events_field",
        ),
        CheckConstraint(
            "source IN ('user', 'system')",
            name="ck_order_change_events_source",
        ),
        Index("ix_order_change_events_created_at", "created_at"),
        Index("ix_order_change_events_order", "order_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL = zmiana daty końca CAŁEJ grupy zamówienia (``order_group_id``).
    order_id: Mapped[Optional[int]] = mapped_column(Integer)
    order_group_id: Mapped[Optional[int]] = mapped_column(Integer)
    contract_id: Mapped[Optional[int]] = mapped_column(Integer)
    client_id: Mapped[Optional[int]] = mapped_column(Integer)
    field: Mapped[str] = mapped_column(String(16), nullable=False)
    old_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6))
    new_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(16, 6))
    # ``hourly`` | ``daily`` | ``monthly`` | ``md`` — kwota bez jednostki
    # przy zmianie jednostki czytałaby się jak podwyżka o rząd wielkości.
    old_unit: Mapped[Optional[str]] = mapped_column(String(16))
    new_unit: Mapped[Optional[str]] = mapped_column(String(16))
    currency: Mapped[Optional[str]] = mapped_column(String(3))
    # Waluta PRZED zmianą (0372, audyt 24.09.2026): sama zmiana waluty też
    # jest zmianą stawki. NULL w wierszach sprzed tej kolumny.
    old_currency: Mapped[Optional[str]] = mapped_column(String(3))
    old_date: Mapped[Optional[date]] = mapped_column(Date)
    new_date: Mapped[Optional[date]] = mapped_column(Date)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default=SOURCE_SYSTEM
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
