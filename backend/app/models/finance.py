"""Miesięczne wyniki finansowe kontraktorów (moduł „Finanse").

Moduł jest CELOWO odcięty od reszty systemu: „Imię i nazwisko" oraz „Klient"
to wolny tekst z arkusza, bez FK do ``candidates``/``clients``. Import nie
modyfikuje niczego poza tymi dwiema tabelami — dopięcie tych danych do rekordów
kandydatów/klientów jest osobnym zadaniem produktowym.

Dwie tabele, bo plik i jego zawartość mają różne cykle życia:

``FinanceImportRun``
    Jeden wgrany arkusz. Trzyma oryginalny plik (ślad audytowy — pkt 5 ticketu)
    oraz status ``current``/``superseded``. Re-import miesiąca NIE kasuje
    poprzedniej wersji: przestawia ją na ``superseded`` i wstawia nową jako
    ``current``. Dzięki temu „Przywróć jako aktualny" to przestawienie dwóch
    statusów, a nie odtwarzanie danych z pliku.

``FinanceMonthlyResult``
    Wiersze wyników, ZAWSZE związane z konkretnym biegiem importu i nigdy
    nadpisywane w miejscu. To dlatego wersja zastąpiona zachowuje własne ręczne
    poprawki (``edited_fields``) — przywrócenie oddaje dokładnie ten stan,
    w którym ją porzucono.

Świadomie NIE zapisujemy sześciu kolumn arkusza spoza tabeli wynikowej (Uwagi,
Projekt, Stawka z VD, Czy wystawiono fakturę, Data wysłania, Płatny urlop).
Ticket wymaga, żeby nie były pokazywane w żadnym widoku; trzymanie ich
„na wszelki wypadek" w JSONB tworzyłoby stałą powierzchnię wycieku (każda
przyszła serializacja wiersza by je wyniosła) w zamian za nic — oryginalny plik
i tak jest zachowany i pobieralny z Archiwum.
"""

from __future__ import annotations

import enum
from datetime import datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    JSON,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class FinanceImportRunStatus(str, enum.Enum):
    """Która wersja miesiąca obowiązuje.

    W UI: ``current`` → „Aktualny", ``superseded`` → „Zastąpiony".
    """

    current = "current"
    superseded = "superseded"


_RUN_STATUSES = tuple(status.value for status in FinanceImportRunStatus)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class FinanceImportRun(Base, TimestampMixin):
    """Jeden import arkusza za konkretny miesiąc."""

    __tablename__ = "finance_import_runs"
    __table_args__ = (
        # Dokładnie JEDNA aktualna wersja miesiąca. Indeks częściowy zamiast
        # zwykłego UNIQUE, bo wersji zastąpionych może być dowolnie wiele.
        Index(
            "uq_finance_import_runs_current_period",
            "period_year",
            "period_month",
            unique=True,
            postgresql_where=text("status = 'current'"),
            sqlite_where=text("status = 'current'"),
        ),
        Index("ix_finance_import_runs_period", "period_year", "period_month"),
        CheckConstraint(
            f"status IN ({_sql_values(_RUN_STATUSES)})",
            name="ck_finance_import_runs_status",
        ),
        CheckConstraint(
            "period_month BETWEEN 1 AND 12",
            name="ck_finance_import_runs_period_month",
        ),
        CheckConstraint(
            "period_year BETWEEN 2000 AND 2100",
            name="ck_finance_import_runs_period_year",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Okres wybiera CZŁOWIEK przy wgrywaniu — arkusz nie niesie jednoznacznej
    # informacji o miesiącu (pkt 6 ticketu), więc nie zgadujemy go z nazwy pliku.
    period_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_month: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[FinanceImportRunStatus] = mapped_column(
        # native_enum=False → VARCHAR + CHECK zamiast typu PG. Poszerzenie
        # domeny to przepisanie CHECK-a; ALTER TYPE ... ADD VALUE na prodzie
        # potrafi nie wykonać się ponownie (lekcja z migracji 0226).
        Enum(
            FinanceImportRunStatus,
            native_enum=False,
            length=32,
            create_constraint=False,
        ),
        default=FinanceImportRunStatus.current,
        server_default=FinanceImportRunStatus.current.value,
        nullable=False,
        index=True,
    )

    source_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_path: Mapped[str] = mapped_column(String(512), nullable=False)
    # Wyłącznie informacyjnie. CELOWO bez UNIQUE — inaczej poprawka w arkuszu
    # i ponowne wgranie tego samego pliku (najczęstszy scenariusz „Zastąp")
    # rozbijałoby się o indeks.
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    row_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    needs_completion_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    rejected_count: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0", nullable=False
    )
    # Lista {"row_number": int, "reason": str} dla wierszy odrzuconych jako
    # strukturalnie uszkodzone. Do pobrania przez operatora z podsumowania importu.
    rejected_details: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=list,
        server_default="[]",
        nullable=False,
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    creator = relationship("User", lazy="noload")
    rows: Mapped[list["FinanceMonthlyResult"]] = relationship(
        "FinanceMonthlyResult",
        back_populates="import_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FinanceMonthlyResult.row_number",
        lazy="noload",
    )


class FinanceMonthlyResult(Base, TimestampMixin):
    """Jeden wiersz wyników — dokładnie te pola, które pokazuje tabela."""

    __tablename__ = "finance_monthly_results"
    __table_args__ = (
        UniqueConstraint(
            "import_run_id", "row_number", name="uq_finance_monthly_results_row"
        ),
        Index("ix_finance_monthly_results_import_run_id", "import_run_id"),
        CheckConstraint(
            "row_number >= 1", name="ck_finance_monthly_results_row_number"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    import_run_id: Mapped[int] = mapped_column(
        ForeignKey("finance_import_runs.id", ondelete="CASCADE"), nullable=False
    )
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)

    # Wolny tekst z arkusza — bez FK do candidates/clients (pkt 6 ticketu).
    consultant_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Wszystkie kwoty NULLOWALNE. Brak wartości w arkuszu NIE pomija wiersza —
    # wiersz wjeżdża z pustym polem oznaczonym w UI jako „do uzupełnienia"
    # (pkt 4.1 ticketu), a operator uzupełnia je ręcznie w tabeli.
    cost_rate_md: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    md_count: Mapped[Optional[Decimal]] = mapped_column(Numeric(9, 3), nullable=True)
    compensation: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 3), nullable=True
    )
    revenue_rate_md: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    invoice_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(15, 3), nullable=True
    )
    margin_pln: Mapped[Optional[Decimal]] = mapped_column(Numeric(15, 3), nullable=True)
    margin_pct: Mapped[Optional[Decimal]] = mapped_column(Numeric(7, 2), nullable=True)

    # Nazwy pól zmienionych RĘCZNIE po imporcie. Dwa zastosowania:
    #  1. licznik w ostrzeżeniu „Zastąp" — ile ręcznej pracy przepadnie,
    #  2. odróżnienie „pusto, bo import nie dał wartości" (ramka „Uzupełnij")
    #     od „pusto, bo człowiek świadomie wyczyścił".
    edited_fields: Mapped[list[str]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        default=list,
        server_default="[]",
        nullable=False,
    )

    import_run: Mapped["FinanceImportRun"] = relationship(
        "FinanceImportRun", back_populates="rows", lazy="noload"
    )
