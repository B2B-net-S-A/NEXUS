"""„Ludzie → Mój zespół” (etap 2, D6, 17.10.2026) — prefiks ``/api/hr/team``.

* ``GET ""`` — bezpośredni podwładni przełożonego: dziś, urlop i nieobecności,
  bieżący miesiąc, premie w drodze (bez stawek), rzeczy do decyzji.
  ``?manager=<id>`` — zespół innego przełożonego (tylko Kadry i admin).
* ``GET /managers`` — przełożeni z liczbą podwładnych (wybór zespołu, Kadry i admin).

Bramka ``require_hr_team_reader``: moduł „Ludzie” otwarty i osoba ma
podwładnych albo jest Kadrami/adminem. Odpowiedź składa ``services/hr/team.py``.
"""

from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import MODULE_DISABLED_DETAIL
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User
from app.services.hr import modules as hr_modules
from app.services.hr import people
from app.services.hr import team as service

router = APIRouter()

TEAM_DETAIL = "„Mój zespół” widzą przełożeni i Kadry."
OTHER_TEAM_DETAIL = "Zespół innego koordynatora widzą tylko Kadry."


def require_hr_team_reader():
    """Przełożony (ma podwładnych z kartoteką), Kadry albo admin."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        loaded = await hr_modules.load_modules(db)
        if not hr_modules.module_open_for(current_user, loaded, "people"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, MODULE_DISABLED_DETAIL)
        if service.can_view_any_team(current_user):
            return current_user
        if await people.direct_report_ids(db, current_user.id):
            return current_user
        raise HTTPException(status.HTTP_403_FORBIDDEN, TEAM_DETAIL)

    return _check


TeamReader = Annotated[User, Depends(require_hr_team_reader())]


@router.get("")
async def my_team(
    current_user: TeamReader,
    db: AsyncSession = Depends(get_db),
    manager: Optional[int] = Query(default=None, ge=1),
) -> dict:
    target = current_user
    if manager is not None and manager != current_user.id:
        if not service.can_view_any_team(current_user):
            raise HTTPException(status.HTTP_403_FORBIDDEN, OTHER_TEAM_DETAIL)
        found = await db.get(User, manager)
        if found is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiej osoby.")
        target = found
    return await service.team_view(
        db, viewer=current_user, manager=target, today=business_today()
    )


@router.get("/managers")
async def team_managers(
    current_user: TeamReader, db: AsyncSession = Depends(get_db)
) -> dict:
    if not service.can_view_any_team(current_user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, OTHER_TEAM_DETAIL)
    return {"items": await service.managers(db)}
