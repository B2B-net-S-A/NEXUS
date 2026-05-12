"""Osoba kontaktowa w firmie klienta + nasza relacja (DL/TAC ↔ contact).

Refactor 2026-05-11: dodane pola "key relationship" — DL na bieżąco buduje
relacje z ludźmi u klientów, niektóre osoby to "key relationships" (relacja
DL z osobą, nie jej pozycja w firmie). Różne semantycznie od
`is_decision_maker`.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RelationshipStrength(str, enum.Enum):
    """Siła naszej (DL/TAC) relacji z osobą kontaktową u klienta.

    Różne semantycznie od `is_decision_maker` (dotyczy hierarchii w firmie
    klienta, nie naszej relacji).
    """

    cold = "cold"  # Wymiana maili biznesowych, brak więzi
    warm = "warm"  # Pamiętają nas, odpowiadają chętnie
    strong = "strong"  # Spotkania osobiste, znamy się dobrze
    champion = "champion"  # Wewnętrzny ambasador, poleca nas dalej


class Contact(Base):
    """Osoba kontaktowa w firmie klienta + nasza relacja z nią."""

    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[Optional[str]] = mapped_column(String(255))
    phone: Mapped[Optional[str]] = mapped_column(String(50))
    position: Mapped[Optional[str]] = mapped_column(String(255))
    department: Mapped[Optional[str]] = mapped_column(String(255))

    is_decision_maker: Mapped[bool] = mapped_column(Boolean, default=False)
    notes: Mapped[Optional[str]] = mapped_column(Text)
    last_contacted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )

    # ── Key relationship fields (migracja 0096, 2026-05-11) ─────────────────
    is_key_relationship: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    relationship_strength: Mapped[Optional[RelationshipStrength]] = mapped_column(
        Enum(
            RelationshipStrength,
            name="relationshipstrength",
            create_type=False,
        ),
        nullable=True,
    )
    relationship_notes: Mapped[Optional[str]] = mapped_column(Text)
    """Długi opis relacji — birthdays, hobby, jak rozmawiać, mieszka gdzie,
    rodzina, ulubione miejsca, gift preferences."""

    key_relationship_owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    """DL/TAC który zbudował relację — używane w `/my-relationships` filter."""

    last_personal_touchpoint_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    """Kiedy ostatnio "kawa razem", rozmowa o dzieciach. Osobne semantycznie
    od `last_contacted_at` (każdy kontakt biznesowy)."""

    # External source tracking — Traffit / future imports.
    # Migracja 0071 dodaje partial unique index na (external_source, external_id).
    external_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", index=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    client = relationship("Client", backref="contacts")
    key_relationship_owner = relationship(
        "User", foreign_keys=[key_relationship_owner_id]
    )

    def __repr__(self) -> str:
        return f"<Contact id={self.id} name={self.name} client_id={self.client_id}>"
