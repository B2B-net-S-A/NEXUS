"""Durable indexing outbox (plan PR5).

One row per pending "reindex this entity" intent, enqueued in the same
transaction as the source change so an embedding update can never be silently
lost. A background worker drains it: builds the document + content hash in the
application (never in PL/pgSQL), upserts/deletes the vector, and records the
``indexed_hash``/``indexed_revision`` so ``desired_hash == indexed_hash`` is a
measurable freshness contract.

State machine: ``pending`` → ``processing`` → ``done`` | ``failed`` → (after
``AI_INDEX_MAX_ATTEMPTS``) ``dead``. ``operation`` is ``upsert`` or ``delete``
(delete writes a Qdrant tombstone so a removed/ineligible entity does not
linger in the index).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

OUTBOX_STATUSES = ("pending", "processing", "done", "failed", "dead")
OUTBOX_OPERATIONS = ("upsert", "delete")


class IndexOutboxEvent(Base):
    __tablename__ = "match_index_outbox"
    __table_args__ = (
        # Worker polls pending/failed events oldest-first; this covers it.
        Index(
            "ix_match_index_outbox_pending",
            "status",
            "created_at",
        ),
        Index(
            "ix_match_index_outbox_entity",
            "entity_type",
            "entity_id",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # candidate|job
    entity_id: Mapped[int] = mapped_column(Integer, nullable=False)
    # Monotonic per-entity revision (epoch micros of updated_at at enqueue). The
    # worker skips an event whose revision is older than what it already indexed.
    entity_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    desired_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="upsert"
    )

    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="pending", index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)

    indexed_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    indexed_revision: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
