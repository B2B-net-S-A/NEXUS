"""Canonical, role-specific Dashboard v2 endpoints."""

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import (
    AnalyticsCapability,
    require_capability,
    user_has_capability,
)
from app.analytics.periods import Period, PeriodError, resolve_period
from app.api.recruitment_access import ensure_job_membership
from app.api.deps import (
    AdminUser,
    DeliveryLeadPlus,
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
from app.schemas.recruitment_operations import (
    RecruitmentOperationsDetailResponse,
    RecruitmentOperationsFavorite,
    RecruitmentOperationsFavoriteUpdate,
    RecruitmentOperationsListResponse,
    RecruitmentOperationsPreset,
)
from app.schemas.recruitment_activity import (
    RecruitmentActivityDetailResponse,
    RecruitmentActivityMetric,
    RecruitmentActivitySummaryResponse,
    RecruitmentActivityWindow,
)
from app.services.dashboard_v2 import (
    build_admin_ops_dashboard,
    build_delivery_lead_dashboard,
    build_finance_dashboard,
    build_head_of_recruitment_dashboard,
    build_my_work_dashboard,
    build_recruitment_stats_dashboard,
)
from app.services.recruitment_operations import (
    get_recruitment_operation_detail,
    list_recruitment_operations,
    set_recruitment_operation_favorite,
)
from app.services.recruitment_activity import (
    build_recruitment_activity_summary,
    list_recruitment_activity_details,
)
from app.services.kpi_engine import WARSAW

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
HeadOfRecruitmentDashboardUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.talent_community_manager,
        )
    ),
]
FinanceUser = Annotated[
    User,
    Depends(require_capability(AnalyticsCapability.VIEW_FINANCE)),
]
RecruitmentOperationsUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
            UserRole.tac,
            UserRole.recruiter,
            UserRole.finance,
            UserRole.sourcer,
        )
    ),
]

_RECRUITMENT_OPERATIONS_PRESET_ROLES: dict[
    RecruitmentOperationsPreset, tuple[UserRole, ...]
] = {
    "admin-ops": (),  # Empty means admin-only; the shortcut below handles admins.
    "delivery-lead": (UserRole.delivery_lead,),
    "finance": (UserRole.finance,),
    "head-of-recruitment": (
        UserRole.head_of_recruitment,
        UserRole.talent_community_manager,
    ),
    "my-work": (UserRole.recruiter, UserRole.tac, UserRole.sourcer),
}


def ensure_recruitment_operations_preset(
    user: User,
    preset: RecruitmentOperationsPreset,
) -> None:
    """Keep this shared surface aligned with the selected role dashboard."""

    if user.has_role(UserRole.admin):
        # `/api/auth/me` intentionally advertises every role dashboard to admin.
        return
    required_roles = _RECRUITMENT_OPERATIONS_PRESET_ROLES[preset]
    if required_roles and user.has_any_role(*required_roles):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"Brak dostępu do presetu dashboardu: {preset}",
    )


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
    current_user: HeadOfRecruitmentDashboardUser,
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
    (tabela per osoba, podia, wyścigi, LinkedIn), więc legacy `user` dostaje 403.

    UWAGA — finance PRZECHODZI. `OperationalUser` zawiera `UserRole.finance`
    od 19.08 (pełny dostęp operacyjny, tier recruitera). Do 20.08 ten docstring
    twierdził coś przeciwnego i to właśnie on kazał autorowi testu FE zapisać
    bramkę węższą niż API — sekcja nie renderowała się finansom, choć endpoint
    odpowiadał im 200. Jeśli kiedyś finance ma tu NIE wchodzić, właściwą zmianą
    jest ZAWĘŻENIE TEGO GUARDU, nie bramka na froncie: front węższy niż API
    odtwarza dokładnie ten rozjazd, tylko ciszej.

    Dane org-wide dla każdego uprawnionego; default `period=month`.
    """
    return await build_recruitment_stats_dashboard(current_user, db, period)


@router.get(
    "/recruitment-operations",
    response_model=RecruitmentOperationsListResponse,
)
async def recruitment_operations_list(
    current_user: RecruitmentOperationsUser,
    db: Database,
    preset: RecruitmentOperationsPreset = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    q: str | None = Query(None, max_length=200),
    category_id: int | None = Query(None, ge=1),
    mine_only: bool = Query(False),
) -> RecruitmentOperationsListResponse:
    ensure_recruitment_operations_preset(current_user, preset)
    return await list_recruitment_operations(
        db,
        current_user,
        preset=preset,
        page=page,
        page_size=page_size,
        q=q,
        category_id=category_id,
        mine_only=mine_only,
    )


@router.get(
    "/recruitment-activity",
    response_model=RecruitmentActivitySummaryResponse,
)
async def recruitment_activity_summary(
    current_user: RecruitmentOperationsUser,
    db: Database,
    day: date | None = Query(None),
    month: date | None = Query(None),
    subject_user_id: int | None = Query(None, ge=1),
    scope: Literal["auto", "team"] = Query("auto"),
) -> RecruitmentActivitySummaryResponse:
    """Drillable personal/team KPI activity for the unified dashboard."""

    selected_day = day or datetime.now(WARSAW).date()
    selected_month = month or selected_day.replace(day=1)
    return await build_recruitment_activity_summary(
        db,
        current_user,
        selected_day=selected_day,
        selected_month=selected_month,
        subject_user_id=subject_user_id,
        team_scope=scope == "team",
    )


@router.get(
    "/recruitment-activity/details",
    response_model=RecruitmentActivityDetailResponse,
)
async def recruitment_activity_details(
    current_user: RecruitmentOperationsUser,
    db: Database,
    metric: RecruitmentActivityMetric = Query(...),
    window: RecruitmentActivityWindow = Query(...),
    day: date | None = Query(None),
    month: date | None = Query(None),
    subject_user_id: int | None = Query(None, ge=1),
    scope: Literal["auto", "team"] = Query("auto"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
) -> RecruitmentActivityDetailResponse:
    """Candidate/job rows behind one visible KPI number."""

    selected_day = day or datetime.now(WARSAW).date()
    selected_month = month or selected_day.replace(day=1)
    return await list_recruitment_activity_details(
        db,
        current_user,
        metric=metric,
        window=window,
        selected_day=selected_day,
        selected_month=selected_month,
        subject_user_id=subject_user_id,
        team_scope=scope == "team",
        page=page,
        page_size=page_size,
    )


@router.get(
    "/recruitment-operations/{job_id}",
    response_model=RecruitmentOperationsDetailResponse,
)
async def recruitment_operations_detail(
    job_id: int,
    current_user: RecruitmentOperationsUser,
    db: Database,
    preset: RecruitmentOperationsPreset = Query(...),
) -> RecruitmentOperationsDetailResponse:
    ensure_recruitment_operations_preset(current_user, preset)
    if preset not in {"delivery-lead", "finance"}:
        await ensure_job_membership(
            db,
            current_user,
            job_id,
            oversight_bypass=preset != "my-work",
        )
    return await get_recruitment_operation_detail(
        db,
        current_user,
        job_id,
        preset=preset,
    )


@router.put(
    "/recruitment-operations/{job_id}/favorite",
    response_model=RecruitmentOperationsFavorite | None,
)
async def recruitment_operations_favorite(
    job_id: int,
    payload: RecruitmentOperationsFavoriteUpdate,
    current_user: RecruitmentOperationsUser,
    db: Database,
    preset: RecruitmentOperationsPreset = Query(...),
) -> RecruitmentOperationsFavorite | None:
    ensure_recruitment_operations_preset(current_user, preset)
    if preset not in {"delivery-lead", "finance"}:
        await ensure_job_membership(
            db,
            current_user,
            job_id,
            oversight_bypass=preset != "my-work",
        )
    return await set_recruitment_operation_favorite(
        db,
        current_user,
        job_id,
        payload.candidate_id,
        preset=preset,
    )


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
