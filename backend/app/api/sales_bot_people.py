"""Sprzedaż: mapy decydentów od bota (rodzaj ``people``, decyzja Artura 12.11.2026).

Prefiks ``/api/sales/bot-people`` (wpięty w ``app/main.py``). Bot dostaje nazwę
i domenę firmy, odsyła osoby ze źródłami publicznymi; wynik czeka na przegląd
w Leady → „Lista z researchu”. Przegląd i zapis to maszyna importu listy
(``research_import``): te same stany wiersza, ta sama walidacja i punkt zapisu
na wiersz. Odczyt listy wyników: „Sprzedaż: podgląd”; przegląd, zapis i start
biegu: „Sprzedaż: edycja”. Wyłączona flaga ``SALES_BOT_TASKS_ENABLED``: lista
mówi ``enabled: false``, reszta odpowiada 409.
→ docs/claude/sprzedaz/mapy-decydentow-od-bota.md
"""

# NIE dodawaj tu `from __future__ import annotations`: moduł ma `@limiter.limit`
# (CLAUDE.md, ciało żądania ląduje wtedy jako parametr query).

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.api.sales_research_import import (
    ResearchAcceptOut,
    ResearchOutcomeOut,
    ResearchPreviewOut,
    _client_out,
    _owner,
    preview_out,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.sales import SalesBotResult, SalesCompany
from app.services.sales import bot_tasks, client_gate, company_aliases, signals
from app.services.sales import research_import, signal_targets
from app.services.sales.bot_tasks import people
from app.services.sales.factories import COMPANY_DO_NOT_CONTACT

router = APIRouter()

#: Jeden uruchomiony bieg na firmę na dobę (bez nieudanych startów).
START_EVERY = timedelta(hours=24)
START_LOCK_KEY = "sales-bot-people-start"
OPEN_STATUSES = ("new", "partial")

DISABLED_DETAIL = "Zadania bota są wyłączone."
NOT_CONFIGURED_DETAIL = "Bot researchu nie jest skonfigurowany."
NO_COMPANY_DETAIL = "Nie ma takiej firmy albo jest w archiwum."
RECENT_DETAIL = (
    "Bot szuka już decydentów tej firmy. Kolejny bieg można zlecić po 24 godzinach."
)
PENDING_DETAIL = "Na przegląd czeka już wynik bota dla tej firmy."
BLOCKED_DETAIL = "Firma ma oznaczenie „Nie kontaktować”."
NOT_STARTED_DETAIL = "Nie udało się zlecić biegu. Spróbuj ponownie później."
WEBHOOK_DETAIL = "Bot nie przyjął zlecenia. Spróbuj ponownie później."
NOT_FOUND_DETAIL = "Nie ma takiego wyniku."
DECIDED_DETAIL = "O tym wyniku już zdecydowano."


class BotPeopleCompanyOut(BaseModel):
    id: int
    name: str


class BotPeoplePendingOut(BaseModel):
    id: int
    company: BotPeopleCompanyOut
    status: str
    people: int
    #: Osoby, o których nikt jeszcze nie zdecydował.
    open: int
    created_at: datetime


class BotPeopleListOut(BaseModel):
    enabled: bool
    items: list[BotPeoplePendingOut]
    #: Firmy z biegiem z ostatnich 24 godzin: przycisk czeka.
    running_company_ids: list[int]


class BotPeoplePreviewOut(BaseModel):
    result_id: int
    company: BotPeopleCompanyOut
    status: str
    preview: ResearchPreviewOut
    #: Data publikacji źródła per wiersz (``line`` → RRRR-MM-DD).
    published: dict[int, Optional[str]]
    #: Wiersze, o których już zdecydowano (wynik zapisu).
    decided: dict[int, str]


class BotPeoplePickIn(BaseModel):
    """Wiersz wyniku do zapisu. Treść osoby serwer bierze z wyniku, nie z żądania."""

    model_config = ConfigDict(extra="forbid")

    line: int = Field(ge=1, le=people.MAX_PEOPLE)
    decision_level: Optional[int] = Field(default=None, ge=1, le=4)
    company_id: Optional[int] = Field(default=None, ge=1)


class BotPeopleAcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    owner_user_id: Optional[int] = Field(default=None, ge=1)
    people: list[BotPeoplePickIn] = Field(min_length=1, max_length=people.MAX_PEOPLE)


class BotPeopleAcceptOut(ResearchAcceptOut):
    status: str


class BotPeopleStartOut(BaseModel):
    started: bool
    run_id: int


def _require_enabled() -> None:
    if not bot_tasks.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail=DISABLED_DETAIL)


@router.get("/pending", response_model=BotPeopleListOut)
async def pending_results(
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> BotPeopleListOut:
    """Wyniki do przeglądu (najnowsze najpierw) i firmy z biegiem z ostatniej doby."""

    if not bot_tasks.enabled():
        return BotPeopleListOut(enabled=False, items=[], running_company_ids=[])
    rows = (
        await db.execute(
            select(SalesBotResult, SalesCompany)
            .join(SalesCompany, SalesCompany.id == SalesBotResult.company_id)
            .where(
                SalesBotResult.kind == people.KIND,
                SalesBotResult.status.in_(OPEN_STATUSES),
                SalesCompany.archived_at.is_(None),
            )
            .order_by(SalesBotResult.created_at.desc(), SalesBotResult.id.desc())
            .limit(200)
        )
    ).all()
    running = await signal_targets.people_recently_sent(
        db, now=datetime.now(timezone.utc), within=START_EVERY
    )
    return BotPeopleListOut(
        enabled=True,
        items=[
            BotPeoplePendingOut(
                id=row.id,
                company=BotPeopleCompanyOut(id=company.id, name=company.name),
                status=row.status,
                people=len((row.payload or {}).get("people") or []),
                open=people.open_count(row),
                created_at=row.created_at,
            )
            for row, company in rows
        ],
        running_company_ids=sorted(running),
    )


async def _open_result(
    db: AsyncSession, result_id: int, *, lock: bool = False
) -> SalesBotResult:
    row = await db.get(SalesBotResult, result_id, with_for_update=lock or None)
    if row is None or row.kind != people.KIND:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if row.status not in OPEN_STATUSES:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=DECIDED_DETAIL)
    return row


@router.get("/{result_id}/preview", response_model=BotPeoplePreviewOut)
# Przegląd liczy „Znamy teraz” skanem kandydatów, jak przegląd pliku (20/min).
@limiter.limit("20/minute")
async def preview_result(
    request: Request,  # wymagane przez slowapi
    result_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> BotPeoplePreviewOut:
    """Osoby z wyniku jako wiersze przeglądu listy z researchu; niczego nie zapisuje."""

    _require_enabled()
    row = await _open_result(db, result_id)
    try:
        plan, published = await people.review_plan(db, row)
    except bot_tasks.AcceptRefused as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    company = await db.get(SalesCompany, row.company_id)
    # Odczyt przed skanem: po przekroczonym limicie skanu transakcja jest cofana.
    company_out = BotPeopleCompanyOut(id=company.id, name=company.name)
    status_now, decided = row.status, people.decided_lines(row)
    return BotPeoplePreviewOut(
        result_id=result_id,
        company=company_out,
        status=status_now,
        preview=await preview_out(db, plan, [], origin=people.ORIGIN),
        published=published,
        decided=decided,
    )


@router.post("/{result_id}/people", response_model=BotPeopleAcceptOut)
# Akceptacja wiersz po wierszu to jedno żądanie na klik, jak w imporcie listy.
@limiter.limit("120/minute")
async def accept_people(
    request: Request,  # wymagane przez slowapi
    result_id: int,
    payload: BotPeopleAcceptIn,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> BotPeopleAcceptOut:
    """Wybrane osoby z wyniku na mapę konta firmy; wynik ``partial`` albo ``accepted``."""

    _require_enabled()
    owner_id = await _owner(db, current_user, payload.owner_user_id)
    row = await _open_result(db, result_id, lock=True)
    try:
        outcomes = await people.apply(
            db,
            row,
            [
                people.Pick(
                    line=pick.line,
                    decision_level=pick.decision_level,
                    company_id=pick.company_id,
                )
                for pick in payload.people
            ],
            user_id=current_user.id,
            owner_user_id=owner_id,
            now=datetime.now(timezone.utc),
        )
    except bot_tasks.AcceptRefused as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from None
    result_status = row.status
    await db.commit()
    added = [o for o in outcomes if o.result == research_import.ADDED]
    return BotPeopleAcceptOut(
        status=result_status,
        outcomes=[
            ResearchOutcomeOut(
                line=outcome.line,
                result=outcome.result,
                detail=outcome.detail,
                company_id=outcome.company_id,
                opportunity_id=outcome.opportunity_id,
                created_company=outcome.created_company,
                created_account=outcome.created_account,
                client=_client_out(outcome.client),
            )
            for outcome in outcomes
        ],
        added=len(added),
        created_companies=sum(o.created_company for o in added),
        created_accounts=sum(o.created_account for o in added),
    )


@router.post("/companies/{company_id}/start", response_model=BotPeopleStartOut)
# Każdy start to bieg bota (koszt po jego stronie): limit ponad regułę 24 godzin.
@limiter.limit("10/minute")
async def start_people_run(
    request: Request,  # wymagane przez slowapi
    company_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> BotPeopleStartOut:
    """„Znajdź decydentów (bot)”: jeden bieg na firmę na 24 godziny."""

    _require_enabled()
    if not signals.configured():
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_CONFIGURED_DETAIL)
    company = await db.get(SalesCompany, company_id)
    if company is None or company.archived_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NO_COMPANY_DETAIL)
    if company_aliases.is_own_company(company.normalized_name or ""):
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=client_gate.OWN_COMPANY_REFUSAL
        )
    if company.status == COMPANY_DO_NOT_CONTACT:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=BLOCKED_DETAIL)
    clients = await client_gate.match_companies(
        db,
        [
            client_gate.CompanyIdentity(
                company_id=company.id,
                client_id=company.client_id,
                normalized_name=company.normalized_name,
            )
        ],
    )
    if company.id in clients:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=clients[company.id].refusal
        )
    # Dwa kliknięcia naraz: blokada do commitu w ``start_run``, sprawdzenie i zapis biegu
    # widzą się nawzajem.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:key))"), {"key": START_LOCK_KEY}
    )
    now = datetime.now(timezone.utc)
    recent = await signal_targets.people_recently_sent(db, now=now, within=START_EVERY)
    if company.id in recent:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=RECENT_DETAIL)
    pending = await db.scalar(
        select(SalesBotResult.id).where(
            SalesBotResult.kind == people.KIND,
            SalesBotResult.company_id == company.id,
            SalesBotResult.status.in_(OPEN_STATUSES),
        )
    )
    if pending is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=PENDING_DETAIL)
    run = await signals.start_run(
        db, people.KIND, [company.id], now=now, requested_by_user_id=current_user.id
    )
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_STARTED_DETAIL)
    if run.status == "failed":
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, detail=WEBHOOK_DETAIL)
    return BotPeopleStartOut(started=True, run_id=run.id)
