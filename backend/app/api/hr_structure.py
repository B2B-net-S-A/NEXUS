"""„Ludzie → Struktura” (etap 2, D4 i D7, 17.10.2026) — prefiks ``/api/hr/structure``.

* ``GET ""`` — kartoteki z przełożonymi, liczbą podwładnych, odejściem w toku
  i rozjazdem z Microsoft 365 (drzewo układa front),
* ``POST /reassign`` — nowy przełożony dla wielu osób naraz, od razu
  (``{user_ids, manager_user_id}``; ``null`` = bez przełożonego),
* ``POST /division`` — pion firmy dla wielu osób naraz (``{user_ids, division}``),
* ``PUT /divisions`` — head Front office i Back office
  (``app_settings['hr_divisions']``).

Tylko Kadry i admin (``require_hr_people_admin``). Jak trasy Kadr w
``hr_admin.py`` nie czekają na przełącznik modułu — Kadry układają strukturę
przed włączeniem modułu.
"""

from __future__ import annotations

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.hr_gates import HrPeopleAdmin, require_hr_people_admin
from app.core.database import get_db
from app.services.hr import people
from app.services.hr import structure as service

router = APIRouter(dependencies=[Depends(require_hr_people_admin())])


Division = Literal["front_office", "back_office"]


class ReassignIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=service.MAX_REASSIGN)
    # Wymagane, ale może być `null` — jawne „bez przełożonego”, nie domyślne.
    manager_user_id: Optional[int]


class DivisionIn(BaseModel):
    user_ids: list[int] = Field(min_length=1, max_length=service.MAX_REASSIGN)
    division: Optional[Division]


class DivisionHeadsIn(BaseModel):
    front_office: Optional[int] = None
    back_office: Optional[int] = None


def _unprocessable(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


_MISSING_PROFILES = "Część wybranych osób nie ma kartoteki — odśwież stronę."


@router.get("")
async def get_structure(
    current_user: HrPeopleAdmin, db: AsyncSession = Depends(get_db)
) -> dict:
    return await service.structure(db, current_user)


@router.post("/reassign")
async def reassign(
    payload: ReassignIn,
    current_user: HrPeopleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await service.reassign(
            db,
            user_ids=payload.user_ids,
            manager_user_id=payload.manager_user_id,
            actor=current_user,
        )
    except people.HrPeopleError as exc:
        raise _unprocessable(exc) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _MISSING_PROFILES) from exc
    await db.commit()
    return result


@router.post("/division")
async def set_division(
    payload: DivisionIn,
    current_user: HrPeopleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        result = await service.set_division(
            db,
            user_ids=payload.user_ids,
            division=payload.division,
            actor=current_user,
        )
    except people.HrPeopleError as exc:
        raise _unprocessable(exc) from exc
    except LookupError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, _MISSING_PROFILES) from exc
    await db.commit()
    return result


@router.put("/divisions")
async def set_division_heads(
    payload: DivisionHeadsIn,
    current_user: HrPeopleAdmin,
    db: AsyncSession = Depends(get_db),
) -> dict:
    # `exclude_unset`: pion pominięty w żądaniu zostaje bez zmian, `null` czyści.
    try:
        heads = await service.set_division_heads(
            db, heads=payload.model_dump(exclude_unset=True), actor=current_user
        )
    except people.HrPeopleError as exc:
        raise _unprocessable(exc) from exc
    await db.commit()
    return {"heads": heads}
