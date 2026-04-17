"""FX admin endpoints — fetch NBP rates + list cached rows."""

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.fx_rate import FxRate
from app.services.fx_service import fetch_and_store_nbp_today

router = APIRouter()


class FxRateRow(BaseModel):
    id: int
    effective_date: str
    currency: str
    rate_to_pln: float
    source: str

    model_config = {"from_attributes": True}


@router.get("", response_model=List[FxRateRow])
async def list_rates(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 50,
):
    res = await db.execute(
        select(FxRate)
        .order_by(FxRate.effective_date.desc(), FxRate.currency)
        .limit(limit)
    )
    return [
        FxRateRow(
            id=r.id,
            effective_date=r.effective_date.isoformat(),
            currency=r.currency,
            rate_to_pln=float(r.rate_to_pln),
            source=r.source,
        )
        for r in res.scalars().all()
    ]


@router.post("/refresh")
async def refresh_rates(current_user: AdminUser):
    """Admin trigger — fetches NBP table A and stores any missing rows."""
    inserted = await fetch_and_store_nbp_today()
    return {"inserted": inserted}
