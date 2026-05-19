"""DynaReporter Admin — Master Data (Klienci + Konsultanci) read-only viewer.

Port `MasterDataManager.tsx` z artur-t-96/InfraReporter.
Read-only views nad dr_clients + dr_consultants tables.

Pełne CRUD (add/edit/delete clients/consultants) zaplanowane na kolejną sesję.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db

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
