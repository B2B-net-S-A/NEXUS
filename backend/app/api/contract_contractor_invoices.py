"""Zakładka „Faktury” kontraktu: faktury konsultanta z KSeF (decyzja Artura 19.11.2026).

Źródłem są faktury kontraktorów z Rozliczeń (``client_contractor_invoices``,
roadmapa E4) ze wszystkich miesięcy jednego kontraktu. W Finanse → Rozliczenia
te same faktury widać miesiąc po miesiącu na karcie osoby, razem z kontrolami
(kwota z RCP, łańcuch korekt, biała lista). Do 19.11.2026 zakładka czytała
ręczny rejestr ``invoices`` (``/api/invoices``), który na produkcji nie miał
ani jednego wiersza, więc zawsze pokazywała „Brak faktur”.

Dostęp jak w Rozliczeniach: sekcja Finanse i uprawnienie „Moduł Finanse”
(Delivery Lead i Back office faktur kontraktorów nie widzą), wyłączony moduł
rozliczeń = 404 z tym samym komunikatem (admin widzi zawsze). Kwoty tylko
z dostępem finansowym (``has_financial_access``).
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.financial_access import has_financial_access
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.contract import Contract
from app.services.client_settlements import contractor_invoices
from app.services.client_settlements import settings as module_settings

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


@router.get("/{contract_id}/contractor-invoices")
async def contract_contractor_invoices(
    contract_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Faktury konsultanta z KSeF przypięte do kontraktu, najnowszy miesiąc pierwszy."""

    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(current_user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )
    client_id = await db.scalar(
        select(Contract.client_id).where(Contract.id == contract_id)
    )
    if client_id is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie znaleziono kontraktu.")
    invoices = await contractor_invoices.for_contract(db, contract_id)
    return {
        "contract_id": contract_id,
        "client_id": client_id,
        "invoices": contractor_invoices.contract_listing(
            invoices, amounts=has_financial_access(current_user)
        ),
    }
