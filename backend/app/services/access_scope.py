"""Authoritative data scope for role-aware dashboards.

Capabilities answer *what* a user may see.  This module answers *whose / which
client's* rows may participate in that view.  Keeping the two concerns separate
prevents a Delivery Lead assignment from accidentally becoming organization-wide
access to every activity of a TAC.
"""

from dataclasses import dataclass
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.job import Job
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole


class ScopeKind(str, Enum):
    organization = "organization"
    recruitment_org = "recruitment_org"
    delivery_clients = "delivery_clients"
    self = "self"


@dataclass(frozen=True)
class DashboardScope:
    kind: ScopeKind
    user_id: int | None = None
    allowed_client_ids: frozenset[int] = frozenset()
    allowed_tac_user_ids: frozenset[int] = frozenset()
    allowed_operator_user_ids: frozenset[int] = frozenset()
    # Authoritative Delivery Lead relationship scope.  The separate client/TAC
    # sets are useful summaries, but must never be combined as a cartesian
    # product when filtering facts.
    allowed_client_tac_pairs: frozenset[tuple[int, int]] = frozenset()

    def as_payload(self) -> dict[str, object]:
        return {
            "kind": self.kind.value,
            "user_id": self.user_id,
            "allowed_client_ids": sorted(self.allowed_client_ids),
            "allowed_tac_user_ids": sorted(self.allowed_tac_user_ids),
            "allowed_operator_user_ids": sorted(self.allowed_operator_user_ids),
            "allowed_client_tac_pairs": [
                {"client_id": client_id, "tac_user_id": tac_user_id}
                for client_id, tac_user_id in sorted(self.allowed_client_tac_pairs)
            ],
        }

    def cache_token(self) -> str:
        """Stable cache discriminator; never share aggregates across scopes."""

        clients = ",".join(str(value) for value in sorted(self.allowed_client_ids))
        tacs = ",".join(str(value) for value in sorted(self.allowed_tac_user_ids))
        operators = ",".join(
            str(value) for value in sorted(self.allowed_operator_user_ids)
        )
        pairs = ",".join(
            f"{client_id}-{tac_user_id}"
            for client_id, tac_user_id in sorted(self.allowed_client_tac_pairs)
        )
        return (
            f"{self.kind.value}:u={self.user_id or '-'}:"
            f"c={clients}:t={tacs}:o={operators}:p={pairs}"
        )


async def resolve_dashboard_scope(
    user: User,
    db: AsyncSession,
) -> DashboardScope:
    """Resolve the narrowest authoritative scope for the user's persona.

    Precedence intentionally follows organizational authority.  Admin and the
    exclusive Finance persona can query organization-wide rows, with the
    capability matrix still limiting the domains/fields they may consume.
    Head of Recruitment sees active recruitment operators.  Delivery Lead sees
    only the intersection of their clients and TACs assigned to those clients.
    Operators see only their own work.
    """

    roles = set(user.get_all_roles())
    if UserRole.admin in roles or UserRole.finance in roles:
        return DashboardScope(kind=ScopeKind.organization, user_id=user.id)

    if UserRole.head_of_recruitment in roles:
        recruitment_roles = (
            UserRole.tac,
            UserRole.sourcer,
            UserRole.recruiter,
        )
        operator_ids = frozenset(
            (
                await db.scalars(
                    select(User.id).where(
                        User.is_active.is_(True),
                        or_(
                            User.role.in_(recruitment_roles),
                            *(
                                User.roles.contains([role.value])
                                for role in recruitment_roles
                            ),
                        ),
                    )
                )
            ).all()
        )
        return DashboardScope(
            kind=ScopeKind.recruitment_org,
            user_id=user.id,
            allowed_tac_user_ids=operator_ids,
            allowed_operator_user_ids=operator_ids,
        )

    if UserRole.delivery_lead in roles:
        client_ids = frozenset(
            (
                await db.scalars(
                    select(DeliveryLeadClientAssignment.client_id).where(
                        DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
                    )
                )
            ).all()
        )
        client_tac_pairs: frozenset[tuple[int, int]] = frozenset()
        if client_ids:
            pair_rows = (
                await db.execute(
                    select(
                        ClientTacAssignment.client_id,
                        ClientTacAssignment.tac_user_id,
                    )
                    .where(ClientTacAssignment.client_id.in_(client_ids))
                    .distinct()
                )
            ).all()
            client_tac_pairs = frozenset(
                (int(row.client_id), int(row.tac_user_id)) for row in pair_rows
            )
        tac_ids = frozenset(tac_user_id for _, tac_user_id in client_tac_pairs)
        return DashboardScope(
            kind=ScopeKind.delivery_clients,
            user_id=user.id,
            allowed_client_ids=client_ids,
            allowed_tac_user_ids=tac_ids,
            allowed_operator_user_ids=tac_ids,
            allowed_client_tac_pairs=client_tac_pairs,
        )

    return DashboardScope(
        kind=ScopeKind.self,
        user_id=user.id,
        allowed_tac_user_ids=frozenset({user.id}),
        allowed_operator_user_ids=frozenset({user.id}),
    )


async def resolve_delivery_lead_client_ids(
    user: User,
    db: AsyncSession,
) -> frozenset[int] | None:
    """Return the canonical client boundary for a plain Delivery Lead.

    ``None`` means the caller is not governed by the DL persona boundary
    (Admin/Head of Recruitment oversight or a non-DL operational role). An
    empty set is a real deny-all scope and must never fall back to all clients.
    """

    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return None
    if not user.has_role(UserRole.delivery_lead):
        return None
    scope = await resolve_dashboard_scope(user, db)
    if scope.kind is not ScopeKind.delivery_clients or scope.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery scope belongs to a different user",
        )
    return scope.allowed_client_ids


def apply_delivery_lead_client_scope(
    statement,
    client_column,
    allowed_client_ids: frozenset[int] | None,
):
    if allowed_client_ids is None:
        return statement
    return statement.where(client_column.in_(sorted(allowed_client_ids) or [-1]))


def assert_delivery_lead_client_visible(
    client_id: int | None,
    allowed_client_ids: frozenset[int] | None,
) -> None:
    if allowed_client_ids is None:
        return
    if client_id is None or client_id not in allowed_client_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Client is outside the resolved Delivery Lead scope",
        )


def apply_delivery_lead_activity_scope(
    statement,
    scope: DashboardScope,
):
    """Keep a DL feed inside exact client and client/TAC relationships.

    Activity has a polymorphic ``entity_id`` and no direct client foreign key.
    Client rows therefore use the DL's explicit client assignments, while job
    rows are resolved through the authoritative ``(client_id, tac_id)`` pairs.
    Empty assignments are represented by impossible sentinels and remain
    deny-all.
    """

    if scope.kind is not ScopeKind.delivery_clients or scope.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery activity scope is not authoritative",
        )

    client_ids = sorted(scope.allowed_client_ids) or [-1]
    client_tac_pairs = sorted(scope.allowed_client_tac_pairs) or [(-1, -1)]
    allowed_job_ids = select(Job.id).where(
        tuple_(Job.client_id, Job.tac_id).in_(client_tac_pairs)
    )
    return statement.where(
        or_(
            and_(
                Activity.entity_type == "client",
                Activity.entity_id.in_(client_ids),
            ),
            and_(
                Activity.entity_type == "job",
                Activity.entity_id.in_(allowed_job_ids),
            ),
        )
    )


async def apply_activity_feed_scope(
    statement,
    user: User,
    db: AsyncSession,
):
    """Apply the persona-specific activity boundary before sorting/limiting."""

    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return statement
    if not user.has_role(UserRole.delivery_lead):
        return statement

    scope = await resolve_dashboard_scope(user, db)
    if scope.kind is not ScopeKind.delivery_clients or scope.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery activity scope belongs to a different user",
        )
    return apply_delivery_lead_activity_scope(statement, scope)
