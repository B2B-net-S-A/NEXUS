"""Brak kolejnego zamówienia po zakończonym zamówieniu (0308).

Wiersz powstaje DZIEŃ PO dacie końca zamówienia, gdy ta sama osoba nie ma
u tego klienta żadnego następnego zamówienia (aktywnego, przyszłego ani
szkicu). Źródło podzakładki „Braki" w Finansach i alertu Delivery Leada.

**Wiersz nigdy nie jest kasowany.** Gdy DL doda zamówienie po fakcie, status
zmienia się na ``filled_late`` z numerem i datą uzupełnienia — ticket wymaga,
żeby było widać, że temat nie został dopilnowany na czas. Kasowanie przy
uzupełnieniu zamieniłoby raport w listę „na dziś", z której spóźnienia
znikają same.

Bez kluczy obcych z tego samego powodu co ``order_change_events``: wpis
przeżywa usunięcie zamówienia, a numer zamówienia jest zapisany w chwili
wykrycia.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

GAP_STATUS_OPEN = "open"
GAP_STATUS_FILLED_LATE = "filled_late"


class OrderGap(Base):
    __tablename__ = "order_gaps"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_order_gaps_order_id"),
        CheckConstraint(
            "status IN ('open', 'filled_late')", name="ck_order_gaps_status"
        ),
        CheckConstraint(
            "status <> 'filled_late' OR resolved_at IS NOT NULL",
            name="ck_order_gaps_resolved_coherence",
        ),
        Index("ix_order_gaps_detected_on", "detected_on"),
        Index("ix_order_gaps_contract_status", "contract_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_group_id: Mapped[Optional[int]] = mapped_column(Integer)
    contract_id: Mapped[int] = mapped_column(Integer, nullable=False)
    client_id: Mapped[int] = mapped_column(Integer, nullable=False)
    order_number: Mapped[Optional[str]] = mapped_column(String(255))
    ended_on: Mapped[date] = mapped_column(Date, nullable=False)
    detected_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=GAP_STATUS_OPEN
    )
    resolved_order_id: Mapped[Optional[int]] = mapped_column(Integer)
    resolved_order_number: Mapped[Optional[str]] = mapped_column(String(255))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
