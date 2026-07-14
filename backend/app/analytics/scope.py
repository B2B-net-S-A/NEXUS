"""Row-scope rules for capability-gated analytics endpoints.

Capabilities define which data class a role may request.  These helpers apply
the second security boundary: explicit client/team assignments.  They are kept
separate so secondary roles grant capabilities without silently turning a
client-scoped account into an organization-wide account.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.client import Client
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
    TacDeliveryLeadAssignment,
)
from app.models.user import User, UserRole


async def require_client_scope(
    db: AsyncSession,
    *,
    user: User,
    client_id: int,
    finance: bool,
) -> None:
    """Require global manager scope or an explicit client assignment.

    Operations are global for admin/HoR. Financial client detail is global for
    admin and Delivery Lead, matching their organization-wide finance
    capability. TAC assignments are valid for operations only.
    """

    global_roles = (
        (UserRole.admin, UserRole.delivery_lead)
        if finance
        else (UserRole.admin, UserRole.head_of_recruitment)
    )
    if user.has_any_role(*global_roles):
        exists = await db.scalar(select(Client.id).where(Client.id == client_id))
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Client not found",
            )
        return

    assignment_checks = []
    if user.has_role(UserRole.delivery_lead):
        assignment_checks.append(
            select(DeliveryLeadClientAssignment.id).where(
                DeliveryLeadClientAssignment.client_id == client_id,
                DeliveryLeadClientAssignment.delivery_lead_user_id == user.id,
            )
        )
    if not finance and user.has_role(UserRole.tac):
        assignment_checks.append(
            select(ClientTacAssignment.id).where(
                ClientTacAssignment.client_id == client_id,
                ClientTacAssignment.tac_user_id == user.id,
            )
        )

    for query in assignment_checks:
        if await db.scalar(query) is not None:
            return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Analytics access is limited to assigned clients",
    )


async def tender_client_scope(
    db: AsyncSession,
    *,
    user: User,
) -> set[int] | None:
    """Return allowed tender client ids; ``None`` means organization-wide."""

    if user.has_role(UserRole.admin):
        return None

    client_ids: set[int] = set()
    if user.has_role(UserRole.delivery_lead):
        rows = await db.scalars(
            select(DeliveryLeadClientAssignment.client_id).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
            )
        )
        client_ids.update(int(value) for value in rows.all())
    if user.has_role(UserRole.tac):
        rows = await db.scalars(
            select(ClientTacAssignment.client_id).where(
                ClientTacAssignment.tac_user_id == user.id
            )
        )
        client_ids.update(int(value) for value in rows.all())
    return client_ids


async def operations_client_scope(
    db: AsyncSession,
    *,
    user: User,
) -> set[int] | None:
    """Return visible operational client ids; ``None`` means organization-wide."""

    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return None

    client_ids: set[int] = set()
    if user.has_role(UserRole.delivery_lead):
        rows = await db.scalars(
            select(DeliveryLeadClientAssignment.client_id).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
            )
        )
        client_ids.update(int(value) for value in rows.all())
    if user.has_role(UserRole.tac):
        rows = await db.scalars(
            select(ClientTacAssignment.client_id).where(
                ClientTacAssignment.tac_user_id == user.id
            )
        )
        client_ids.update(int(value) for value in rows.all())
    return client_ids


async def delivery_lead_scope(
    db: AsyncSession,
    *,
    user: User,
) -> set[int] | None:
    """Return visible DL ids; ``None`` means the whole delivery organization."""

    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return None

    delivery_lead_ids: set[int] = set()
    if user.has_role(UserRole.delivery_lead):
        delivery_lead_ids.add(user.id)
    if user.has_role(UserRole.tac):
        assigned = await db.scalars(
            select(TacDeliveryLeadAssignment.delivery_lead_user_id).where(
                TacDeliveryLeadAssignment.tac_user_id == user.id
            )
        )
        delivery_lead_ids.update(int(value) for value in assigned.all())
    return delivery_lead_ids


async def require_recruitment_user_scope(
    db: AsyncSession,
    *,
    viewer: User,
    target_user_id: int,
) -> User:
    """Resolve a recruitment user only inside the viewer's management scope."""

    globally_visible = viewer.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
    )
    self_visible = viewer.id == target_user_id
    assigned_visible = False
    if (
        not globally_visible
        and not self_visible
        and viewer.has_role(UserRole.delivery_lead)
    ):
        assigned_visible = (
            await db.scalar(
                select(TacDeliveryLeadAssignment.id).where(
                    TacDeliveryLeadAssignment.delivery_lead_user_id == viewer.id,
                    TacDeliveryLeadAssignment.tac_user_id == target_user_id,
                )
            )
            is not None
        )

    if not (globally_visible or self_visible or assigned_visible):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Recruitment analytics are limited to self or assigned team",
        )

    target = await db.scalar(
        select(User).where(
            User.id == target_user_id,
            User.is_active.is_(True),
        )
    )
    if target is None or not target.has_any_role(
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.tac,
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Recruitment user not found",
        )
    return target
