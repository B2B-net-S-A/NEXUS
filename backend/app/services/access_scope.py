"""Authoritative data scope for role-aware dashboards.

Capabilities answer *what* a user may see.  This module answers *whose / which
client's* rows may participate in that view.  Keeping the two concerns separate
lets every Delivery Lead work across the full client portfolio without turning
the role into an Admin or Finance persona.

Delivery modules (Klienci, Kontrakty, Zamówienia, skrzynka zamówień) use
``resolve_delivery_lead_client_ids`` — since 25.09.2026 only the DL's assigned
clients (``DL_CLIENT_SCOPE``). Recruitment surfaces keep the whole portfolio via
``resolve_delivery_lead_org_client_ids``; dashboards via ``resolve_dashboard_scope``.
"""

from dataclasses import dataclass
from enum import Enum

from fastapi import HTTPException, status
from sqlalchemy import and_, or_, select, union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.core.config import settings
from app.models.activity import Activity
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.job_collaborator import JobCollaborator
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
    *,
    delivery_lead_persona: bool = False,
) -> DashboardScope:
    """Resolve the narrowest authoritative scope for the user's persona.

    Precedence intentionally follows organizational authority.  Admin and the
    exclusive Finance persona can query organization-wide rows, with the
    capability matrix still limiting the domains/fields they may consume.
    Head of Recruitment and Talent Community Manager see active recruitment
    operators. Delivery Lead sees every client and the authoritative TAC
    relationships attached to those clients; its operator team is built from
    the people on its recruitments (``_delivery_lead_operator_ids``).
    Operators see only their own work.
    ``delivery_lead_persona=True`` lets a recruitment+DL hybrid explicitly
    select its DL dashboard without inheriting the wider recruitment
    precedence; admin remains organization-wide.
    """

    roles = set(user.get_all_roles())
    if UserRole.admin in roles or UserRole.finance in roles:
        return DashboardScope(kind=ScopeKind.organization, user_id=user.id)

    if (
        roles.intersection(
            {UserRole.head_of_recruitment, UserRole.talent_community_manager}
        )
        and not delivery_lead_persona
    ):
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
            int(client_id) for client_id in (await db.scalars(select(Client.id))).all()
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
            allowed_operator_user_ids=tac_ids
            | await _delivery_lead_operator_ids(user, db),
            allowed_client_tac_pairs=client_tac_pairs,
        )

    if delivery_lead_persona:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not hold the Delivery Lead persona",
        )

    return DashboardScope(
        kind=ScopeKind.self,
        user_id=user.id,
        allowed_tac_user_ids=frozenset({user.id}),
        allowed_operator_user_ids=frozenset({user.id}),
    )


async def _delivery_lead_operator_ids(user: User, db: AsyncSession) -> frozenset[int]:
    """Zespół Delivery Leada = ludzie jego otwartych rekrutacji.

    Do 22.09.2026 zespół DL liczył się wyłącznie z ``ClientTacAssignment``,
    a funkcji TAC nie używamy — więc „zespół" był pusty u każdego DL. Teraz
    to osoby prowadzące rekrutacje, które DL prowadzi (``jobs.delivery_lead_id``)
    albo które należą do jego klientów (``DeliveryLeadClientAssignment``):
    rekruter prowadzący, TAC i aktywni współpracownicy. Tylko aktywne konta.
    Zakres DANYCH (pary klient×TAC, klienci) zostaje bez zmian — to wyłącznie
    lista ludzi do atrybucji w pulpitach.
    """

    assigned_clients = select(DeliveryLeadClientAssignment.client_id).where(
        DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
    )
    led_jobs = select(Job.id).where(
        Job.status != JobStatus.closed,
        or_(
            Job.delivery_lead_id == user.id,
            Job.client_id.in_(assigned_clients),
        ),
    )
    people = union(
        select(Job.recruiter_id.label("user_id")).where(Job.id.in_(led_jobs)),
        select(Job.tac_id.label("user_id")).where(Job.id.in_(led_jobs)),
        select(JobCollaborator.user_id.label("user_id")).where(
            JobCollaborator.job_id.in_(led_jobs),
            JobCollaborator.removed_from_auto_cc.is_(False),
        ),
    ).subquery()
    return frozenset(
        int(user_id)
        for user_id in (
            await db.scalars(
                select(User.id).where(
                    User.id.in_(select(people.c.user_id)),
                    User.is_active.is_(True),
                )
            )
        ).all()
    )


def delivery_lead_scope_is_assigned() -> bool:
    """``DL_CLIENT_SCOPE``: anything but ``all`` narrows (fail-closed)."""

    return (settings.DL_CLIENT_SCOPE or "").strip().lower() != "all"


def delivery_lead_sees_whole_delivery(user: User) -> bool:
    """DL accounts whose other role already reads Delivery org-wide.

    Talent Community Manager reads every client's Delivery surfaces; adding
    the DL role must not take that away.
    """

    return user.has_role(UserRole.talent_community_manager)


async def resolve_delivery_lead_org_client_ids(
    user: User,
    db: AsyncSession,
) -> frozenset[int] | None:
    """Every current client for a Delivery Lead — recruitment surfaces only.

    Recruitment stays open to everyone (decision 23.09.2026), so screens such
    as recommendations, prep kit or email templates must not follow the
    Delivery narrowing. ``None`` has the same meaning as below.
    """

    if user.has_any_role(UserRole.admin, UserRole.finance):
        return None
    if not user.has_role(UserRole.delivery_lead):
        return None
    return frozenset(
        int(client_id) for client_id in (await db.scalars(select(Client.id))).all()
    )


async def resolve_delivery_lead_client_ids(
    user: User,
    db: AsyncSession,
) -> frozenset[int] | None:
    """Client boundary of a Delivery Lead in the Delivery modules.

    ``None`` means the caller is not governed by the DL persona boundary
    (Admin/Finance oversight or a non-DL operational role). A Delivery Lead
    sees only clients with ANY row in ``delivery_lead_client_assignments``
    (head or not — decision 25.09.2026). ``DL_CLIENT_SCOPE=all`` restores the
    #1365 behaviour (every client). Returning concrete ids (rather than
    ``None``) preserves the role's narrow finance exceptions without granting
    the global ``VIEW_FINANCE`` capability.
    """

    if not delivery_lead_scope_is_assigned() or delivery_lead_sees_whole_delivery(user):
        return await resolve_delivery_lead_org_client_ids(user, db)
    return await resolve_delivery_lead_assigned_client_ids(user, db)


async def resolve_delivery_lead_assigned_client_ids(
    user: User,
    db: AsyncSession,
) -> frozenset[int] | None:
    """Return clients for which the Delivery Lead is an explicit owner.

    Since 25.09.2026 this is also the Delivery read boundary
    (``resolve_delivery_lead_client_ids``); it keeps gating finance exceptions,
    rate-bearing opaque files and consequential legal writes. ``None`` means the caller is not governed by the DL ownership path.
    """

    if user.has_any_role(UserRole.admin, UserRole.finance):
        return None
    if not user.has_role(UserRole.delivery_lead):
        return None
    assigned = select(DeliveryLeadClientAssignment.client_id).where(
        DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
    )
    # Scalony duplikat i klient kanoniczny to ta sama firma (runda 6 audytu),
    # bo scalenie (``POST /clients/{id}/merge``, manifest portfela) NIE
    # przepina ``delivery_lead_client_assignments``: DL przypisany tylko do
    # duplikatu tracił po scaleniu dostęp do klienta kanonicznego, a DL
    # klienta kanonicznego nie widział historii zostawionej na duplikacie.
    # Łańcuch ma jeden poziom — celem scalenia nie może być klient scalony.
    merged = aliased(Client)
    canonical_of_assigned = select(merged.merged_into_client_id).where(
        merged.id.in_(assigned),
        merged.merged_into_client_id.is_not(None),
    )
    return frozenset(
        int(client_id)
        for client_id in (
            await db.scalars(
                select(Client.id).where(
                    or_(
                        Client.id.in_(assigned),
                        Client.id.in_(canonical_of_assigned),
                        Client.merged_into_client_id.in_(assigned),
                        Client.merged_into_client_id.in_(canonical_of_assigned),
                    )
                )
            )
        ).all()
    )


async def resolve_delivery_lead_finance_client_ids(
    user: User,
    db: AsyncSession,
) -> frozenset[int] | None:
    """Assigned-client boundary for the narrow DL finance exception."""

    return await resolve_delivery_lead_assigned_client_ids(user, db)


def apply_delivery_lead_client_scope(
    statement,
    client_column,
    allowed_client_ids: frozenset[int] | None,
):
    if allowed_client_ids is None:
        return statement
    return statement.where(client_column.in_(sorted(allowed_client_ids) or [-1]))


# Odmowa zakresu DL trafia wprost do toastów formularzy (Kontrakty,
# zamówienia), więc mówi po polsku (runda 6 audytu); front na 403 profilu
# pisze to samo zdanie.
DL_CLIENT_OUT_OF_SCOPE_DETAIL = "Ten klient jest poza Twoim portfelem."


def assert_delivery_lead_client_visible(
    client_id: int | None,
    allowed_client_ids: frozenset[int] | None,
) -> None:
    if allowed_client_ids is None:
        return
    if client_id is None or client_id not in allowed_client_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=DL_CLIENT_OUT_OF_SCOPE_DETAIL,
        )


def apply_delivery_lead_activity_scope(
    statement,
    scope: DashboardScope,
):
    """Keep a DL feed inside the organization-wide client boundary.

    Activity has a polymorphic ``entity_id`` and no direct client foreign key.
    Client rows therefore use the resolved all-client set, while job rows are
    admitted by their client id. TAC relationship pairs remain available on
    the dashboard scope for team attribution, but they are no longer an access
    boundary. An empty database is represented by an impossible sentinel.
    """

    if scope.kind is not ScopeKind.delivery_clients or scope.user_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery activity scope is not authoritative",
        )

    client_ids = sorted(scope.allowed_client_ids) or [-1]
    allowed_job_ids = select(Job.id).where(Job.client_id.in_(client_ids))
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

    if user.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
        UserRole.talent_community_manager,
    ):
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
