"""Fail-closed owner eligibility checks for Microsoft 365 operations.

An active ``M365Connection`` is only a credential record.  It must never be
treated as current authorization: the owning Nexus user can move to Finance or
the legacy viewer role while tokens, subscriptions and queued work still
exist.  Every Graph execution path re-reads the owner and applies the same
candidate-domain boundary used by the HTTP API.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import user_can_access_candidate_domain
from app.models.m365 import M365Connection
from app.models.user import User


class M365OwnerIneligible(RuntimeError):
    """Raised before Graph access when the connection owner is not eligible."""


async def eligible_m365_owner(db: AsyncSession, user_id: int) -> User | None:
    """Return the current eligible owner, or ``None`` without mutating state."""

    # ``populate_existing`` forces a SELECT even when this session already has
    # the user in its identity map. Role changes happen in other requests and
    # a cached pre-cutover User object must not authorize a Graph call.
    owner = await db.get(User, user_id, populate_existing=True)
    if owner is None or not user_can_access_candidate_domain(owner):
        return None
    return owner


async def connection_owner_is_eligible(
    db: AsyncSession,
    connection: M365Connection,
) -> bool:
    """Check an M365 connection against its owner's current effective roles."""

    return await eligible_m365_owner(db, connection.user_id) is not None


async def require_eligible_connection_owner(
    db: AsyncSession,
    connection: M365Connection,
) -> User:
    """Fail before token/Graph use when the current owner cannot access PII."""

    owner = await eligible_m365_owner(db, connection.user_id)
    if owner is None:
        raise M365OwnerIneligible(
            f"M365 connection {connection.id} owner is outside candidate domain"
        )
    return owner
