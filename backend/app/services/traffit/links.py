"""Entity-link lookup and API-facing synchronization state projection."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.traffit_integration import (
    TraffitEntityLink,
    TraffitOutboxEvent,
    TraffitSyncConflict,
)


@dataclass(frozen=True)
class EntitySyncState:
    status: str
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    traffit_id: Optional[str] = None
    traffit_url: Optional[str] = None
    conflict_id: Optional[int] = None
    pending_event_id: Optional[int] = None

    def as_dict(self) -> dict:
        return asdict(self)

    def as_api_dict(self) -> dict:
        """Project the internal ledger state onto IntegrationSyncState."""
        allowed = {
            "synced",
            "pending",
            "conflict",
            "error",
            "manual_action_required",
        }
        state = self.status
        if state not in allowed:
            state = "pending" if state in {"active"} else "error"
        return {
            "system": "traffit",
            "state": state,
            "external_id": self.traffit_id,
            "remote_url": self.traffit_url,
            "last_synced_at": self.last_synced_at,
            "pending_events": int(self.pending_event_id is not None),
            "conflict_id": self.conflict_id,
            "message": self.last_error,
        }


async def get_entity_link(
    db: AsyncSession,
    entity_type: str,
    nexus_id: int,
) -> Optional[TraffitEntityLink]:
    return await db.scalar(
        select(TraffitEntityLink).where(
            TraffitEntityLink.entity_type == entity_type,
            TraffitEntityLink.nexus_entity_id == nexus_id,
        )
    )


def _traffit_url(entity_type: str, remote_id: Optional[str]) -> Optional[str]:
    tenant = os.environ.get("TRAFFIT_TENANT")
    if not tenant or not remote_id:
        return None
    # Traffit UI routes can vary by tenant/version. Candidate is the only
    # stable deep link; other entities point to the tenant home page.
    if entity_type == "candidate":
        return f"https://{tenant}.traffit.com/employees/{remote_id}"
    return f"https://{tenant}.traffit.com"


async def integration_sync_state(
    db: AsyncSession,
    entity_type: str,
    nexus_id: int,
) -> EntitySyncState:
    states = await integration_sync_states(db, [(entity_type, nexus_id)])
    return states[(entity_type, nexus_id)]


def _project_state(
    entity_type: str,
    link: Optional[TraffitEntityLink],
    conflict: Optional[TraffitSyncConflict],
    event: Optional[TraffitOutboxEvent],
) -> EntitySyncState:
    remote_id = link.traffit_entity_id if link else None
    if conflict is not None:
        return EntitySyncState(
            status=(
                "manual_action_required"
                if conflict.status == "manual_action_required"
                else "conflict"
            ),
            last_synced_at=link.last_synced_at if link else None,
            last_error=link.last_error if link else None,
            traffit_id=remote_id,
            traffit_url=_traffit_url(entity_type, remote_id),
            conflict_id=conflict.id,
        )

    if event is not None and event.status in {
        "pending",
        "retry",
        "processing",
        "dry_run",
        "shadowed",
    }:
        return EntitySyncState(
            status="pending",
            last_synced_at=link.last_synced_at if link else None,
            traffit_id=remote_id,
            traffit_url=_traffit_url(entity_type, remote_id),
            pending_event_id=event.id,
        )
    if event is not None and event.status in {"manual_action_required"}:
        return EntitySyncState(
            status="manual_action_required",
            last_synced_at=link.last_synced_at if link else None,
            last_error=event.last_error,
            traffit_id=remote_id,
            traffit_url=_traffit_url(entity_type, remote_id),
            pending_event_id=event.id,
        )
    if event is not None and event.status == "dead_letter":
        return EntitySyncState(
            status="error",
            last_synced_at=link.last_synced_at if link else None,
            last_error=event.last_error,
            traffit_id=remote_id,
            traffit_url=_traffit_url(entity_type, remote_id),
            pending_event_id=event.id,
        )
    if link is None:
        return EntitySyncState(status="pending")
    return EntitySyncState(
        status="synced" if link.status == "synced" else link.status,
        last_synced_at=link.last_synced_at,
        last_error=link.last_error,
        traffit_id=link.traffit_entity_id,
        traffit_url=_traffit_url(entity_type, link.traffit_entity_id),
    )


async def integration_sync_states(
    db: AsyncSession,
    entities: list[tuple[str, int]],
) -> dict[tuple[str, int], EntitySyncState]:
    """Bulk projection used by list endpoints; performs three queries total."""
    keys = list(dict.fromkeys(entities))
    if not keys:
        return {}
    links = list(
        (
            await db.scalars(
                select(TraffitEntityLink).where(
                    tuple_(
                        TraffitEntityLink.entity_type,
                        TraffitEntityLink.nexus_entity_id,
                    ).in_(keys)
                )
            )
        ).all()
    )
    link_by_key = {
        (row.entity_type, int(row.nexus_entity_id)): row
        for row in links
        if row.nexus_entity_id is not None
    }
    conflicts = list(
        (
            await db.scalars(
                select(TraffitSyncConflict)
                .where(
                    tuple_(
                        TraffitSyncConflict.entity_type,
                        TraffitSyncConflict.nexus_entity_id,
                    ).in_(keys),
                    TraffitSyncConflict.status.in_(
                        ("open", "manual_action_required")
                    ),
                )
                .order_by(TraffitSyncConflict.id.desc())
            )
        ).all()
    )
    conflict_by_key: dict[tuple[str, int], TraffitSyncConflict] = {}
    for row in conflicts:
        if row.nexus_entity_id is not None:
            conflict_by_key.setdefault(
                (row.entity_type, int(row.nexus_entity_id)), row
            )

    candidate_ids = [entity_id for kind, entity_id in keys if kind == "candidate"]
    event_filter = tuple_(
        TraffitOutboxEvent.aggregate_type,
        TraffitOutboxEvent.aggregate_id,
    ).in_(keys)
    if candidate_ids:
        event_filter = or_(
            event_filter,
            TraffitOutboxEvent.candidate_id.in_(candidate_ids),
        )
    events = list(
        (
            await db.scalars(
                select(TraffitOutboxEvent)
                .where(event_filter)
                .order_by(TraffitOutboxEvent.id.desc())
            )
        ).all()
    )
    event_by_key: dict[tuple[str, int], TraffitOutboxEvent] = {}
    requested = set(keys)
    for row in events:
        aggregate_key = (row.aggregate_type, int(row.aggregate_id))
        if aggregate_key in requested:
            event_by_key.setdefault(aggregate_key, row)
        if row.candidate_id is not None:
            candidate_key = ("candidate", int(row.candidate_id))
            if candidate_key in requested:
                event_by_key.setdefault(candidate_key, row)

    return {
        key: _project_state(
            key[0],
            link_by_key.get(key),
            conflict_by_key.get(key),
            event_by_key.get(key),
        )
        for key in keys
    }
