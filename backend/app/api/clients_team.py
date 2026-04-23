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

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus
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
    ClientTeamResponse,
)

router = APIRouter()


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
    if user.role not in TAC_ASSIGNABLE_ROLES:
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


@router.get("/{client_id}/team", response_model=ClientTeamResponse)
async def get_client_team(
    client_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> ClientTeamResponse:
    """Combined TAC + DL view for a single client."""
    await _ensure_client_exists(db, client_id)

    tac_rows = (
        await db.execute(
            select(
                ClientTacAssignment.id,
                ClientTacAssignment.tac_user_id,
                ClientTacAssignment.is_primary,
                ClientTacAssignment.created_at,
                User.name,
                User.email,
                User.role,
            )
            .join(User, User.id == ClientTacAssignment.tac_user_id)
            .where(ClientTacAssignment.client_id == client_id)
            .order_by(
                ClientTacAssignment.is_primary.desc(),
                User.name.asc(),
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
            .join(
                User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id
            )
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

    If `is_primary=True`, the previous primary TAC (if any) is demoted to
    `is_primary=False` inside the same transaction so the partial unique
    index `uq_client_primary_tac` is never violated.
    """
    await _ensure_client_exists(db, client_id)
    await _load_user_for_tac(db, payload.user_id)

    if payload.is_primary:
        prev_primary = (
            await db.execute(
                select(ClientTacAssignment).where(
                    ClientTacAssignment.client_id == client_id,
                    ClientTacAssignment.is_primary.is_(True),
                    ClientTacAssignment.tac_user_id != payload.user_id,
                )
            )
        ).scalar_one_or_none()
        if prev_primary is not None:
            prev_primary.is_primary = False
            await db.flush()

    existing = (
        await db.execute(
            select(ClientTacAssignment).where(
                ClientTacAssignment.client_id == client_id,
                ClientTacAssignment.tac_user_id == payload.user_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.is_primary = payload.is_primary
    else:
        db.add(
            ClientTacAssignment(
                client_id=client_id,
                tac_user_id=payload.user_id,
                is_primary=payload.is_primary,
            )
        )
    await db.commit()
    return {"ok": True}


@router.delete(
    "/{client_id}/tacs/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_tac_from_client(
    client_id: int,
    user_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(ClientTacAssignment).where(
                ClientTacAssignment.client_id == client_id,
                ClientTacAssignment.tac_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Assignment not found"
        )
    await db.delete(row)
    await db.commit()


@router.put("/{client_id}/tacs/{user_id}/toggle-primary")
async def toggle_tac_primary(
    client_id: int,
    user_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Flip `is_primary` flag for a TAC on a client, demoting any other primary."""
    row = (
        await db.execute(
            select(ClientTacAssignment).where(
                ClientTacAssignment.client_id == client_id,
                ClientTacAssignment.tac_user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Assignment not found"
        )

    if not row.is_primary:
        prev_primary = (
            await db.execute(
                select(ClientTacAssignment).where(
                    ClientTacAssignment.client_id == client_id,
                    ClientTacAssignment.is_primary.is_(True),
                    ClientTacAssignment.tac_user_id != user_id,
                )
            )
        ).scalar_one_or_none()
        if prev_primary is not None:
            prev_primary.is_primary = False
            await db.flush()

    row.is_primary = not row.is_primary
    await db.commit()
    return {"ok": True, "is_primary": row.is_primary}
