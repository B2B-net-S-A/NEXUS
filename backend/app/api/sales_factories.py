"""Sprzedaż → lejek Fabryki IT mierzony kontaktem (prefiks ``/api/sales/it-factories``).

Trzy odczyty dla listy kont w zakładce Szanse (decyzje Artura 10.11.2026):
liczniki map per konto, kolejka osób do pierwszego kontaktu i liczniki
„Znamy teraz” / „Kiedyś” dla wszystkich firm lejka jednym skanem. Logika:
``services/sales/factories.py`` i ``services/sales/known_counts.py``.

Liczniki „Kogo znamy” są osobną trasą, bo skan kandydatów trwa sekundy i ma
własny limit: lista kont nie może na niego czekać ani przez niego padać.
"""

# NIE dodawaj tu `from __future__ import annotations`: moduł ma `@limiter.limit`
# (CLAUDE.md, ciało żądania ląduje wtedy jako parametr query).

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_companies import _is_statement_timeout
from app.api.sales_gates import SalesViewUser
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.sales import SalesCompany, SalesOpportunity, SalesPipeline
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.permission_denial import ensure_permission
from app.services.sales import client_gate, factories, known_counts
from app.services.sales.decision_map import IT_FACTORIES_PIPELINE_KEY

router = APIRouter()


# Modele mają przedrostek „Factory”: nazwa bez niego (np. ``ClientOut``) zderza się
# z modelem API v1, a FastAPI zmienia wtedy nazwy obu w OpenAPI i psuje kontrakt v1.
class FactoryRef(BaseModel):
    id: int
    name: str


class FactoryOpportunityRef(BaseModel):
    id: int
    title: str


class FactoryClientOut(BaseModel):
    """Firma jest klientem NEXUSA: temat prowadzi Delivery Lead."""

    name: str
    delivery_lead: Optional[str]


class FactoryAccountOut(BaseModel):
    opportunity_id: int
    company_id: int
    map_total: int
    map_contacted: int
    #: Poziom 1 i 2 (zarząd, dyrektorzy).
    top_total: int
    top_contacted: int
    #: Poziom 1 i 2 bez kontaktu i bez sprzeciwu: tyle osób jest w kolejce.
    waiting: int
    #: Etap mówi o kontakcie, a na mapie nikt go nie ma. Podpowiedź, nie blokada.
    stage_mismatch: bool
    client: Optional[FactoryClientOut]


class FactoryAccountsOut(BaseModel):
    items: list[FactoryAccountOut]


class FactoryQueuePersonOut(BaseModel):
    opportunity: FactoryOpportunityRef
    company: FactoryRef
    client: Optional[FactoryClientOut]
    #: Wpis mapy w kształcie z karty szansy (``atlas_motion.it_factory.decision_map``).
    person: dict[str, Any]


class FactoryQueueOut(BaseModel):
    owner: FactoryRef
    people: list[FactoryQueuePersonOut]
    #: Poziom 3 i 4 oraz osoby bez poziomu: ekran pokazuje je zwinięte.
    lower_levels: list[FactoryQueuePersonOut]


class FactoryKnownCountsOut(BaseModel):
    company_id: int
    current: int
    past: int
    via_us: int
    unknown: int


class FactoryKnownPeopleOut(BaseModel):
    items: list[FactoryKnownCountsOut]
    #: Skan trafił w sufit wierszy: liczby są dolną granicą.
    truncated: bool


def _client_out(match: Optional[client_gate.ClientMatch]) -> Optional[FactoryClientOut]:
    if match is None:
        return None
    return FactoryClientOut(name=match.client_name, delivery_lead=match.delivery_lead)


def _person_out(row: factories.QueuePerson) -> FactoryQueuePersonOut:
    return FactoryQueuePersonOut(
        opportunity=FactoryOpportunityRef(
            id=row.opportunity_id, title=row.opportunity_title
        ),
        company=FactoryRef(id=row.company_id, name=row.company_name),
        client=_client_out(row.client),
        person=row.person,
    )


@router.get("/accounts", response_model=FactoryAccountsOut)
async def list_accounts(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    archived: bool = False,
) -> FactoryAccountsOut:
    """Liczniki map kont lejka; wiersze listy daje ``GET /api/sales/opportunities``."""

    accounts = await factories.load_accounts(db, archived=archived)
    return FactoryAccountsOut(
        items=[
            FactoryAccountOut(
                opportunity_id=account.opportunity_id,
                company_id=account.company_id,
                map_total=account.counts.total,
                map_contacted=account.counts.contacted,
                top_total=account.counts.top_total,
                top_contacted=account.counts.top_contacted,
                waiting=account.counts.waiting,
                stage_mismatch=account.stage_mismatch,
                client=_client_out(account.client),
            )
            for account in accounts
        ]
    )


@router.get("/queue", response_model=FactoryQueueOut)
async def people_queue(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    owner_id: Optional[int] = None,
) -> FactoryQueueOut:
    """Kolejka do pierwszego kontaktu z map zalogowanej osoby.

    Kolejkę innego opiekuna (``owner_id``, ten sam filtr co w Szansach) otwiera
    konto z „Sprzedaż: edycja”, czyli także admin. Konto z samym podglądem widzi
    tylko własną: decyzja Artura z 10.11.2026, bo to nie ma być podgląd cudzej pracy.
    """

    owner = current_user
    if owner_id is not None and owner_id != current_user.id:
        ensure_permission(current_user, ProductAction.sales_edit)
        owner = await db.get(User, owner_id)
        if owner is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail="Nie ma takiego opiekuna."
            )
    queue = await factories.load_queue(db, owner_user_id=owner.id)
    return FactoryQueueOut(
        owner=FactoryRef(id=owner.id, name=owner.name),
        people=[_person_out(row) for row in queue.people],
        lower_levels=[_person_out(row) for row in queue.lower_levels],
    )


@router.get("/known-people", response_model=FactoryKnownPeopleOut)
# Skan kandydatów po JSONB, jak panel „Kogo znamy” (30/min): bramka uprawnienia
# nie ogranicza przepustowości.
@limiter.limit("30/minute")
async def known_people(
    request: Request,  # wymagane przez slowapi
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    archived: bool = False,
) -> FactoryKnownPeopleOut:
    """„Znamy teraz” i „Kiedyś” dla firm lejka: same liczby, jeden skan na listę."""

    companies = list(
        (
            await db.execute(
                select(SalesCompany)
                .where(
                    SalesCompany.id.in_(
                        select(SalesOpportunity.company_id)
                        .join(
                            SalesPipeline,
                            SalesPipeline.id == SalesOpportunity.pipeline_id,
                        )
                        .where(
                            SalesPipeline.key == IT_FACTORIES_PIPELINE_KEY,
                            SalesOpportunity.archived_at.is_not(None)
                            if archived
                            else SalesOpportunity.archived_at.is_(None),
                        )
                    )
                )
                .order_by(SalesCompany.id)
            )
        ).scalars()
    )
    try:
        known = await known_counts.count_known_people(db, companies)
    except DBAPIError as exc:
        if not _is_statement_timeout(exc):
            raise
        await db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nie udało się teraz policzyć osób z bazy. Spróbuj za chwilę.",
        ) from exc
    return FactoryKnownPeopleOut(
        items=[
            FactoryKnownCountsOut(
                company_id=company_id,
                current=counts.current,
                past=counts.past,
                via_us=counts.via_us,
                unknown=counts.unknown,
            )
            for company_id, counts in known.counts.items()
        ],
        truncated=known.truncated,
    )
