"""Sprawy konsultanta w opiece: ``GET /api/care/contracts/{id}/cases``.

Karta konsultanta (opieka, decyzja 7 z 22.10.2026) pokazuje sprawy
administracja@ przypięte do kontraktu. Listę widzi każdy, kto widzi kartę —
czytelnik opieki (``CareReader``: sekcja i podgląd Delivery, bez roli
„Automatyzacje”, moduł opieki włączony) z kontraktem w swoim zakresie
(Delivery Lead — swoi klienci). Treść spraw dalej tylko ``may_read``
(obsługa „Spraw” i osoba przypisana): wiersz niesie tytuł, obszar, status,
termin i osobę, a ``content_hidden`` mówi, czy sprawę wolno otworzyć;
negocjacje — nigdy z karty. Odczyt niczego nie zapisuje.

``GET /case-assignees`` — lista osób do spraw dla zapisującego opiekę (wybór
„Prowadzi” w oknie rozmowy). Obsługa Spraw (``is_handler``) dostaje pełną
listę, reszta tylko siebie — sprawę z rozmowy bez uprawnienia zostawia się
bez osoby albo bierze na siebie (``conversation_save.case_request_problem``).

Router dołącza się pod prefiksem ``/api/care`` z ``_HR_PROGRAM``.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import CareReader, CareWriter
from app.core.database import get_db
from app.models.user import User
from app.services.admin_cases import queries
from app.services.admin_cases.service import is_handler
from app.services.care import access as care_access

router = APIRouter()


@router.get("/contracts/{contract_id}/cases")
async def contract_cases(
    contract_id: int,
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await care_access.load_contract(db, contract_id, current_user)
    return await queries.cases_for_contract(db, contract_id, current_user)


@router.get("/case-assignees")
async def case_assignees(
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if is_handler(current_user):
        return {"items": await queries.assignee_options(db)}
    return {
        "items": [{"id": current_user.id, "name": current_user.name, "handler": False}]
    }
