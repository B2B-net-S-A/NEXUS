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

Jedno zamówienie może mieć KILKA braków — po jednym na datę końca
(``ux_order_gaps_order_ended``, runda 10 audytu, R10-N4-1). Zamówienie
przedłużone po fakcie uzupełnia swój brak (``filled_late``), a gdy nowa data
końca też minie bez następcy, powstaje drugi brak z tą nową datą. Do rundy 10
UNIQUE(order_id) blokował drugi wpis i osoba zostawała bez Braku i bez karty
DL na zawsze.

``episode`` liczy przywrócenia braku na ``open`` (następca zniknął albo
przedłużenie cofnięto). Wchodzi do klucza odhaczenia w Finansach — bez niego
przywrócony brak dziedziczył „Zrobione" z poprzedniego epizodu (R10-N4-3).
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
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

GAP_STATUS_OPEN = "open"
GAP_STATUS_FILLED_LATE = "filled_late"


class OrderGap(Base):
    __tablename__ = "order_gaps"
    __table_args__ = (
        Index("ux_order_gaps_order_ended", "order_id", "ended_on", unique=True),
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
    episode: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
