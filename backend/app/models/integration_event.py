"""Zdarzenia i webhooki API integracyjnego v1 (migracja 0448).

Trzy tabele:

* ``integration_event_outbox`` — poczekalnia. Listener ORM
  (``services/integration_events.py``) dopisuje tu wiersz w TEJ SAMEJ
  transakcji co zmiana biznesowa, więc wycofana zmiana nie zostawia zdarzenia.
* ``integration_events`` — kanał. ``id`` to kursor (``GET /events?after=``).
  Wiersze przenosi z poczekalni wyłącznie pętla w tle (``publish_pending``)
  pod blokadą doradczą, jedną transakcją na partię. Dlatego kursor nie ma
  dziur „na później”: gdyby ``id`` nadawał sam listener, transakcja z ``id=101``
  mogłaby się zatwierdzić PO transakcji z ``id=102`` — integrator, który już
  przeczytał 102 i przesunął kursor, nigdy nie zobaczyłby 101.
* ``integration_webhooks`` — subskrypcje kont serwisowych: adres, sekret
  podpisu (zaszyfrowany Fernetem — do podpisu potrzebny jest jawny sekret, więc
  skrót nie wystarcza), kursor dostarczenia i stan ponowień.

Zdarzenie niesie typ, czas i same identyfikatory (``refs``) — bez danych
osobowych i kwot. ``scope`` to uprawnienie klucza potrzebne, żeby je zobaczyć.
Retencja kanału: 30 dni (``EVENT_RETENTION_DAYS``), sprząta pętla webhooków.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

EVENT_RETENTION_DAYS = 30


class IntegrationEventOutbox(Base):
    """Zdarzenie zapisane w transakcji zmiany, jeszcze bez kursora."""

    __tablename__ = "integration_event_outbox"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    refs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IntegrationEvent(Base):
    """Zdarzenie w kanale v1; ``id`` = kursor rosnący w kolejności publikacji."""

    __tablename__ = "integration_events"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(refs) = 'object'", name="ck_integration_events_refs_object"
        ),
        Index("ix_integration_events_type_id", "type", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    type: Mapped[str] = mapped_column(String(64), nullable=False)
    scope: Mapped[str] = mapped_column(String(64), nullable=False)
    refs: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default="{}"
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    # Czas wejścia do kanału — rośnie razem z ``id`` (partie są szeregowane),
    # więc retencja tnie po nim zakresem kursora.
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class IntegrationWebhook(Base):
    """Subskrypcja zdarzeń konta serwisowego (adres ``https://`` + sekret)."""

    __tablename__ = "integration_webhooks"
    __table_args__ = (
        CheckConstraint(
            "jsonb_typeof(event_types) = 'array'",
            name="ck_integration_webhooks_event_types_array",
        ),
        Index("ix_integration_webhooks_account", "service_account_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    service_account_id: Mapped[int] = mapped_column(
        ForeignKey("service_accounts.id", ondelete="CASCADE"), nullable=False
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    # Fernet (``core.encryption.get_token_cipher``); jawny sekret jest w
    # odpowiedzi na utworzenie RAZ i nigdzie więcej.
    secret_ct: Mapped[str] = mapped_column(Text, nullable=False)
    # Pusta lista = wszystkie typy, które konto może zobaczyć.
    event_types: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Kursor dostarczenia: ostatnie ``integration_events.id`` przyjęte (2xx)
    # albo pominięte jako niewidoczne dla konta.
    last_event_id: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    failure_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Rezerwacja wysyłki (dwa procesy w czasie wdrożenia nie wysyłają razem).
    lease_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    test_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    disabled_reason: Mapped[Optional[str]] = mapped_column(String(255))
    disabled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_delivery_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # Kod HTTP ostatniej próby (``None`` = brak odpowiedzi) i krótki powód porażki.
    last_status: Mapped[Optional[int]] = mapped_column(Integer)
    last_error: Mapped[Optional[str]] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = [
    "EVENT_RETENTION_DAYS",
    "IntegrationEvent",
    "IntegrationEventOutbox",
    "IntegrationWebhook",
]
