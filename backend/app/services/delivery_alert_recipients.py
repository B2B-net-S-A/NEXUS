"""Recipient scope for Delivery notifications.

Delivery alerts may contain client and contract data.  Global fan-out is
therefore limited to active admins, while Delivery Leads receive alerts only
for clients assigned through ``DeliveryLeadClientAssignment``.  Both primary
and secondary (JSONB) roles are honoured, and every non-admin recipient is
checked against the authoritative section policy before an alert is created.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    resolve_effective_section_access_for_users,
    section_access_for_user,
)


@dataclass(frozen=True)
class DeliveryAlertRecipientScope:
    """Pre-resolved recipients for one database session/cycle."""

    admin_ids: frozenset[int]
    delivery_lead_ids_by_client: dict[int, frozenset[int]]

    def for_client(self, client_id: int | None) -> list[int]:
        """Return deterministic, de-duplicated recipients for ``client_id``."""

        return sorted(
            self.admin_ids
            | (
                self.delivery_lead_ids_by_client.get(client_id, frozenset())
                if client_id is not None
                else frozenset()
            )
        )

    @property
    def is_empty(self) -> bool:
        return not self.admin_ids and not self.delivery_lead_ids_by_client


async def load_delivery_alert_recipient_scope(
    db: AsyncSession,
) -> DeliveryAlertRecipientScope:
    """Load active admins and assigned Delivery Leads with Delivery read access.

    Admin is a global-recipient role even when it is stored only in the JSONB
    ``roles`` array.  A Delivery Lead needs all three conditions: an active
    account, a primary or secondary ``delivery_lead`` role, and effective
    ``delivery >= read`` after applying per-user overrides.
    """

    eligible_users = list(
        (
            await db.scalars(
                select(User).where(
                    User.is_active.is_(True),
                    or_(
                        User.role.in_([UserRole.admin, UserRole.delivery_lead]),
                        User.roles.contains([UserRole.admin.value]),
                        User.roles.contains([UserRole.delivery_lead.value]),
                    ),
                )
            )
        ).all()
    )
    await resolve_effective_section_access_for_users(db, eligible_users)

    admin_ids = frozenset(
        user.id for user in eligible_users if user.has_role(UserRole.admin)
    )
    eligible_delivery_lead_ids = {
        user.id
        for user in eligible_users
        if not user.has_role(UserRole.admin)
        and user.has_role(UserRole.delivery_lead)
        and section_access_for_user(user, ProductSection.delivery) >= SectionAccess.read
    }

    assigned_by_client: dict[int, set[int]] = {}
    if eligible_delivery_lead_ids:
        rows = await db.execute(
            select(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.delivery_lead_user_id,
            ).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id.in_(
                    eligible_delivery_lead_ids
                )
            )
        )
        for client_id, user_id in rows.all():
            assigned_by_client.setdefault(client_id, set()).add(user_id)

    return DeliveryAlertRecipientScope(
        admin_ids=admin_ids,
        delivery_lead_ids_by_client={
            client_id: frozenset(user_ids)
            for client_id, user_ids in assigned_by_client.items()
        },
    )
