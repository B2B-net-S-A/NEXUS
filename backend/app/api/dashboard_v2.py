"""Canonical, role-specific Dashboard v2 endpoints."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import (
    AnalyticsCapability,
    require_capability,
    user_has_capability,
)
from app.analytics.periods import Period, PeriodError, resolve_period
from app.api.deps import (
    AdminUser,
    DeliveryLeadPlus,
    HeadOfRecruitmentPlus,
    OperationalUser,
    require_roles,
)
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.dashboard_v2 import (
    AdminOpsDashboardResponse,
    DeliveryLeadDashboardResponse,
    FinanceDashboardResponse,
    HeadOfRecruitmentDashboardResponse,
    MyWorkDashboardResponse,
    RecruitmentStatsDashboardResponse,
)
from app.services.dashboard_v2 import (
    build_admin_ops_dashboard,
    build_delivery_lead_dashboard,
    build_finance_dashboard,
    build_head_of_recruitment_dashboard,
    build_my_work_dashboard,
    build_recruitment_stats_dashboard,
)

router = APIRouter()

Database = Annotated[AsyncSession, Depends(get_db)]
MyWorkUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.sourcer,
            UserRole.tac,
            UserRole.recruiter,
        )
    ),
]
FinanceUser = Annotated[
    User,
    Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
]


def parse_dashboard_period(
    period: str = Query("month"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> Period:
    """Resolve the shared Warsaw-calendar analytics period contract."""

    try:
        return resolve_period(period, date_from=date_from, date_to=date_to)
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc


DashboardPeriod = Annotated[Period, Depends(parse_dashboard_period)]


@router.get("/admin-ops", response_model=AdminOpsDashboardResponse)
async def admin_ops_dashboard(
    request: Request,
    current_user: AdminUser,
    db: Database,
) -> AdminOpsDashboardResponse:
    return await build_admin_ops_dashboard(request, current_user, db)


@router.get("/delivery-lead", response_model=DeliveryLeadDashboardResponse)
async def delivery_lead_dashboard(
    current_user: DeliveryLeadPlus,
    db: Database,
    period: DashboardPeriod,
) -> DeliveryLeadDashboardResponse:
    return await build_delivery_lead_dashboard(current_user, db, period)


@router.get(
    "/head-of-recruitment",
    response_model=HeadOfRecruitmentDashboardResponse,
)
async def head_of_recruitment_dashboard(
    current_user: HeadOfRecruitmentPlus,
    db: Database,
    period: DashboardPeriod,
) -> HeadOfRecruitmentDashboardResponse:
    return await build_head_of_recruitment_dashboard(current_user, db, period)


@router.get("/my-work", response_model=MyWorkDashboardResponse)
async def my_work_dashboard(
    current_user: MyWorkUser,
    db: Database,
    period: DashboardPeriod,
) -> MyWorkDashboardResponse:
    return await build_my_work_dashboard(current_user, db, period)


@router.get(
    "/recruitment-stats",
    response_model=RecruitmentStatsDashboardResponse,
)
async def recruitment_stats_dashboard(
    current_user: OperationalUser,
    db: Database,
    period: DashboardPeriod,
) -> RecruitmentStatsDashboardResponse:
    """Sekcja „Statystyki rekrutacji" — wspólna dla wszystkich presetów.

    Guard `OperationalUser` (nie capability): payload jest z natury imienny
    (tabela per osoba, podia, wyścigi, LinkedIn), więc finance — persona z
    zakazem danych osobowych — i legacy `user` dostają 403. Dane org-wide
    dla każdego uprawnionego; default `period=month` (decyzja właściciela).
    """
    return await build_recruitment_stats_dashboard(current_user, db, period)


@router.get("/finance", response_model=FinanceDashboardResponse)
async def finance_dashboard(
    current_user: FinanceUser,
    db: Database,
    period: DashboardPeriod,
    tab: Literal["operations", "executive"] = Query("operations"),
) -> FinanceDashboardResponse:
    if tab == "executive" and not user_has_capability(
        current_user,
        AnalyticsCapability.VIEW_EXECUTIVE,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requires analytics capability: view_executive",
        )
    return await build_finance_dashboard(
        current_user,
        db,
        period,
        tab=tab,
    )
