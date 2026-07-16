"""Watermark / run-state for the scheduled Traffit → Nexus sync.

One row per logical phase (``candidates``, ``jobs``, …) plus two scheduler
marker rows: ``__daily__`` (gates + provides the ``updated_at`` watermark for
the daily delta) and ``__full__`` (gates the weekly full reconcile).

The watermark is *persisted* (not an in-memory timer) so the loop is
restart-safe — Coolify rebuilds the container on every push to ``main``, and we
must NOT re-trigger a multi-hour import on each deploy. The loop reads
``last_run_finished_at`` from here to decide whether a run is due.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class TraffitSyncState(Base, TimestampMixin):
    __tablename__ = "traffit_sync_state"

    # Phase name or scheduler marker (``__daily__`` / ``__full__``).
    phase: Mapped[str] = mapped_column(String(50), primary_key=True)

    # High-water mark used to compute the next delta's ``updated_at >= since``.
    last_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Optional id-based watermark for append-only feeds (reserved; not all
    # phases use it).
    last_max_external_id: Mapped[Optional[int]] = mapped_column(BigInteger)

    last_run_started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    last_run_finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    # "ok" | "errors" | "error" | "running"
    last_status: Mapped[Optional[str]] = mapped_column(String(20))
    # Last run's per-phase stats (PhaseProgress.as_dict() or aggregate).
    stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)

    # ── Integracja dwukierunkowa: kursor per strumień/tryb ──────────────────
    # Wiersz per strumień i tryb (`<stream>:shadow` / `<stream>:live`) —
    # shadow nigdy nie przesuwa kursora live. Timestamp + external id jako
    # deterministyczny tie-breaker; payload trzyma np. shard plikowy.
    cursor_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cursor_external_id: Mapped[Optional[str]] = mapped_column(String(255))
    cursor_payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text)
    next_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<TraffitSyncState phase={self.phase} status={self.last_status} "
            f"finished={self.last_run_finished_at}>"
        )
