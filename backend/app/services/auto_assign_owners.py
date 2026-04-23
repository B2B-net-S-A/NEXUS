"""Resolve default owners (primary TAC + head Delivery Lead) for a Job.

Pure resolver — no DB writes. Called from `POST /jobs` to pre-fill `tac_id`
and `delivery_lead_id` when the caller didn't supply them explicitly.

Source of truth:
- `client_tac_assignments.is_primary = TRUE` (guarded by partial unique
  index `uq_client_primary_tac` in migracja 0060 — max 1 per client).
- `delivery_lead_client_assignments.is_head = TRUE` (app-level guard only;
  resolver uses `.limit(1)` with deterministic ordering for safety).

Active user filter: `User.is_active = TRUE` — a deactivated primary TAC
should fall back to NULL, not be auto-assigned. The UI surfaces this via
the "Brak TAC" alert, prompting admin to pick a new opiekun.
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


async def resolve_default_owners(
    db: AsyncSession, client_id: int | None
) -> ResolvedOwners:
    """Look up primary TAC and head DL for the given client.

    Returns `ResolvedOwners(None, None)` when:
    - `client_id` is None (new job without a client yet), or
    - the client has no primary TAC / head DL (either field can be None),
    - the assigned user was deactivated (filtered out).

    Never raises; callers fall back to NULL silently.
    """
    if client_id is None:
        return ResolvedOwners(tac_id=None, delivery_lead_id=None)

    # Primary TAC — partial unique index guarantees at most one row.
    tac_stmt = (
        select(ClientTacAssignment.tac_user_id)
        .join(User, User.id == ClientTacAssignment.tac_user_id)
        .where(
            ClientTacAssignment.client_id == client_id,
            ClientTacAssignment.is_primary.is_(True),
            User.is_active.is_(True),
        )
        .limit(1)
    )
    tac_row = (await db.execute(tac_stmt)).scalar_one_or_none()

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

    if tac_row is None:
        logger.info(
            "auto_assign: client=%s has no primary TAC (UI alert expected)",
            client_id,
        )
    if dl_row is None:
        logger.info(
            "auto_assign: client=%s has no head Delivery Lead",
            client_id,
        )

    return ResolvedOwners(tac_id=tac_row, delivery_lead_id=dl_row)
