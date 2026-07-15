"""Database-backed leader lease for multi-replica integration workers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traffit_integration import IntegrationLease


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class LeaseResult:
    acquired: bool
    generation: Optional[int] = None
    expires_at: Optional[datetime] = None


async def acquire_lease(
    db: AsyncSession,
    *,
    name: str,
    holder_id: str,
    ttl: timedelta = timedelta(seconds=90),
    metadata: Optional[dict[str, Any]] = None,
) -> LeaseResult:
    """Acquire/renew a fenced lease. Caller commits the transaction."""
    now = _utcnow()
    row = await db.scalar(
        select(IntegrationLease)
        .where(IntegrationLease.name == name)
        .with_for_update()
    )
    if row is None:
        row = IntegrationLease(
            name=name,
            holder_id=holder_id,
            acquired_at=now,
            heartbeat_at=now,
            expires_at=now + ttl,
            generation=1,
            lease_metadata=metadata or {},
        )
        db.add(row)
        try:
            await db.flush()
        except IntegrityError:
            # Another replica inserted between SELECT and INSERT.
            await db.rollback()
            return LeaseResult(False)
        return LeaseResult(True, row.generation, row.expires_at)

    if row.holder_id != holder_id and row.expires_at > now:
        return LeaseResult(False, row.generation, row.expires_at)
    if row.holder_id != holder_id:
        row.generation += 1
        row.acquired_at = now
    row.holder_id = holder_id
    row.heartbeat_at = now
    row.expires_at = now + ttl
    row.lease_metadata = metadata or row.lease_metadata or {}
    await db.flush()
    return LeaseResult(True, row.generation, row.expires_at)


async def heartbeat_lease(
    db: AsyncSession,
    *,
    name: str,
    holder_id: str,
    generation: int,
    ttl: timedelta = timedelta(seconds=90),
) -> bool:
    row = await db.scalar(
        select(IntegrationLease)
        .where(IntegrationLease.name == name)
        .with_for_update()
    )
    now = _utcnow()
    if (
        row is None
        or row.holder_id != holder_id
        or row.generation != generation
        or row.expires_at <= now
    ):
        return False
    row.heartbeat_at = now
    row.expires_at = now + ttl
    await db.flush()
    return True


async def release_lease(
    db: AsyncSession,
    *,
    name: str,
    holder_id: str,
    generation: int,
) -> bool:
    row = await db.scalar(
        select(IntegrationLease)
        .where(IntegrationLease.name == name)
        .with_for_update()
    )
    if row is None or row.holder_id != holder_id or row.generation != generation:
        return False
    row.expires_at = _utcnow()
    await db.flush()
    return True

