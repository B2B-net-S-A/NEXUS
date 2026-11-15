"""Durable state for the bidirectional Traffit integration.

The integration deliberately keeps lifecycle values in ``VARCHAR`` columns
instead of PostgreSQL enums.  Integration workers evolve independently from
the core ATS domain and must be able to introduce a new retry/dead-letter
state without a blocking enum migration.

The tables in this module are transport-agnostic persistence primitives:

* entity links keep the three-way-merge baseline and source identities,
* inbox rows make webhook delivery durable and idempotent.

Pozostałe tabele z 0173 (outbox, konflikty, przebiegi i fazy synchronizacji,
dzierżawy, przełączniki) kod tylko deklarował, a na produkcji nie dostały ani
jednego wiersza; modele zdjęte 15.11.2026, tabele kasuje osobna migracja.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class TraffitEntityLink(Base, TimestampMixin):
    """Stable Nexus↔Traffit identity and three-way-merge baseline."""

    __tablename__ = "traffit_entity_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    entity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    nexus_entity_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    traffit_entity_id: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )

    # active | pending | conflict | error | manual_action_required | detached
    status: Mapped[str] = mapped_column(
        String(40), nullable=False, default="active", server_default="active"
    )
    base_snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    # Hash kontraktu pól, z którym zbudowano base_snapshot — zmiana schematu
    # tenanta unieważnia bazę do 3-way merge zamiast cicho porównywać
    # nieporównywalne projekcje.
    base_schema_hash: Mapped[Optional[str]] = mapped_column(String(64))
    nexus_snapshot_hash: Mapped[Optional[str]] = mapped_column(String(64))
    traffit_snapshot_hash: Mapped[Optional[str]] = mapped_column(String(64))

    nexus_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    traffit_updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    missing_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    missing_strikes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    source_deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    pending_delete_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_direction: Mapped[Optional[str]] = mapped_column(String(20))
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        Index(
            "ux_traffit_entity_links_nexus",
            "entity_type",
            "nexus_entity_id",
            unique=True,
            postgresql_where=text("nexus_entity_id IS NOT NULL"),
        ),
        Index(
            "ux_traffit_entity_links_remote",
            "entity_type",
            "traffit_entity_id",
            unique=True,
            postgresql_where=text("traffit_entity_id IS NOT NULL"),
        ),
        Index(
            "ix_traffit_entity_links_candidate_status",
            "candidate_id",
            "status",
        ),
        Index("ix_traffit_entity_links_last_seen", "entity_type", "last_seen_at"),
    )


class TraffitWebhookEvent(Base, TimestampMixin):
    """Durable, deduplicated inbox row for a Traffit webhook signal."""

    __tablename__ = "traffit_webhook_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    subscription_id: Mapped[str] = mapped_column(String(100), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    remote_entity_type: Mapped[Optional[str]] = mapped_column(String(50))
    remote_entity_id: Mapped[Optional[str]] = mapped_column(String(255))
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # pending | processing | retry | succeeded | dead_letter | ignored
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8, server_default="8"
    )
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), default=func.now(), server_default=func.now()
    )
    locked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[Optional[str]] = mapped_column(String(255))
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(Text)

    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "dedupe_key", name="uq_traffit_webhook_dedupe"
        ),
        Index(
            "ix_traffit_webhook_due",
            "next_attempt_at",
            "id",
            postgresql_where=text("status IN ('pending', 'retry')"),
        ),
        Index(
            "ix_traffit_webhook_remote_entity",
            "remote_entity_type",
            "remote_entity_id",
        ),
    )
