"""Ustawienia → Rekrutacja → Cele KPI (plan PR3, 23.09.2026).

Admin i Head of Recruitment (`HeadOfRecruitmentPlus`) edytują odstępstwa ról
od katalogu KPI i osobiste cele — bez deployu. Reguły zapisu (kanoniczne id,
kasowanie aliasów, wartość z katalogu = usunięcie odstępstwa roli) żyją
w `app.services.kpi_target_editor`. Bramka sekcji Insights na routerze:
HoR ma tam zapis, admin też; konto z odebraną sekcją nie wywoła tras.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.services import kpi_target_editor as editor

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)


class RoleDefaultIn(BaseModel):
    role: str
    kpi_id: str
    # `None` = przywróć wartość z katalogu (usuń odstępstwo).
    target_value: Optional[int] = Field(default=None, ge=0, le=100_000)


class UserTargetIn(BaseModel):
    user_id: int
    kpi_id: str
    # `None` = usuń osobisty cel (osoba wraca do celu swoich ról).
    target_value: Optional[int] = Field(default=None, ge=0, le=100_000)


@router.get("")
async def get_kpi_targets(
    _: HeadOfRecruitmentPlus, db: AsyncSession = Depends(get_db)
) -> dict:
    """Macierz rola × KPI + efektywne cele każdej osoby z rolą rekrutacyjną."""
    return await editor.build_matrix(db)


@router.put("/role-default")
async def put_role_default(
    payload: RoleDefaultIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await editor.set_role_default(
            db,
            role=payload.role,
            kpi_id=payload.kpi_id,
            target_value=payload.target_value,
            actor=current_user,
        )
    except editor.KpiTargetEditError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    await db.commit()
    if result.changed:
        await editor.invalidate_target_caches()
    return await editor.build_matrix(db)


@router.put("/user-target")
async def put_user_target(
    payload: UserTargetIn,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await editor.set_user_target(
            db,
            user_id=payload.user_id,
            kpi_id=payload.kpi_id,
            target_value=payload.target_value,
            actor=current_user,
        )
    except editor.KpiTargetEditError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Nie znaleziono użytkownika."
        ) from exc
    await db.commit()
    if result.changed:
        await editor.invalidate_target_caches()
    return await editor.build_matrix(db)


@router.get("/history")
async def get_kpi_target_history(
    _: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    return {"items": await editor.history(db, limit=limit)}
