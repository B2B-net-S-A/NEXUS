"""Własny pulpit startowy — odczyt i zapis układu kafelków (0337).

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
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user_dashboard import UserDashboard
from app.services.dashboard_tiles import (
    MAX_TILES,
    DashboardLayout,
    DashboardTile,
    ROLE_LAYOUT_OFF_KEY,
    PanelKey,
    hidden_panels,
    load_layout,
    may_hide_panel,
    uses_role_layout,
)

router = APIRouter()


class UserDashboardResponse(BaseModel):
    tiles: list[DashboardTile]
    version: int
    dropped_tiles: list[dict[str, Any]] = Field(default_factory=list)
    # Listy nad kafelkami usunięte z pulpitu („Twoje CV w drodze”).
    hidden_panels: list[str] = Field(default_factory=list)
    # Brak zapisanych kafelków = front pokazuje układ roli. Fałsz także wtedy,
    # gdy osoba zapisała pusty pulpit („Usuń” ostatniego kafelka).
    uses_role_layout: bool = False


class PanelVisibilityUpdate(BaseModel):
    hidden: bool


class UserDashboardUpdate(BaseModel):
    # Runda 10 (R10-N1-5): limit i unikalność id sprawdzane w modelu żądania
    # (422 z FastAPI). Do tej rundy łapał je dopiero `DashboardLayout(...)`
    # w ciele handlera, a `ValidationError` stamtąd kończył się 500.
    tiles: list[DashboardTile] = Field(default_factory=list, max_length=MAX_TILES)
    expected_version: int = Field(ge=0)

    @model_validator(mode="after")
    def _unique_tile_ids(self) -> "UserDashboardUpdate":
        ids = [tile.id for tile in self.tiles]
        if len(ids) != len(set(ids)):
            raise ValueError("Dwa kafelki mają ten sam identyfikator.")
        return self


@router.get("", response_model=UserDashboardResponse)
async def get_my_dashboard(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> UserDashboardResponse:
    """Układ pulpitu zalogowanej osoby; brak zapisu = układ roli."""
    row = await db.get(UserDashboard, current_user.id)
    if row is None:
        return UserDashboardResponse(tiles=[], version=0, uses_role_layout=True)
    layout, dropped = load_layout(row.layout)
    return UserDashboardResponse(
        tiles=layout.tiles,
        version=row.version,
        dropped_tiles=dropped,
        hidden_panels=hidden_panels(row.layout),
        uses_role_layout=uses_role_layout(row.layout, layout.tiles),
    )


@router.put("", response_model=UserDashboardResponse)
async def save_my_dashboard(
    payload: UserDashboardUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserDashboardResponse:
    """Zapisuje cały układ naraz (tryb edycji pracuje na szkicu)."""
    layout = DashboardLayout(tiles=payload.tiles)
    # Audyt 22.09 r2 (DATA-05): pierwszy zapis z dwóch kart naraz. Bez
    # wiersza `FOR UPDATE` nie ma czego zablokować, obie karty wstawiały
    # `UserDashboard` i druga kończyła się IntegrityError → 500. Pusty wiersz
    # (wersja 0 = to samo co „brak zapisu”) zakładamy PRZED blokadą; druga
    # karta czeka na blokadzie i dostaje czytelne 409.
    await db.execute(
        pg_insert(UserDashboard)
        .values(user_id=current_user.id, layout={}, version=0)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
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
    # Zapis kafelków nie rusza list usuniętych z pulpitu — to osobna decyzja.
    hidden = hidden_panels(row.layout)
    stored: dict[str, Any] = {**layout.to_storage(), "hidden_panels": hidden}
    # Pusty zapis to decyzja „chcę pusty pulpit” — bez znacznika wróciłby
    # układ roli przy następnym wejściu.
    if not layout.tiles:
        stored[ROLE_LAYOUT_OFF_KEY] = True
    row.layout = stored
    row.version = current_version + 1
    await db.commit()
    return UserDashboardResponse(
        tiles=layout.tiles,
        version=current_version + 1,
        hidden_panels=hidden,
        uses_role_layout=False,
    )


@router.put("/panels/{panel}", response_model=UserDashboardResponse)
async def set_panel_visibility(
    panel: PanelKey,
    payload: PanelVisibilityUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> UserDashboardResponse:
    """„Usuń z pulpitu” / „Przywróć” dla listy stojącej nad kafelkami.

    Wersja układu zostaje bez zmian: chroni kafelki, a ta decyzja ich nie
    dotyczy — otwarta druga karta nie dostaje 409 przy zapisie układu.
    """
    if payload.hidden and not may_hide_panel(current_user, panel):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tę listę może usunąć z pulpitu tylko Head of Recruitment.",
        )
    await db.execute(
        pg_insert(UserDashboard)
        .values(user_id=current_user.id, layout={}, version=0)
        .on_conflict_do_nothing(index_elements=["user_id"])
    )
    row = (
        await db.execute(
            select(UserDashboard)
            .where(UserDashboard.user_id == current_user.id)
            .with_for_update()
        )
    ).scalar_one()
    hidden = [key for key in hidden_panels(row.layout) if key != panel]
    if payload.hidden:
        hidden.append(panel)
    stored = {**(row.layout or {}), "hidden_panels": hidden}
    row.layout = stored
    version = row.version
    await db.commit()
    layout, dropped = load_layout(stored)
    return UserDashboardResponse(
        tiles=layout.tiles,
        version=version,
        dropped_tiles=dropped,
        hidden_panels=hidden,
        uses_role_layout=uses_role_layout(stored, layout.tiles),
    )
