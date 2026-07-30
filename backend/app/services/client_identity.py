"""Shared client naming and lifecycle visibility policy.

Client ``status`` describes the operational lifecycle and does not decide
whether a record is globally visible.  Canonicalisation uses the independent
``hidden`` / ``archived_at`` / ``merged_into_client_id`` fields instead.
"""

from __future__ import annotations

from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client


def client_display_name_expression(model: type[Client] = Client) -> Any:
    """Return the SQL expression used for every user-facing client name."""

    return func.coalesce(
        func.nullif(func.btrim(model.display_name), ""),
        model.name,
    )


def client_display_name(client: Client) -> str:
    """Return the NEXUS-owned display name, falling back to the source name."""

    return (client.display_name or "").strip() or client.name


def visible_client_predicates(model: type[Client] = Client) -> tuple[Any, ...]:
    """SQL predicates for records that may be exposed outside admin tooling."""

    return (
        model.hidden.is_(False),
        model.archived_at.is_(None),
        model.merged_into_client_id.is_(None),
    )


def is_client_visible(client: Client) -> bool:
    """In-memory equivalent of :func:`visible_client_predicates`."""

    return (
        not client.hidden
        and client.archived_at is None
        and client.merged_into_client_id is None
    )


async def resolve_visible_client(
    db: AsyncSession,
    client_id: int,
    *,
    follow_merge: bool = False,
) -> Optional[Client]:
    """Load a visible client and optionally follow its canonical merge target.

    Merge chains are not expected, but following them defensively prevents a
    stale foreign key from revealing an intermediate duplicate.  A broken
    target or cycle fails closed.
    """

    current_id = client_id
    visited: set[int] = set()
    while current_id not in visited:
        visited.add(current_id)
        client = await db.scalar(select(Client).where(Client.id == current_id))
        if client is None:
            return None
        if client.merged_into_client_id is not None:
            if not follow_merge:
                return None
            current_id = client.merged_into_client_id
            continue
        return client if is_client_visible(client) else None
    return None
