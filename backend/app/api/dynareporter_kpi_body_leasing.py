"""DynaReporter B.2.1 — KPI Body Leasing endpoints.

Phase B.2.1 z planu migracji DynaReportera. Pierwszy realny moduł
z danymi (po B.0+B.1 walidacji wzorca).

Endpoints:
- GET    /api/dynareporter/kpi/body-leasing/my        — moje wpisy (filtr)
- GET    /api/dynareporter/kpi/body-leasing/all       — wpisy wszystkich (admin)
- GET    /api/dynareporter/kpi/body-leasing/summary   — agregaty per okres
- GET    /api/dynareporter/kpi/body-leasing/ranking   — Liga Mistrzów input
- POST   /api/dynareporter/kpi/body-leasing           — upsert tygodniowy
- DELETE /api/dynareporter/kpi/body-leasing/{id}      — usuń wpis

Uprawnienia:
- Każdy zalogowany user widzi *swoje* wpisy (`/my`)
- `admin` / `delivery_lead` / `head_of_recruitment` widzą wszystkich (`/all`)
- Wpisy może edytować autor wpisu lub admin
- Ranking widoczny dla wszystkich (motywacja)
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.dr_kpi_body_leasing import DrKpiBodyLeasing
from app.models.user import User, UserRole
from app.schemas.dr_kpi_body_leasing import (
    DrKpiBodyLeasingCreate,
    DrKpiBodyLeasingRankingEntry,
    DrKpiBodyLeasingResponse,
    DrKpiBodyLeasingSummary,
)

router = APIRouter()


def _check_admin_or_self(current_user: User, target_user_id: int) -> None:
    """403 jeśli user nie jest adminem ani properem nie operuje na swoich danych."""
    is_admin = current_user.role in (
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    )
    if not is_admin and current_user.id != target_user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Możesz operować tylko na własnych wpisach KPI",
        )


@router.get(
    "/my",
    response_model=list[DrKpiBodyLeasingResponse],
    summary="Lista moich wpisów KPI Body Leasing",
)
async def list_my_entries(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    from_date: Optional[date] = Query(default=None, description="Data od (włącznie)"),
    to_date: Optional[date] = Query(default=None, description="Data do (włącznie)"),
) -> list[DrKpiBodyLeasingResponse]:
    """Zwraca wpisy current_user, opcjonalnie filtrowane po dacie."""
    stmt = select(DrKpiBodyLeasing).where(DrKpiBodyLeasing.user_id == current_user.id)
    if from_date:
        stmt = stmt.where(DrKpiBodyLeasing.report_date >= from_date)
    if to_date:
        stmt = stmt.where(DrKpiBodyLeasing.report_date <= to_date)
    stmt = stmt.order_by(DrKpiBodyLeasing.report_date.desc())

    result = await db.execute(stmt)
    rows = result.scalars().all()
    return [
        DrKpiBodyLeasingResponse.model_validate(
            {**row.__dict__, "user_name": current_user.name, "user_email": current_user.email}
        )
        for row in rows
    ]


@router.get(
    "/all",
    response_model=list[DrKpiBodyLeasingResponse],
    summary="Lista wpisów wszystkich userów (admin/DL/HoR)",
)
async def list_all_entries(
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None, description="Filtr per user"),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
) -> list[DrKpiBodyLeasingResponse]:
    """Endpoint dla widoków Liga Mistrzów / Board — wszystkie wpisy."""
    # Tylko admin / DL / HoR mogą widzieć cudze
    is_privileged = current_user.role in (
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    )
    if not is_privileged and user_id and user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do widoku cudzych wpisów",
        )

    stmt = (
        select(DrKpiBodyLeasing, User.name, User.email)
        .join(User, User.id == DrKpiBodyLeasing.user_id)
    )
    if user_id:
        stmt = stmt.where(DrKpiBodyLeasing.user_id == user_id)
    elif not is_privileged:
        # Non-privileged user widzi tylko swoje (bez przekazania user_id)
        stmt = stmt.where(DrKpiBodyLeasing.user_id == current_user.id)
    if from_date:
        stmt = stmt.where(DrKpiBodyLeasing.report_date >= from_date)
    if to_date:
        stmt = stmt.where(DrKpiBodyLeasing.report_date <= to_date)
    stmt = stmt.order_by(DrKpiBodyLeasing.report_date.desc())

    result = await db.execute(stmt)
    return [
        DrKpiBodyLeasingResponse.model_validate(
            {**row.__dict__, "user_name": user_name, "user_email": user_email}
        )
        for row, user_name, user_email in result.all()
    ]


@router.get(
    "/summary",
    response_model=DrKpiBodyLeasingSummary,
    summary="Agregaty KPI Body Leasing per okres",
)
async def get_summary(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="month", pattern="^(week|month|quarter|year)$"),
    user_id: Optional[int] = Query(default=None),
) -> DrKpiBodyLeasingSummary:
    """Agreguje counters w wybranym oknie czasowym."""
    target_user_id = user_id if user_id is not None else current_user.id
    _check_admin_or_self(current_user, target_user_id)

    today = date.today()
    if period == "week":
        from_d = today - timedelta(days=7)
    elif period == "month":
        from_d = today - timedelta(days=30)
    elif period == "quarter":
        from_d = today - timedelta(days=90)
    else:  # year
        from_d = today - timedelta(days=365)

    stmt = select(
        func.coalesce(func.sum(DrKpiBodyLeasing.verifications), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.recommendations), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.interviews), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.placements), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.requests), 0),
        func.coalesce(func.sum(DrKpiBodyLeasing.days_worked), 0),
        func.count(DrKpiBodyLeasing.id),
    ).where(
        and_(
            DrKpiBodyLeasing.user_id == target_user_id,
            DrKpiBodyLeasing.report_date >= from_d,
            DrKpiBodyLeasing.report_date <= today,
        )
    )

    row = (await db.execute(stmt)).first()
    return DrKpiBodyLeasingSummary(
        period=period,
        from_date=from_d,
        to_date=today,
        total_verifications=row[0] or 0,
        total_recommendations=row[1] or 0,
        total_interviews=row[2] or 0,
        total_placements=row[3] or 0,
        total_requests=row[4] or 0,
        total_days_worked=row[5] or 0,
        entries_count=row[6] or 0,
    )


@router.get(
    "/ranking",
    response_model=list[DrKpiBodyLeasingRankingEntry],
    summary="Liga Mistrzów ranking (top placementów per user)",
)
async def get_ranking(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="quarter", pattern="^(month|quarter|year)$"),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[DrKpiBodyLeasingRankingEntry]:
    """Top N userów wg total_placements w wybranym oknie."""
    today = date.today()
    if period == "month":
        from_d = today - timedelta(days=30)
    elif period == "quarter":
        from_d = today - timedelta(days=90)
    else:
        from_d = today - timedelta(days=365)

    placements_sum = func.coalesce(func.sum(DrKpiBodyLeasing.placements), 0)
    stmt = (
        select(
            User.id,
            User.name,
            User.email,
            placements_sum.label("p"),
            func.coalesce(func.sum(DrKpiBodyLeasing.interviews), 0).label("i"),
            func.coalesce(func.sum(DrKpiBodyLeasing.recommendations), 0).label("r"),
            func.coalesce(func.sum(DrKpiBodyLeasing.verifications), 0).label("v"),
        )
        .join(DrKpiBodyLeasing, DrKpiBodyLeasing.user_id == User.id)
        .where(
            and_(
                DrKpiBodyLeasing.report_date >= from_d,
                DrKpiBodyLeasing.report_date <= today,
                User.is_active.is_(True),
            )
        )
        .group_by(User.id, User.name, User.email)
        .order_by(placements_sum.desc())
        .limit(limit)
    )

    rows = (await db.execute(stmt)).all()
    return [
        DrKpiBodyLeasingRankingEntry(
            user_id=uid,
            user_name=name or "",
            user_email=email or "",
            total_placements=p,
            total_interviews=i,
            total_recommendations=r,
            total_verifications=v,
            rank=rank,
        )
        for rank, (uid, name, email, p, i, r, v) in enumerate(rows, start=1)
    ]


@router.post(
    "",
    response_model=DrKpiBodyLeasingResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upsert tygodniowy wpis KPI (PK collision → UPDATE)",
)
async def upsert_entry(
    payload: DrKpiBodyLeasingCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None, description="Target user (admin only)"),
) -> DrKpiBodyLeasingResponse:
    """UPSERT — jeśli wpis dla (user, week) istnieje, nadpisuje counters.

    User może zapisywać tylko własne wpisy (default user_id = current_user.id).
    Admin może przekazać `?user_id=X` żeby zapisać wpis za innego usera.
    """
    target_user_id = user_id if user_id is not None else current_user.id
    _check_admin_or_self(current_user, target_user_id)

    stmt = (
        pg_insert(DrKpiBodyLeasing)
        .values(user_id=target_user_id, **payload.model_dump())
        .on_conflict_do_update(
            index_elements=["user_id", "report_date"],
            set_={
                "week_number": payload.week_number,
                "verifications": payload.verifications,
                "recommendations": payload.recommendations,
                "interviews": payload.interviews,
                "placements": payload.placements,
                "requests": payload.requests,
                "days_worked": payload.days_worked,
                "is_draft": payload.is_draft,
                "linkedin_cv_added": payload.linkedin_cv_added,
                "linkedin_messages_sent": payload.linkedin_messages_sent,
                "linkedin_responses_received": payload.linkedin_responses_received,
            },
        )
        .returning(DrKpiBodyLeasing)
    )
    result = await db.execute(stmt)
    await db.commit()
    row = result.scalar_one()

    # Lookup user name/email
    target_user = (
        await db.execute(select(User).where(User.id == target_user_id))
    ).scalar_one()

    return DrKpiBodyLeasingResponse.model_validate(
        {**row.__dict__, "user_name": target_user.name, "user_email": target_user.email}
    )


@router.delete(
    "/{entry_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Usuwa wpis KPI Body Leasing",
)
async def delete_entry(
    entry_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Usuwa wpis — autor wpisu lub admin (DL/HoR też mogą)."""
    row = (
        await db.execute(
            select(DrKpiBodyLeasing).where(DrKpiBodyLeasing.id == entry_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie znaleziony")

    _check_admin_or_self(current_user, row.user_id)

    await db.delete(row)
    await db.commit()
