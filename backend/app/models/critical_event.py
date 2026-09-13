"""Historia zdarzeń — dziennik krytycznych operacji w systemie (0307).

Jeden wiersz = jedna operacja albo jedna ZABLOKOWANA próba: kto, kiedy, na
jakim obiekcie, z jakim wynikiem i z jakiego powodu. Na start: usunięcia
klientów, kontraktorów/konsultantów, kontraktów, umów i zamówień.

Tabela celowo nie ma kluczy obcych. Wpis musi przeżyć usunięcie obiektu, którego
dotyczy (to jest jego sens), i konta osoby, która go wykonała — dlatego nazwy
są zdenormalizowane w chwili zapisu. Brak FK ma też skutek operacyjny:
zablokowaną próbę zapisujemy z OSOBNEJ sesji (żądanie, które odmawia, jest
wycofywane), a wstawienie bez FK nigdy nie czeka na blokady trzymane przez to
żądanie.
"""

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CriticalEvent(Base):
    __tablename__ = "critical_events"
    __table_args__ = (
        CheckConstraint(
            "outcome IN ('executed', 'blocked')",
            name="ck_critical_events_outcome",
        ),
        Index("ix_critical_events_occurred_at", "occurred_at"),
        Index("ix_critical_events_entity", "entity_type", "entity_id"),
        Index("ix_critical_events_client_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Rodzaj operacji, np. ``client.delete``, ``contract.delete``.
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # Kategoria obiektu do filtrowania: client | contractor | contract |
    # agreement | order | user.
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_id: Mapped[Optional[int]] = mapped_column(Integer)
    # Czytelny opis obiektu W CHWILI zdarzenia — obiektu może już nie być.
    entity_label: Mapped[Optional[str]] = mapped_column(String(500))
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[Optional[str]] = mapped_column(String(64))
    reason: Mapped[Optional[str]] = mapped_column(Text)
    actor_user_id: Mapped[Optional[int]] = mapped_column(Integer)
    actor_name: Mapped[Optional[str]] = mapped_column(String(255))
    actor_email: Mapped[Optional[str]] = mapped_column(String(255))
    # Klient, którego operacja dotyczy (także pośrednio — zamówienie, umowa).
    client_id: Mapped[Optional[int]] = mapped_column(Integer)
    client_name: Mapped[Optional[str]] = mapped_column(String(255))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"),
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
