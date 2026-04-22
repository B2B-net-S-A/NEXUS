"""KPI Coach API.

Endpoint `GET /api/kpis/me/today` — zwraca bieżący progres current_user
względem wszystkich KPI z katalogu. Używane przez widget `MyKpiWidget`
w TopbarV2 i DashboardV2.

Inne endpointy (targets CRUD, historia nudge'y, per-user lookup dla
delivery_leada) dodawane w kolejnych fazach.
"""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.user import UserRole
from app.services.kpi_coach_service import run_scheduled_sweep
from app.services.kpi_engine import evaluate_user_kpis

router = APIRouter()


class KpiResultSchema(BaseModel):
    """DTO zwracany do frontendu. Lustro dla `KpiResult` z kpi_engine."""

    kpi_id: str
    period: str  # "day" | "week" | "month"
    title_pl: str
    description_pl: str
    target: int
    current: int
    progress_pct: float
    state: str  # "on_track" | "ahead" | "behind" | "hit" | "missed"
    deadline_hours_left: float


def _to_schema(kpi_result) -> KpiResultSchema:
    return KpiResultSchema(
        kpi_id=kpi_result.kpi_id,
        period=kpi_result.period.value,
        title_pl=kpi_result.title_pl,
        description_pl=kpi_result.description_pl,
        target=kpi_result.target,
        current=kpi_result.current,
        progress_pct=round(kpi_result.progress_pct, 1),
        state=kpi_result.state,
        deadline_hours_left=round(kpi_result.deadline_hours_left, 2),
    )


# Role, które nie wykonują pracy operacyjnej — nie pokazujemy im widgeta.
_NON_OPERATIONAL_ROLES = {
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.user,
}


@router.get("/me/today", response_model=List[KpiResultSchema])
async def get_my_kpis_today(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[KpiResultSchema]:
    """Bieżący progres current_user względem wszystkich KPI.

    - Filtruje KPI dla których target==0 (rola nie dotyczy).
    - Dla ról nie-operacyjnych (admin, delivery_lead, ...) zwraca pustą
      listę — widget nie powinien im się pokazywać.
    """
    if current_user.role in _NON_OPERATIONAL_ROLES:
        return []

    results = await evaluate_user_kpis(db, user=current_user)
    return [_to_schema(r) for r in results if r.target > 0]


@router.get("/users/{user_id}/today", response_model=List[KpiResultSchema])
async def get_user_kpis_today(
    user_id: int,
    _: RecruiterPlus,  # tylko zalogowany user (późniejsze RBAC dla managera)
    db: AsyncSession = Depends(get_db),
) -> list[KpiResultSchema]:
    """Progres dowolnego usera. Używane przez admina/delivery_leada do
    monitorowania teamu. W MVP pozwala też rekruterowi sprawdzić kogoś
    innego — zmieni się gdy Faza D doda admin UI z właściwym RBAC."""
    from sqlalchemy import select

    from app.models.user import User

    user = await db.scalar(select(User).where(User.id == user_id))
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Użytkownik nie znaleziony",
        )
    results = await evaluate_user_kpis(db, user=user)
    return [_to_schema(r) for r in results if r.target > 0]


# ── Admin: manual trigger for E2E smoke-tests ──────────────────────────────


class SweepCountersSchema(BaseModel):
    users: int
    praise: int
    remind: int
    eod: int
    skipped_dedup: int
    skipped_optout: int


@router.post("/admin/trigger-sweep", response_model=SweepCountersSchema)
async def admin_trigger_kpi_coach_sweep(
    _: AdminUser,
    db: AsyncSession = Depends(get_db),
    force: bool = True,
    target_user_id: int | None = None,
) -> SweepCountersSchema:
    """Admin-only: ręcznie odpala jeden cykl `run_scheduled_sweep`.

    Przydatne do:
    - Smoke-testów po godzinach pracy (domyślnie `force=true` obchodzi
      gate quiet hours 09:00–17:30 Warsaw).
    - Targetowanego testu per user (`target_user_id=N`) — emituje nudge'e
      tylko dla wskazanego usera, np. dla smoke-test account'u Marta.

    Zwraca counters (users processed, praise/remind/eod emitted, skipped).
    """
    counters = await run_scheduled_sweep(
        db, force=force, target_user_id=target_user_id
    )
    await db.commit()
    return SweepCountersSchema(**counters)
