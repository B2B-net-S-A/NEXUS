"""FX admin endpoints — fetch NBP rates + list cached rows."""

from datetime import date, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.fx_rate import FxRate
from app.services.fx_service import backfill_nbp_rates, fetch_and_store_nbp_today

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
    """Admin trigger — fetches NBP table A and stores any missing rows.

    UWAGA: pobiera WYŁĄCZNIE dzisiejsze notowanie. Luki w PRZESZŁOŚCI (a to
    one wywołują `degraded.fx` w kokpicie zarządu) zasypuje dopiero
    `POST /api/fx/backfill`.
    """
    inserted = await fetch_and_store_nbp_today()
    return {"inserted": inserted}


# Domyślnie dwa lata wstecz: `rates_to_pln_by_date` szuka najnowszego kursu
# NIE PÓŹNIEJSZEGO niż granica miesiąca, więc wystarczy jedno notowanie przed
# najstarszym pytanym miesiącem, żeby cała seria przestała wypadać z sum.
_BACKFILL_DEFAULT_DAYS = 730


@router.post("/backfill")
async def backfill_rates(
    current_user: AdminUser,
    currency: str = Query(..., min_length=3, max_length=3),
    start: date | None = Query(None, description="Domyślnie 2 lata wstecz."),
    end: date | None = Query(None, description="Domyślnie dzisiaj."),
):
    """Dociągnij HISTORYCZNE kursy jednej waluty z NBP.

    Powstało z realnej luki na produkcji: kokpit zarządu raportował siedem
    kolejnych miesięcy (2025-10 … 2026-04) z kwotami EUR POMINIĘTYMI w sumach,
    a komunikat podpowiadał `POST /api/fx/refresh` — który pobiera tylko
    dzisiejszą tabelę i tej luki nie ruszał.

    Idempotentne. `failed_ranges` w odpowiedzi jest CELOWO jawne: `inserted: 0`
    samo w sobie nie odróżnia „wszystko już było w cache'u" od „NBP nie oddał
    ani jednego zakresu".
    """
    today = date.today()
    resolved_end = end or today
    resolved_start = start or (resolved_end - timedelta(days=_BACKFILL_DEFAULT_DAYS))
    try:
        return await backfill_nbp_rates(currency, resolved_start, resolved_end)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
