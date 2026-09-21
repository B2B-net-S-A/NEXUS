"""Własny pulpit startowy — odczyt i zapis układu kafelków (0336).

Jeden pulpit na osobę, widoczny tylko dla właściciela. Trasa niesie wyłącznie
układ (typy kafelków, pozycje, ustawienia) — dane kafelków pobierają ich
własne endpointy za swoimi bramkami sekcji, więc ta trasa świadomie stoi za
samym zalogowaniem (wpisy w `_SECTIONLESS_ALLOWLIST` i `_BARE_BASELINE`).

Zapis wymaga `expected_version`: dwie karty przeglądarki z otwartym trybem
edycji nie nadpisują sobie układu po cichu (409, front przeładowuje).
Tryb „podgląd jako" odrzuca zapis w `deps.py` (każde żądanie nie-odczytowe).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user_dashboard import UserDashboard
from app.services.dashboard_tiles import DashboardLayout, DashboardTile, load_layout

router = APIRouter()


class UserDashboardResponse(BaseModel):
    tiles: list[DashboardTile]
    version: int
    dropped_tiles: list[dict[str, Any]] = Field(default_factory=list)


class UserDashboardUpdate(BaseModel):
    tiles: list[DashboardTile] = Field(default_factory=list)
    expected_version: int = Field(ge=0)


@router.get("", response_model=UserDashboardResponse)
async def get_my_dashboard(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserDashboardResponse:
    """Układ pulpitu zalogowanej osoby; brak zapisu = pusty pulpit."""
    row = await db.get(UserDashboard, current_user.id)
    if row is None:
        return UserDashboardResponse(tiles=[], version=0)
    layout, dropped = load_layout(row.layout)
    return UserDashboardResponse(
        tiles=layout.tiles, version=row.version, dropped_tiles=dropped
    )


@router.put("", response_model=UserDashboardResponse)
async def save_my_dashboard(
    payload: UserDashboardUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserDashboardResponse:
    """Zapisuje cały układ naraz (tryb edycji pracuje na szkicu)."""
    layout = DashboardLayout(tiles=payload.tiles)
    row = (
        await db.execute(
            select(UserDashboard)
            .where(UserDashboard.user_id == current_user.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    current_version = row.version if row is not None else 0
    if payload.expected_version != current_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "DASHBOARD_VERSION_CONFLICT",
                "message": (
                    "Pulpit został zmieniony w innej karcie. Wczytaj go "
                    "ponownie i wprowadź zmiany jeszcze raz."
                ),
                "current_version": current_version,
            },
        )
    if row is None:
        row = UserDashboard(user_id=current_user.id, layout={}, version=0)
        db.add(row)
    row.layout = layout.to_storage()
    row.version = current_version + 1
    await db.commit()
    return UserDashboardResponse(tiles=layout.tiles, version=current_version + 1)
