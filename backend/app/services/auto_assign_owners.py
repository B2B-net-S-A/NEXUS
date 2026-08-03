"""Resolve safe default owners (sole TAC + head Delivery Lead) for a Job.

Pure resolver — no DB writes. Called from `POST /jobs` to pre-fill `tac_id`
and `delivery_lead_id` when the caller didn't supply them explicitly.

Source of truth:
- all active Client ↔ TAC assignments. A TAC is inferred only when there is
  exactly one; multiple equal TACs require an explicit owner on the new Job.
- `delivery_lead_client_assignments.is_head = TRUE` (app-level guard only;
  resolver uses `.limit(1)` with deterministic ordering for safety).

Active user filter: `User.is_active = TRUE` — deactivated TACs are never
auto-assigned. Legacy ``ClientTacAssignment.is_primary`` remains available to
the notification resolver, but no longer decides ownership of newly created
Jobs.
"""

import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResolvedOwners:
    """Immutable DTO holding the resolved default TAC + DL for a client."""

    tac_id: int | None
    delivery_lead_id: int | None
    tac_selection_required: bool = False


async def resolve_default_owners(
    db: AsyncSession, client_id: int | None
) -> ResolvedOwners:
    """Look up the sole active TAC and head DL for the given client.

    Returns `ResolvedOwners(None, None)` when:
    - `client_id` is None (new job without a client yet), or
    - the client has zero or multiple active TACs / no head DL,
    - the assigned user was deactivated (filtered out).

    Never raises; callers fall back to NULL silently.
    """
    if client_id is None:
        return ResolvedOwners(tac_id=None, delivery_lead_id=None)

    # TAC relationships are equal.  Inferring only the sole active assignment
    # prevents a legacy `is_primary` bit (or row order) from becoming an
    # arbitrary owner when several TACs serve the same client.
    tac_stmt = (
        select(ClientTacAssignment.tac_user_id)
        .join(User, User.id == ClientTacAssignment.tac_user_id)
        .where(
            ClientTacAssignment.client_id == client_id,
            User.is_active.is_(True),
        )
        .order_by(ClientTacAssignment.id.asc())
    )
    tac_rows = list((await db.execute(tac_stmt)).scalars().all())
    tac_id = tac_rows[0] if len(tac_rows) == 1 else None

    # Head Delivery Lead — no DB-level max-1 guarantee, so `.limit(1)` with
    # deterministic ordering (by assignment id) to avoid flip-flopping.
    dl_stmt = (
        select(DeliveryLeadClientAssignment.delivery_lead_user_id)
        .join(
            User,
            User.id == DeliveryLeadClientAssignment.delivery_lead_user_id,
        )
        .where(
            DeliveryLeadClientAssignment.client_id == client_id,
            DeliveryLeadClientAssignment.is_head.is_(True),
            User.is_active.is_(True),
        )
        .order_by(DeliveryLeadClientAssignment.id.asc())
        .limit(1)
    )
    dl_row = (await db.execute(dl_stmt)).scalar_one_or_none()

    if not tac_rows:
        logger.info(
            "auto_assign: client=%s has no active TAC (explicit owner needed)",
            client_id,
        )
    elif len(tac_rows) > 1:
        logger.info(
            "auto_assign: client=%s has %s active TACs; refusing arbitrary owner",
            client_id,
            len(tac_rows),
        )
    if dl_row is None:
        logger.info(
            "auto_assign: client=%s has no head Delivery Lead",
            client_id,
        )

    return ResolvedOwners(
        tac_id=tac_id,
        delivery_lead_id=dl_row,
        tac_selection_required=len(tac_rows) > 1,
    )
