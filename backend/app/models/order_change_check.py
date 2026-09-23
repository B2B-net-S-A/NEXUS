"""Odhaczenia zmian w zamówieniach i pobrania PDF-ów zamówień (0353).

Finanse → „Zmiany w zamówieniach": każda pozycja audytu (zmiana stawki,
nowe zamówienie, zejście, brak…) dostaje checkbox „Zrobione". Odhaczenie jest
AUDYTEM, nie flagą: tabela jest dopisywana (``checked`` / ``unchecked``),
a bieżący stan pozycji to jej ostatni wpis. Cofnięcie zostawia ślad tak samo
jak odhaczenie, a miniony miesiąc pokazuje, kto i kiedy co zrobił.

Pozycja jest identyfikowana ``item_key`` liczonym przy odczycie
(``services/order_change_checks.item_key``) — wpis w dzienniku zmian ma
własne id, a pozycje liczone z bieżącego stanu zamówień (wejście, zejście,
brak) niosą w kluczu to, co je wyróżnia (np. datę końca). Ponowna zmiana
zamówienia daje więc NOWY klucz, czyli nową pozycję „Do zrobienia", a stare
odhaczenie zostaje w historii.

Bez kluczy obcych do zamówień i użytkowników — ślad ma przeżyć usunięcie
zamówienia i konta (imię osoby jest zapisane obok id).

Finanse → „Zamówienia PDF": ``order_pdf_downloads`` pamięta, kto pobrał który
plik. Status „Nowy / Pobrane przez Ciebie" jest osobny dla każdej osoby,
a podmiana pliku (inna ścieżka w magazynie) przywraca „Nowy".
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CHECK_TABS: tuple[str, ...] = ("changes", "entries", "exits", "ending", "gaps")
ACTION_CHECKED = "checked"
ACTION_UNCHECKED = "unchecked"


class OrderChangeCheck(Base):
    __tablename__ = "order_change_checks"
    __table_args__ = (
        CheckConstraint(
            "action IN ('checked', 'unchecked')",
            name="ck_order_change_checks_action",
        ),
        CheckConstraint(
            "tab IN ('changes', 'entries', 'exits', 'ending', 'gaps')",
            name="ck_order_change_checks_tab",
        ),
        CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="ck_order_change_checks_month",
        ),
        Index("ix_order_change_checks_key", "item_key", "id"),
        Index("ix_order_change_checks_period", "period_year", "period_month"),
        Index("ix_order_change_checks_order", "order_id"),
        Index("ix_order_change_checks_group", "order_group_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_key: Mapped[str] = mapped_column(String(160), nullable=False)
    tab: Mapped[str] = mapped_column(String(16), nullable=False)
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)
    order_id: Mapped[Optional[int]] = mapped_column(Integer)
    order_group_id: Mapped[Optional[int]] = mapped_column(Integer)
    client_id: Mapped[Optional[int]] = mapped_column(Integer)
    # Opis pozycji z chwili odhaczenia — pozycja liczona z bieżącego stanu
    # (np. zejście ze starą datą końca) potrafi zniknąć po ponownej zmianie,
    # a historia ma nadal mówić, CO zostało zrobione.
    summary: Mapped[str] = mapped_column(String(400), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(Integer)
    user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


PDF_FILE_KINDS: tuple[str, ...] = ("order", "group", "amendment")


class OrderPdfDownload(Base):
    __tablename__ = "order_pdf_downloads"
    __table_args__ = (
        CheckConstraint(
            "file_kind IN ('order', 'group', 'amendment')",
            name="ck_order_pdf_downloads_kind",
        ),
    )

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    file_kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    file_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Ścieżka pliku z chwili pobrania — podmieniony PDF ma inną ścieżkę,
    # więc wraca jako „Nowy".
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    downloaded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
