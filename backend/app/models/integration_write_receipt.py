"""Paragon zapisu przez API integracyjne v1 (migracja 0442).

Dwie role w jednej tabeli:

* **Idempotencja.** Każdy zapis v1 niesie nagłówek ``Idempotency-Key``.
  Automatyzacja, która po zerwanym połączeniu ponowi żądanie (a wdrożenia
  NEXUSA w nocy dają ~2 min przerwy), dostaje zapisaną odpowiedź zamiast
  drugiego importu MD albo drugiej faktury. Ten sam klucz z INNĄ treścią to
  409 — inaczej powtórka cicho zignorowałaby nowe dane.
* **Rejestr „co zapisała automatyzacja”.** Ekran „Klucze API” pokazuje
  z tej tabeli ostatnie zapisy konta, bez grzebania w logach.

``state='pending'`` jest wstawiany w TEJ SAMEJ transakcji co zmiana
biznesowa, więc zmiana bez paragonu (albo paragon bez zmiany) nie istnieje.
Odpowiedź (``response_json``) dopisuje się w następnej transakcji.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

RECEIPT_PENDING = "pending"
RECEIPT_DONE = "done"


class IntegrationWriteReceipt(Base):
    __tablename__ = "integration_write_receipts"
    __table_args__ = (
        UniqueConstraint(
            "service_account_id",
            "idempotency_key",
            name="uq_integration_write_receipts_account_key",
        ),
        CheckConstraint(
            "state IN ('pending', 'done')",
            name="ck_integration_write_receipts_state",
        ),
        Index(
            "ix_integration_write_receipts_account_created",
            "service_account_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_account_id: Mapped[int] = mapped_column(
        ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=False
    )
    # Jawne id klucza (``v2$<hex>``), nie sekret — wolno je przechowywać.
    key_id: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(80), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    # Szablon trasy (``/api/integrations/v1/invoices/{invoice_id}``), nie ścieżka
    # z wartościami — do grupowania na ekranie.
    route: Mapped[str] = mapped_column(String(255), nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default=RECEIPT_PENDING, server_default="pending"
    )
    status_code: Mapped[Optional[int]] = mapped_column(Integer)
    response_json: Mapped[Optional[Any]] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
