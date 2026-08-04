"""Transactional invalidation for relationship-derived authorization scopes.

Dashboard access for a Delivery Lead is derived from mutable relationship
tables.  A JWT issued before one of those relationships changes must not keep
using the old scope, including on long-lived WebSocket connections.
"""

from collections.abc import Iterable

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole


def _active_delivery_lead_filter():
    """Match active users holding Delivery Lead as a primary or secondary role."""

    return (
        User.is_active.is_(True),
        or_(
            User.role == UserRole.delivery_lead,
            User.roles.contains([UserRole.delivery_lead.value]),
        ),
    )


async def invalidate_delivery_lead_scope_for_users(
    db: AsyncSession,
    user_ids: Iterable[int],
) -> int:
    """Revoke current sessions for the affected active Delivery Leads.

    The SQL expression increments the version atomically, so concurrent
    relationship changes cannot overwrite one another with a stale in-memory
    value.  Callers must invoke this only after detecting a real mutation.
    """

    ids = sorted(set(user_ids))
    if not ids:
        return 0

    result = await db.execute(
        update(User)
        .where(
            User.id.in_(ids),
            *_active_delivery_lead_filter(),
        )
        .values(
            authorization_version=User.authorization_version + 1,
            tokens_valid_after=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return max(result.rowcount or 0, 0)


async def invalidate_delivery_lead_scope_for_client(
    db: AsyncSession,
    client_id: int,
) -> int:
    """Revoke sessions for every active DL whose scope includes ``client_id``."""

    assigned_delivery_leads = select(
        DeliveryLeadClientAssignment.delivery_lead_user_id
    ).where(DeliveryLeadClientAssignment.client_id == client_id)
    result = await db.execute(
        update(User)
        .where(
            User.id.in_(assigned_delivery_leads),
            *_active_delivery_lead_filter(),
        )
        .values(
            authorization_version=User.authorization_version + 1,
            tokens_valid_after=func.now(),
        )
        .execution_options(synchronize_session=False)
    )
    return max(result.rowcount or 0, 0)
