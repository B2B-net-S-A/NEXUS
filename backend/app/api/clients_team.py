"""Router `/api/clients/{id}/team` + `/api/clients/{id}/tacs/*`.

Surfaces the Client ↔ TAC + DL relationships as a single "Opiekunowie"
view for the client edit page. The DL writes still go through
`/api/team-structure/dl-clients/*` (pre-existing); this router owns the
TAC-side CRUD and the combined GET.

Auth:
- `GET /api/clients/{id}/team` — any logged-in user (read-only).
- All writes (`POST`, `DELETE`, `PUT`) — `HeadOfRecruitmentPlus`
  (admin + head_of_recruitment).
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, OperationalUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.client import Client
from app.models.team_structure import (
    ClientTacAssignment,
    DeliveryLeadClientAssignment,
)
from app.models.user import User, UserRole
from app.schemas.client_team import (
    ClientDlAssignmentRead,
    ClientTacAssignmentCreate,
    ClientTacAssignmentRead,
    ClientTacFirstPriorityRead,
    ClientTacFirstPriorityUpdate,
    ClientTeamResponse,
)
from app.services.authorization_invalidation import (
    invalidate_delivery_lead_scope_for_client,
)
from app.services.client_tac_assignments import (
    ClientTacAssignmentNotFound,
    FirstPrioritySuccessorRequired,
    InvalidFirstPrioritySuccessor,
    remove_client_tac_assignment,
    set_first_priority_for_tac,
    toggle_legacy_primary_tac,
    upsert_client_tac_assignment,
)
from app.services.client_access import deny, resolve_client_access

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


# Role allowed to act as a client-relationship TAC. Intentionally wider than
# just `UserRole.tac` — a DL or admin can own a client relationship too
# (especially during transitions). Reused in `POST /jobs` role validation.
TAC_ASSIGNABLE_ROLES = {
    UserRole.tac,
    UserRole.delivery_lead,
    UserRole.admin,
    UserRole.head_of_recruitment,
}


async def _ensure_client_exists(db: AsyncSession, client_id: int) -> Client:
    client = (
        await db.execute(select(Client).where(Client.id == client_id))
    ).scalar_one_or_none()
    if client is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=f"Client {client_id} not found"
        )
    return client


async def _load_user_for_tac(db: AsyncSession, user_id: int) -> User:
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    if not user.is_active:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail="User is inactive; cannot assign as TAC",
        )
    # Multi-role aware (M1-RBAC-02): hybryda np. recruiter+tac kwalifikuje
    # się przez rolę dodatkową.
    if not user.has_any_role(*TAC_ASSIGNABLE_ROLES):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            detail=(
                "user_id must reference a user with role "
                "tac/delivery_lead/admin/head_of_recruitment"
            ),
        )
    return user


def _role_str(role) -> str | None:
    if role is None:
        return None
    return getattr(role, "value", str(role))


async def _resolve_first_priority_reconciliation(
    db: AsyncSession,
    *,
    tac_user_id: int,
    selected_client_id: int,
    resolved_by: int,
) -> None:
    """Close any operational ambiguity record in the assignment transaction."""

    await db.execute(
        text(
            """
            UPDATE rbac_relationship_reconciliation
            SET resolved_at = now(),
                resolved_by = :resolved_by,
                details = COALESCE(details, '{}'::jsonb)
                    || jsonb_build_object(
                        'selected_client_id', CAST(:selected_client_id AS INTEGER)
                    )
            WHERE migration_key = '0210_role_dashboard_rbac_cutover'
              AND issue_kind = 'client_tac_first_priority_required'
              AND user_id = :tac_user_id
              AND resolved_at IS NULL
            """
        ),
        {
            "tac_user_id": tac_user_id,
            "selected_client_id": selected_client_id,
            "resolved_by": resolved_by,
        },
    )


@router.get("/{client_id}/team", response_model=ClientTeamResponse)
async def get_client_team(
    client_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> ClientTeamResponse:
    """Combined TAC + DL view for a single client."""
    await _ensure_client_exists(db, client_id)
    access = await resolve_client_access(db, current_user, client_id)
    if not access.can_view_contacts:
        raise deny("brak dostępu do zespołu tego klienta")

    tac_rows = (
        await db.execute(
            select(
                ClientTacAssignment.id,
                ClientTacAssignment.tac_user_id,
                ClientTacAssignment.is_first_priority_for_tac,
                ClientTacAssignment.is_primary,
                ClientTacAssignment.created_at,
                User.name,
                User.email,
                User.role,
            )
            .join(User, User.id == ClientTacAssignment.tac_user_id)
            .where(ClientTacAssignment.client_id == client_id)
            .order_by(
                User.name.asc(),
                ClientTacAssignment.id.asc(),
            )
        )
    ).all()

    dl_rows = (
        await db.execute(
            select(
                DeliveryLeadClientAssignment.id,
                DeliveryLeadClientAssignment.delivery_lead_user_id,
                DeliveryLeadClientAssignment.is_head,
                DeliveryLeadClientAssignment.created_at,
                User.name,
                User.email,
                User.role,
            )
            .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
            .where(DeliveryLeadClientAssignment.client_id == client_id)
            .order_by(
                DeliveryLeadClientAssignment.is_head.desc(),
                User.name.asc(),
            )
        )
    ).all()

    return ClientTeamResponse(
        tacs=[
            ClientTacAssignmentRead(
                id=r.id,
                user_id=r.tac_user_id,
                name=r.name,
                email=r.email,
                role=_role_str(r.role),
                is_first_priority_for_tac=r.is_first_priority_for_tac,
                is_primary=r.is_primary,
                created_at=r.created_at,
            )
            for r in tac_rows
        ],
        delivery_leads=[
            ClientDlAssignmentRead(
                id=r.id,
                user_id=r.delivery_lead_user_id,
                name=r.name,
                email=r.email,
                role=_role_str(r.role),
                is_head=r.is_head,
                created_at=r.created_at,
            )
            for r in dl_rows
        ],
    )


@router.post(
    "/{client_id}/tacs",
    status_code=status.HTTP_201_CREATED,
)
async def assign_tac_to_client(
    client_id: int,
    payload: ClientTacAssignmentCreate,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Upsert TAC ↔ Client assignment.

    The legacy client-centric ``is_primary`` and the TAC-centric
    ``is_first_priority_for_tac`` are mutated independently.  Omitting the
    latter auto-prioritises only a TAC's first client assignment.
    """
    await _ensure_client_exists(db, client_id)
    await _load_user_for_tac(db, payload.user_id)
    try:
        result = await upsert_client_tac_assignment(
            db,
            client_id=client_id,
            tac_user_id=payload.user_id,
            is_primary=payload.is_primary,
            is_first_priority_for_tac=payload.is_first_priority_for_tac,
        )
    except FirstPrioritySuccessorRequired as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    # Preserve current cache/session behaviour for legacy-primary changes;
    # TAC-centric priority alone never changes the relationship scope.
    if result.membership_changed or result.legacy_primary_changed:
        await invalidate_delivery_lead_scope_for_client(db, client_id)
    if result.assignment.is_first_priority_for_tac is True:
        await _resolve_first_priority_reconciliation(
            db,
            tac_user_id=payload.user_id,
            selected_client_id=client_id,
            resolved_by=_user.id,
        )
    await db.commit()
    return {
        "ok": True,
        "is_primary": result.assignment.is_primary,
        "is_first_priority_for_tac": (result.assignment.is_first_priority_for_tac),
    }


@router.delete(
    "/{client_id}/tacs/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_tac_from_client(
    client_id: int,
    user_id: int,
    _user: HeadOfRecruitmentPlus,
    successor_client_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
):
    try:
        await remove_client_tac_assignment(
            db,
            client_id=client_id,
            tac_user_id=user_id,
            successor_client_id=successor_client_id,
        )
    except ClientTacAssignmentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FirstPrioritySuccessorRequired as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidFirstPrioritySuccessor as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    await invalidate_delivery_lead_scope_for_client(db, client_id)
    if successor_client_id is not None:
        await _resolve_first_priority_reconciliation(
            db,
            tac_user_id=user_id,
            selected_client_id=successor_client_id,
            resolved_by=_user.id,
        )
    await db.commit()


@router.put("/{client_id}/tacs/{user_id}/toggle-primary")
async def toggle_tac_primary(
    client_id: int,
    user_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Flip only legacy ``is_primary``; never rewrite TAC work priority."""
    try:
        row = await toggle_legacy_primary_tac(
            db,
            client_id=client_id,
            tac_user_id=user_id,
        )
    except ClientTacAssignmentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    await invalidate_delivery_lead_scope_for_client(db, client_id)
    await db.commit()
    return {"ok": True, "is_primary": row.is_primary}


@router.put(
    "/{client_id}/tacs/{user_id}/first-priority",
    response_model=ClientTacFirstPriorityRead,
)
async def update_tac_first_priority(
    client_id: int,
    user_id: int,
    payload: ClientTacFirstPriorityUpdate,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> ClientTacFirstPriorityRead:
    """Atomically change a TAC's first-priority client.

    Disabling the current priority while another assignment exists requires
    ``successor_client_id`` so there is no priority gap between transactions.
    This operation does not alter relationship authorization scope.
    """
    try:
        row = await set_first_priority_for_tac(
            db,
            client_id=client_id,
            tac_user_id=user_id,
            enabled=payload.enabled,
            successor_client_id=payload.successor_client_id,
        )
    except ClientTacAssignmentNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FirstPrioritySuccessorRequired as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InvalidFirstPrioritySuccessor as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    selected_client_id = client_id if payload.enabled else payload.successor_client_id
    if selected_client_id is not None:
        await _resolve_first_priority_reconciliation(
            db,
            tac_user_id=user_id,
            selected_client_id=selected_client_id,
            resolved_by=_user.id,
        )
    await db.commit()
    return ClientTacFirstPriorityRead(
        tac_user_id=user_id,
        client_id=client_id,
        is_first_priority_for_tac=row.is_first_priority_for_tac is True,
    )
