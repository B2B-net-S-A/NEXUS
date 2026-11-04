"""Recipient scope for Delivery notifications.

Delivery alerts may contain client and contract data.  Delivery Leads receive
alerts only for clients assigned through ``DeliveryLeadClientAssignment``.
Both primary and secondary (JSONB) roles are honoured, and every non-admin
recipient is checked against the authoritative section policy before an alert
is created.

Dzwonek (koniec zamówienia, umowy, umowy ramowej, zwrot sprzętu, szkic po
zatrudnieniu) idzie przez ``bell_recipients``: do Delivery Leadów klienta,
a do adminów tylko wtedy, gdy żaden z nich nie może dostać tego typu
powiadomienia (klient bez DL-a, DL z wyciszoną kategorią, grupa wyłączona
dla roli, brak sekcji).
Do 09.10.2026 dostawał go każdy admin — 1 237 powiadomień w 30 dni na 7 kont,
przeczytane w 8%.  ``for_client`` (admini + DL) zostaje bramką maili alertów.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.notification import NotificationType
from app.models.user import User, UserRole
from app.services.notification_access import user_can_receive_notification
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
    # Dzwonek: jak wyżej plus konta będące naraz Adminem i Delivery Leadem
    # klienta — `delivery_lead_ids_by_client` pomija je, bo karty DL i maile
    # liczą admina osobno.
    bell_lead_ids_by_client: dict[int, frozenset[int]] = field(default_factory=dict)
    # Konta z policzoną polityką (sekcje, wyciszenia osoby i roli).
    users_by_id: dict[int, User] = field(default_factory=dict)

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

    def bell_recipients(
        self, client_id: int | None, notification_type: NotificationType
    ) -> list[int]:
        """Odbiorcy dzwonka: Delivery Leadzi klienta, bez nich — admini.

        Admin jest zapasem, a nie stałym odbiorcą każdego alertu w firmie.
        Zapas działa, gdy ŻADEN Delivery Lead klienta nie może dostać tego
        typu: klient bez DL-a, umowa bez klienta, ale też DL z wyciszoną
        kategorią albo grupą wyłączoną dla roli. Bez tego alert trafiałby do
        wiersza, którego nikt nie widzi, a skaner uznawałby próg za wysłany.
        """

        leads = (
            self.bell_lead_ids_by_client.get(client_id, frozenset())
            if client_id is not None
            else frozenset()
        )
        reachable = {
            user_id
            for user_id in leads
            if self._can_receive(user_id, notification_type)
        }
        return sorted(reachable or self.admin_ids)

    def _can_receive(self, user_id: int, notification_type: NotificationType) -> bool:
        user = self.users_by_id.get(user_id)
        return user is None or user_can_receive_notification(user, notification_type)

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

    # Admin z rolą Delivery Leada przypisany do klienta jest dla dzwonka jego
    # DL-em — inaczej klient wyglądałby na „bez DL-a” i alert szedłby do
    # wszystkich adminów.
    admin_delivery_lead_ids = {
        user.id
        for user in eligible_users
        if user.has_role(UserRole.admin) and user.has_role(UserRole.delivery_lead)
    }
    bell_lead_ids = eligible_delivery_lead_ids | admin_delivery_lead_ids

    assigned_by_client: dict[int, set[int]] = {}
    bell_by_client: dict[int, set[int]] = {}
    if bell_lead_ids:
        rows = await db.execute(
            select(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.delivery_lead_user_id,
            ).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id.in_(bell_lead_ids)
            )
        )
        for client_id, user_id in rows.all():
            bell_by_client.setdefault(client_id, set()).add(user_id)
            if user_id in eligible_delivery_lead_ids:
                assigned_by_client.setdefault(client_id, set()).add(user_id)

    return DeliveryAlertRecipientScope(
        admin_ids=admin_ids,
        delivery_lead_ids_by_client={
            client_id: frozenset(user_ids)
            for client_id, user_ids in assigned_by_client.items()
        },
        bell_lead_ids_by_client={
            client_id: frozenset(user_ids)
            for client_id, user_ids in bell_by_client.items()
        },
        users_by_id={user.id: user for user in eligible_users},
    )
