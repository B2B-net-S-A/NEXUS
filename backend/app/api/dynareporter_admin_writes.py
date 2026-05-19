"""DynaReporter Admin — write endpoints dla Sales + Przetargi.

Pozwala adminowi dodawać dane:
- Sales projects + people + weekly leads/offers
- Przetargi projects + allocations + costs

Port `SalesDataEntry.tsx` + `PrzetargiDataEntry.tsx` z artur-t-96/InfraReporter.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user import UserRole

router = APIRouter()


def _require_admin(current_user) -> None:  # type: ignore[no-untyped-def]
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Wymagana rola admin"
        )


# ---------------------------------------------------------------------------
# Sales — write endpoints
# ---------------------------------------------------------------------------


class SalesProjectCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=255)
    bdm_id: int | None = None
    is_active: bool = True


class SalesPersonCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=255)
    role: str = Field(pattern=r"^(hod|bdm|sdr)$")
    is_hod: bool = False
    is_active: bool = True


class WeeklyActivityUpsert(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    week_start: date
    week_number: int = Field(ge=1, le=53)
    year: int = Field(ge=2020, le=2100)
    leads_count: int = Field(default=0, ge=0)
    offers_sent: int = Field(default=0, ge=0)


@router.post(
    "/sales/projects",
    summary="Dodaj sales project (admin only)",
    tags=["dynareporter-admin-writes"],
)
async def add_sales_project(
    payload: SalesProjectCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    sql = text(
        """
        INSERT INTO dr_sales_projects (name, bdm_id, is_active)
        VALUES (:name, :bdm, :act)
        RETURNING id
        """
    )
    result = await db.execute(
        sql,
        {"name": payload.name, "bdm": payload.bdm_id, "act": payload.is_active},
    )
    await db.commit()
    row = result.first()
    return {"id": row.id if row else None, "ok": True}


@router.post(
    "/sales/people",
    summary="Dodaj sales person (admin only)",
    tags=["dynareporter-admin-writes"],
)
async def add_sales_person(
    payload: SalesPersonCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    sql = text(
        """
        INSERT INTO dr_sales_people (name, role, is_hod, is_active)
        VALUES (:name, :role, :hod, :act)
        RETURNING id
        """
    )
    result = await db.execute(
        sql,
        {
            "name": payload.name,
            "role": payload.role,
            "hod": payload.is_hod,
            "act": payload.is_active,
        },
    )
    await db.commit()
    row = result.first()
    return {"id": row.id if row else None, "ok": True}


@router.post(
    "/sales/weekly-activity",
    summary="Upsert weekly activity (admin only)",
    tags=["dynareporter-admin-writes"],
)
async def upsert_weekly_activity(
    payload: WeeklyActivityUpsert,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    # Najpierw spróbuj find po week_start
    existing = (
        await db.execute(
            text("SELECT id FROM dr_weekly_sales_activity WHERE week_start = :ws"),
            {"ws": payload.week_start},
        )
    ).first()
    if existing:
        await db.execute(
            text(
                """
                UPDATE dr_weekly_sales_activity SET
                    week_number = :wn,
                    year = :yr,
                    leads_count = :leads,
                    offers_sent = :offers
                WHERE id = :id
                """
            ),
            {
                "wn": payload.week_number,
                "yr": payload.year,
                "leads": payload.leads_count,
                "offers": payload.offers_sent,
                "id": existing.id,
            },
        )
        await db.commit()
        return {"id": existing.id, "ok": True, "updated": True}
    result = await db.execute(
        text(
            """
            INSERT INTO dr_weekly_sales_activity
                (week_start, week_number, year, leads_count, offers_sent)
            VALUES (:ws, :wn, :yr, :leads, :offers)
            RETURNING id
            """
        ),
        {
            "ws": payload.week_start,
            "wn": payload.week_number,
            "yr": payload.year,
            "leads": payload.leads_count,
            "offers": payload.offers_sent,
        },
    )
    await db.commit()
    row = result.first()
    return {"id": row.id if row else None, "ok": True, "updated": False}


# ---------------------------------------------------------------------------
# Przetargi — write endpoints
# ---------------------------------------------------------------------------


class PrzetargiProjectCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str = Field(min_length=1, max_length=255)
    client_id: int | None = None
    is_active: bool = True


class PrzetargiAllocationUpsert(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    consultant_id: int
    month: date
    hours: float = Field(ge=0)
    cost_rate: float = Field(ge=0)
    revenue_rate: float = Field(ge=0)


class PrzetargiCostCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    project_id: int
    month: date
    description: str = Field(min_length=1, max_length=255)
    value: float
    category: str = Field(default="other", max_length=50)


@router.post(
    "/przetargi/projects",
    summary="Dodaj przetargi project (admin only)",
    tags=["dynareporter-admin-writes"],
)
async def add_przetargi_project(
    payload: PrzetargiProjectCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    sql = text(
        """
        INSERT INTO dr_przetargi_projects (name, client_id, is_active)
        VALUES (:name, :cid, :act)
        RETURNING id
        """
    )
    result = await db.execute(
        sql,
        {"name": payload.name, "cid": payload.client_id, "act": payload.is_active},
    )
    await db.commit()
    row = result.first()
    return {"id": row.id if row else None, "ok": True}


@router.post(
    "/przetargi/allocations",
    summary="Upsert przetargi allocation (admin only)",
    tags=["dynareporter-admin-writes"],
)
async def upsert_przetargi_allocation(
    payload: PrzetargiAllocationUpsert,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Upsert po (project_id, consultant_id, month) — assuming unique constraint
    or DELETE+INSERT pattern jeśli brak constraintu."""
    _require_admin(current_user)
    # DELETE+INSERT pattern (brak unique constraint w schemie)
    await db.execute(
        text(
            """
            DELETE FROM dr_przetargi_allocations
            WHERE project_id = :pid AND consultant_id = :cid AND month = :m
            """
        ),
        {"pid": payload.project_id, "cid": payload.consultant_id, "m": payload.month},
    )
    result = await db.execute(
        text(
            """
            INSERT INTO dr_przetargi_allocations
                (project_id, consultant_id, month, hours, cost_rate, revenue_rate)
            VALUES (:pid, :cid, :m, :h, :cr, :rr)
            RETURNING id
            """
        ),
        {
            "pid": payload.project_id,
            "cid": payload.consultant_id,
            "m": payload.month,
            "h": payload.hours,
            "cr": payload.cost_rate,
            "rr": payload.revenue_rate,
        },
    )
    await db.commit()
    row = result.first()
    return {"id": row.id if row else None, "ok": True}


@router.post(
    "/przetargi/costs",
    summary="Dodaj koszt projektu (admin only)",
    tags=["dynareporter-admin-writes"],
)
async def add_przetargi_cost(
    payload: PrzetargiCostCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    _require_admin(current_user)
    sql = text(
        """
        INSERT INTO dr_przetargi_project_costs
            (project_id, month, description, value, category)
        VALUES (:pid, :m, :d, :v, :cat)
        RETURNING id
        """
    )
    result = await db.execute(
        sql,
        {
            "pid": payload.project_id,
            "m": payload.month,
            "d": payload.description,
            "v": payload.value,
            "cat": payload.category,
        },
    )
    await db.commit()
    row = result.first()
    return {"id": row.id if row else None, "ok": True}
