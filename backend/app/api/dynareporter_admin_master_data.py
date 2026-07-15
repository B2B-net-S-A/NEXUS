"""DynaReporter Admin — Master Data (Klienci + Konsultanci) CRUD.

Port `MasterDataManager.tsx` z artur-t-96/InfraReporter.
Full CRUD nad dr_clients + dr_consultants tables.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user import UserRole

logger = logging.getLogger("dynareporter.admin_master_data")

router = APIRouter()


class DrClientRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool = True
    placements_count: int = 0


class DrConsultantRow(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    is_active: bool = True
    default_cost_rate: float = 0.0
    default_revenue_rate: float = 0.0


class DrClientCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True


class DrClientUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None


class DrConsultantCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=200)
    is_active: bool = True
    default_cost_rate: float = Field(default=0.0, ge=0)
    default_revenue_rate: float = Field(default=0.0, ge=0)


class DrConsultantUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = Field(default=None, min_length=1, max_length=200)
    is_active: bool | None = None
    default_cost_rate: float | None = Field(default=None, ge=0)
    default_revenue_rate: float | None = Field(default=None, ge=0)


def _require_admin(current_user) -> None:  # type: ignore[no-untyped-def]
    if not current_user.has_role(UserRole.admin):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Wymagana rola admin"
        )


# ============================================================
# CLIENTS
# ============================================================


@router.get(
    "/clients",
    response_model=list[DrClientRow],
    summary="Lista klientów (dr_clients) z aggregated stats",
)
async def list_clients(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> list[DrClientRow]:
    """Read-only lista wszystkich klientów z dr_clients + placements count."""
    sql = text(
        """
        SELECT
            c.id,
            c.name,
            COALESCE(c.is_active, true) AS is_active,
            (SELECT count(*) FROM dr_placement_details p WHERE p.client_id = c.id)::int
                AS placements_count
        FROM dr_clients c
        ORDER BY c.name
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        DrClientRow(
            id=r.id,
            name=r.name or "",
            is_active=r.is_active,
            placements_count=r.placements_count or 0,
        )
        for r in rows
    ]


@router.post(
    "/clients",
    response_model=DrClientRow,
    status_code=status.HTTP_201_CREATED,
    summary="Dodaj klienta (admin only)",
)
async def create_client(
    payload: DrClientCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DrClientRow:
    _require_admin(current_user)
    name_trim = payload.name.strip()
    if not name_trim:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nazwa klienta nie może być pusta",
        )
    # Check duplicate
    dup = (
        await db.execute(
            text("SELECT id FROM dr_clients WHERE LOWER(name) = LOWER(:n)"),
            {"n": name_trim},
        )
    ).first()
    if dup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Klient '{name_trim}' już istnieje",
        )
    result = await db.execute(
        text(
            """
            INSERT INTO dr_clients (name, is_active, created_at)
            VALUES (:name, :is_active, CURRENT_TIMESTAMP)
            RETURNING id
            """
        ),
        {"name": name_trim, "is_active": payload.is_active},
    )
    new_id = result.scalar_one()
    await db.commit()
    logger.info(
        "Client created: id=%s name=%s by admin=%s",
        new_id,
        name_trim,
        current_user.id,
    )
    return DrClientRow(
        id=new_id, name=name_trim, is_active=payload.is_active, placements_count=0
    )


@router.patch(
    "/clients/{client_id}",
    response_model=DrClientRow,
    summary="Edytuj klienta (admin only)",
)
async def update_client(
    client_id: int,
    payload: DrClientUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DrClientRow:
    _require_admin(current_user)
    # Build dynamic update
    fields: dict[str, object] = {}
    if payload.name is not None:
        n = payload.name.strip()
        if not n:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nazwa klienta nie może być pusta",
            )
        fields["name"] = n
    if payload.is_active is not None:
        fields["is_active"] = payload.is_active
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Brak pól do aktualizacji",
        )
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "id": client_id}
    result = await db.execute(
        text(
            f"UPDATE dr_clients SET {set_clause} WHERE id = :id RETURNING id, name, COALESCE(is_active, true) AS is_active"  # noqa: S608 — set_clause from whitelist
        ),
        params,
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Klient id={client_id} nie istnieje",
        )
    await db.commit()
    logger.info(
        "Client updated: id=%s fields=%s by admin=%s",
        client_id,
        list(fields.keys()),
        current_user.id,
    )
    # Re-fetch placements_count
    count_row = (
        await db.execute(
            text(
                "SELECT count(*)::int FROM dr_placement_details WHERE client_id = :id"
            ),
            {"id": client_id},
        )
    ).scalar_one()
    return DrClientRow(
        id=row.id,
        name=row.name or "",
        is_active=row.is_active,
        placements_count=count_row or 0,
    )


@router.delete(
    "/clients/{client_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # FastAPI 0.115 strict — 204 must not have body
    summary="Soft-delete klienta (is_active=false, admin only)",
)
async def delete_client(
    client_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete — sets is_active=false. Klient z placementami nie jest
    fizycznie usuwany żeby zachować integralność dr_placement_details."""
    _require_admin(current_user)
    result = await db.execute(
        text("UPDATE dr_clients SET is_active = false WHERE id = :id RETURNING id"),
        {"id": client_id},
    )
    if not result.first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Klient id={client_id} nie istnieje",
        )
    await db.commit()
    logger.info("Client soft-deleted: id=%s by admin=%s", client_id, current_user.id)


# ============================================================
# CONSULTANTS
# ============================================================


@router.get(
    "/consultants",
    response_model=list[DrConsultantRow],
    summary="Lista konsultantów (dr_consultants) z client name",
)
async def list_consultants(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> list[DrConsultantRow]:
    """Read-only lista wszystkich konsultantów + default rates."""
    sql = text(
        """
        SELECT
            k.id,
            k.name,
            COALESCE(k.is_active, true) AS is_active,
            COALESCE(k.default_cost_rate, 0)::float AS default_cost_rate,
            COALESCE(k.default_revenue_rate, 0)::float AS default_revenue_rate
        FROM dr_consultants k
        ORDER BY k.name
        """
    )
    rows = (await db.execute(sql)).all()
    return [
        DrConsultantRow(
            id=r.id,
            name=r.name or "",
            is_active=r.is_active,
            default_cost_rate=r.default_cost_rate or 0.0,
            default_revenue_rate=r.default_revenue_rate or 0.0,
        )
        for r in rows
    ]


@router.post(
    "/consultants",
    response_model=DrConsultantRow,
    status_code=status.HTTP_201_CREATED,
    summary="Dodaj konsultanta (admin only)",
)
async def create_consultant(
    payload: DrConsultantCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DrConsultantRow:
    _require_admin(current_user)
    name_trim = payload.name.strip()
    if not name_trim:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Nazwa konsultanta nie może być pusta",
        )
    dup = (
        await db.execute(
            text("SELECT id FROM dr_consultants WHERE LOWER(name) = LOWER(:n)"),
            {"n": name_trim},
        )
    ).first()
    if dup:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Konsultant '{name_trim}' już istnieje",
        )
    result = await db.execute(
        text(
            """
            INSERT INTO dr_consultants (
                name, is_active, default_cost_rate, default_revenue_rate, created_at
            )
            VALUES (:name, :is_active, :cost, :revenue, CURRENT_TIMESTAMP)
            RETURNING id
            """
        ),
        {
            "name": name_trim,
            "is_active": payload.is_active,
            "cost": payload.default_cost_rate,
            "revenue": payload.default_revenue_rate,
        },
    )
    new_id = result.scalar_one()
    await db.commit()
    logger.info(
        "Consultant created: id=%s name=%s cost=%s revenue=%s by admin=%s",
        new_id,
        name_trim,
        payload.default_cost_rate,
        payload.default_revenue_rate,
        current_user.id,
    )
    return DrConsultantRow(
        id=new_id,
        name=name_trim,
        is_active=payload.is_active,
        default_cost_rate=payload.default_cost_rate,
        default_revenue_rate=payload.default_revenue_rate,
    )


@router.patch(
    "/consultants/{consultant_id}",
    response_model=DrConsultantRow,
    summary="Edytuj konsultanta (admin only)",
)
async def update_consultant(
    consultant_id: int,
    payload: DrConsultantUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> DrConsultantRow:
    _require_admin(current_user)
    fields: dict[str, object] = {}
    if payload.name is not None:
        n = payload.name.strip()
        if not n:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Nazwa konsultanta nie może być pusta",
            )
        fields["name"] = n
    if payload.is_active is not None:
        fields["is_active"] = payload.is_active
    if payload.default_cost_rate is not None:
        fields["default_cost_rate"] = payload.default_cost_rate
    if payload.default_revenue_rate is not None:
        fields["default_revenue_rate"] = payload.default_revenue_rate
    if not fields:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Brak pól do aktualizacji",
        )
    set_clause = ", ".join(f"{k} = :{k}" for k in fields)
    params = {**fields, "id": consultant_id}
    result = await db.execute(
        text(
            f"UPDATE dr_consultants SET {set_clause} WHERE id = :id RETURNING id, name, COALESCE(is_active, true) AS is_active, COALESCE(default_cost_rate, 0)::float AS default_cost_rate, COALESCE(default_revenue_rate, 0)::float AS default_revenue_rate"  # noqa: S608 — set_clause from whitelist
        ),
        params,
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Konsultant id={consultant_id} nie istnieje",
        )
    await db.commit()
    logger.info(
        "Consultant updated: id=%s fields=%s by admin=%s",
        consultant_id,
        list(fields.keys()),
        current_user.id,
    )
    return DrConsultantRow(
        id=row.id,
        name=row.name or "",
        is_active=row.is_active,
        default_cost_rate=row.default_cost_rate or 0.0,
        default_revenue_rate=row.default_revenue_rate or 0.0,
    )


@router.delete(
    "/consultants/{consultant_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # FastAPI 0.115 strict — 204 must not have body
    summary="Soft-delete konsultanta (is_active=false, admin only)",
)
async def delete_consultant(
    consultant_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Soft-delete — sets is_active=false."""
    _require_admin(current_user)
    result = await db.execute(
        text("UPDATE dr_consultants SET is_active = false WHERE id = :id RETURNING id"),
        {"id": consultant_id},
    )
    if not result.first():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Konsultant id={consultant_id} nie istnieje",
        )
    await db.commit()
    logger.info(
        "Consultant soft-deleted: id=%s by admin=%s",
        consultant_id,
        current_user.id,
    )
