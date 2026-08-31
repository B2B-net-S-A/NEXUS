"""Zużycie MD: miesięczna konsumpcja linii + partie importu z modułu Finanse.

Budżet MD linii konsultanta topnieje wraz z miesięcznymi raportami z Finansów.
Konsumpcja jest przechowywana per (linia, miesiąc) z UNIQUE — i to ten klucz,
a nie ostrożność w kodzie, czyni import idempotentnym: powtórny import tego
samego miesiąca NADPISUJE wiersz i każe przeliczyć pozostałość od
``md_total``, zamiast odjąć MD po raz drugi.

Plik z Finansów nie zawiera numeru zamówienia — dopasowanie idzie wyłącznie po
imieniu i nazwisku. Dlatego wiersz importu ŻYJE DALEJ po zakończeniu importu:
gdy nazwisko pasuje do więcej niż jednej aktywnej linii, system nie zgaduje,
tylko zostawia wiersz w stanie „wymaga przypisania" do ręcznego rozstrzygnięcia.
Bez trwałego wiersza taka informacja przepadłaby razem z odpowiedzią HTTP,
a zaraportowane MD nigdy nie trafiłyby na żadną linię.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin

# 'YYYY-MM'. Kształt wymuszony w bazie, bo miesiąc jest częścią klucza
# idempotencji: '2026-7' i '2026-07' to dwa różne stringi, czyli dwa wiersze
# na ten sam miesiąc i podwójnie odjęte MD.
_PERIOD_MONTH_CHECK = "period_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$'"

IMPORT_ROW_APPLIED = "applied"
IMPORT_ROW_NEEDS_ASSIGNMENT = "needs_assignment"
IMPORT_ROW_UNMATCHED = "unmatched"
IMPORT_ROW_STATUSES: tuple[str, ...] = (
    IMPORT_ROW_APPLIED,
    IMPORT_ROW_NEEDS_ASSIGNMENT,
    IMPORT_ROW_UNMATCHED,
)

IMPORT_ROW_STATUS_LABELS: dict[str, str] = {
    IMPORT_ROW_APPLIED: "Zaktualizowano",
    IMPORT_ROW_NEEDS_ASSIGNMENT: "Wymaga przypisania",
    IMPORT_ROW_UNMATCHED: "Brak aktywnego zamówienia",
}

CONSUMPTION_SOURCE_IMPORT = "import"
CONSUMPTION_SOURCE_MANUAL = "manual"

# Wynik dopasowania KOSZTOWEGO — niezależny od `status`, który opisuje
# dopasowanie MD po nazwisku. Jeden wiersz bywa jednocześnie MD-dopasowany
# i kosztowo-niedopasowany; wciśnięcie obu prawd w jedno pole gubi jedną.
COST_ROW_APPLIED = "applied"
COST_ROW_UNMATCHED_NUMBER = "unmatched_number"
COST_ROW_UNMATCHED_CONSULTANT = "unmatched_consultant"
COST_ROW_STATUSES: tuple[str, ...] = (
    COST_ROW_APPLIED,
    COST_ROW_UNMATCHED_NUMBER,
    COST_ROW_UNMATCHED_CONSULTANT,
)

COST_ROW_STATUS_LABELS: dict[str, str] = {
    COST_ROW_APPLIED: "Rozliczono",
    COST_ROW_UNMATCHED_NUMBER: "Brak zamówienia o tym numerze",
    COST_ROW_UNMATCHED_CONSULTANT: "Numer się zgadza, konsultant nie",
}


class MdConsumptionImport(Base):
    """Jedna partia importu — jeden wgrany plik za jeden miesiąc."""

    __tablename__ = "md_consumption_imports"
    __table_args__ = (
        CheckConstraint(_PERIOD_MONTH_CHECK, name="ck_md_consumption_imports_period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    """Miesiąc raportu w formacie ``YYYY-MM``. Wybierany ręcznie przy imporcie —
    arkusze z Finansów nie niosą go w ustalonym miejscu, a zgadywanie z nazwy
    pliku pomyliłoby się dokładnie wtedy, gdy import dotyczy zaległego okresu."""

    filename: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    rows_total: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    rows_applied: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_ambiguous: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_unmatched: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_cost_applied: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    rows_cost_unmatched: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )

    uploaded_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    uploader = relationship("User", foreign_keys=[uploaded_by_user_id])
    rows = relationship(
        "MdConsumptionImportRow",
        back_populates="import_batch",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="MdConsumptionImportRow.row_number.asc()",
    )

    def __repr__(self) -> str:
        return (
            f"<MdConsumptionImport id={self.id} month={self.period_month!r} "
            f"rows={self.rows_total}>"
        )


class MdConsumptionImportRow(Base):
    """Pojedynczy wiersz arkusza wraz z wynikiem dopasowania."""

    __tablename__ = "md_consumption_import_rows"
    __table_args__ = (
        CheckConstraint(
            "status IN ('applied', 'needs_assignment', 'unmatched')",
            name="ck_md_import_rows_status",
        ),
        CheckConstraint(
            "cost_status IS NULL OR cost_status IN "
            "('applied', 'unmatched_number', 'unmatched_consultant')",
            name="ck_md_import_rows_cost_status",
        ),
        Index("ix_md_import_rows_import", "import_id"),
        Index("ix_md_import_rows_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    import_id: Mapped[int] = mapped_column(
        ForeignKey("md_consumption_imports.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    """Numer wiersza w arkuszu (nagłówek = 1) — żeby operator odnalazł go w pliku."""

    consultant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    md_reported: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)

    status: Mapped[str] = mapped_column(String(24), nullable=False)

    matched_order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )
    candidate_order_ids: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    """Linie do wyboru, gdy dopasowań jest więcej niż jedno. System celowo nie
    wybiera za operatora — trafienie w złe zamówienie odejmuje MD nie temu
    klientowi i wychodzi dopiero na fakturze."""

    notes_raw: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    """Kolumna „Uwagi" dosłownie. Trzymana, bo to JEDYNE miejsce w arkuszu,
    które niesie numer zamówienia — plik nie ma osobnej kolumny na numer."""

    order_number_hint: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    """Ciąg cyfr wyłuskany z „Uwag" („SAP 4500719650" → „4500719650")."""

    invoice_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(17, 3), nullable=True
    )
    """Kolumna „Faktura" — kwota, o którą schodzi budżet kosztowy."""

    matched_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL"), nullable=True
    )
    cost_status: Mapped[Optional[str]] = mapped_column(String(24), nullable=True)
    """``NULL`` = wiersz nie dotyczy rozliczenia kosztowego (brak numeru
    w „Uwagach"). Patrz ``COST_ROW_*``."""

    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    import_batch = relationship("MdConsumptionImport", back_populates="rows")
    matched_order = relationship("ClientOrder", foreign_keys=[matched_order_id])
    matched_group = relationship("ClientOrderGroup", foreign_keys=[matched_group_id])
    resolver = relationship("User", foreign_keys=[resolved_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<MdConsumptionImportRow id={self.id} name={self.consultant_name!r} "
            f"status={self.status!r}>"
        )


class ClientOrderMdConsumption(Base, TimestampMixin):
    """Zaraportowane MD dla jednej linii w jednym miesiącu."""

    __tablename__ = "client_order_md_consumptions"
    __table_args__ = (
        CheckConstraint(
            "source IN ('import', 'manual')", name="ck_md_consumptions_source"
        ),
        CheckConstraint(_PERIOD_MONTH_CHECK, name="ck_md_consumptions_period"),
        Index(
            "ux_md_consumptions_order_month",
            "order_id",
            "period_month",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("client_orders.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    md_reported: Mapped[Decimal] = mapped_column(Numeric(16, 6), nullable=False)

    import_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("md_consumption_imports.id", ondelete="SET NULL"), nullable=True
    )
    """``SET NULL``, nie ``CASCADE`` — skasowanie partii importu nie może cofać
    już zastosowanego zużycia MD. Wpis konsumpcji jest faktem, partia tylko
    jego pochodzeniem."""

    source: Mapped[str] = mapped_column(String(16), nullable=False)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    order = relationship("ClientOrder", back_populates="md_consumptions")
    import_batch = relationship("MdConsumptionImport", foreign_keys=[import_id])
    author = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<ClientOrderMdConsumption order={self.order_id} "
            f"month={self.period_month!r} md={self.md_reported}>"
        )


class ClientOrderInvoiceConsumption(Base, TimestampMixin):
    """Zafakturowana kwota jednej linii w jednym miesiącu (zamówienie kosztowe).

    Lustro ``ClientOrderMdConsumption`` z tym samym UNIQUE ``(order_id,
    period_month)`` — i to ten indeks, a nie ostrożność w kodzie, czyni
    ponowny import miesiąca idempotentnym: powtórka NADPISUJE wiersz i każe
    przeliczyć budżet od ``budget_amount``, zamiast odjąć kwotę drugi raz.

    ``settled_amount`` / ``unsettled_amount`` są ZAPISANE, a nie liczone przy
    odczycie, bo odpowiedź na pytanie „której osobie zabrakło budżetu" zależy
    od kolejności rozliczania. Bez utrwalenia wyniku ta sama baza dawałaby
    różne odpowiedzi przy różnym sortowaniu, a komunikat „brakuje X zł" trafiał
    raz w jedną, raz w drugą osobę.
    """

    __tablename__ = "client_order_invoice_consumptions"
    __table_args__ = (
        CheckConstraint(
            "source IN ('import', 'manual')",
            name="ck_invoice_consumptions_source",
        ),
        CheckConstraint(_PERIOD_MONTH_CHECK, name="ck_invoice_consumptions_period"),
        Index(
            "ux_invoice_consumptions_order_month",
            "order_id",
            "period_month",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    order_id: Mapped[int] = mapped_column(
        ForeignKey("client_orders.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)

    invoice_amount: Mapped[Decimal] = mapped_column(Numeric(17, 3), nullable=False)
    """Kwota z kolumny „Faktura" — pełna, niezależnie od tego, ile się zmieściło.
    To ona sumuje się do pola „Zafakturowano" przy konsultancie."""

    settled_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 3), nullable=False, server_default="0"
    )
    unsettled_amount: Mapped[Decimal] = mapped_column(
        Numeric(17, 3), nullable=False, server_default="0"
    )
    """Część faktury, która nie zmieściła się w budżecie zamówienia."""

    import_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("md_consumption_imports.id", ondelete="SET NULL"), nullable=True
    )
    """``SET NULL``, nie ``CASCADE`` — skasowanie partii importu nie może cofać
    już zastosowanego rozliczenia."""

    source: Mapped[str] = mapped_column(String(16), nullable=False)

    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    order = relationship("ClientOrder", back_populates="invoice_consumptions")
    import_batch = relationship("MdConsumptionImport", foreign_keys=[import_id])
    author = relationship("User", foreign_keys=[created_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<ClientOrderInvoiceConsumption order={self.order_id} "
            f"month={self.period_month!r} amount={self.invoice_amount}>"
        )
