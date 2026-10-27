"""Sprzedaż → „Kogo znamy w firmie”: osoby z bazy przy firmie i uzupełnianie dat.

Prefiks ``/api/sales/companies`` (drugi router obok ``sales_companies``).
Osobny moduł, bo trasy mają ``@limiter.limit``, a moduł z limiterem nie może
mieć ``from __future__ import annotations`` (ciało żądania ląduje wtedy jako
parametr query — CLAUDE.md). Pełny profil kandydata to decyzja D4
(26.10.2026), daty per firma — D3.
"""

# NIE dodawaj tu `from __future__ import annotations` (patrz wyżej).

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_companies import (
    CompanyPeopleRequest,
    CompanyPeopleResponse,
    MatchedPerson,
    lookup_company_people,
)
from app.api.sales_companies import NOT_FOUND_DETAIL, CompanyRef
from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.client import Client
from app.models.sales import SalesCompany
from app.services.sales import company_dates

router = APIRouter()


# ── „Kogo znamy w firmie” ────────────────────────────────────────────────


class GroupCompanyPeople(BaseModel):
    company: CompanyRef
    relation: Literal["parent", "child"]
    counts: dict[str, int]


class CompanyPeopleOut(BaseModel):
    """Osoby z bazy NEXUSA przy firmie — z pełnym profilem (decyzja D4, 26.10.2026)."""

    matched_client: Optional[CompanyRef]
    counts: dict[str, int]
    truncated: bool
    people: list[MatchedPerson]
    group: list[GroupCompanyPeople]
    #: Stan uzupełniania dat osób z tej firmy (D3): ``status``, ``total``, ``updated``.
    dates_backfill: Optional[dict[str, Any]]


def _lookup_names(company: SalesCompany, client_name: Optional[str]) -> list[str]:
    names: list[str] = []
    for name in (company.name, company.legal_name, client_name):
        if name and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names[:10]


async def _people_for(
    db: AsyncSession, company: SalesCompany, *, limit: int
) -> CompanyPeopleResponse:
    client_name = None
    if company.client_id is not None:
        client = await db.get(Client, company.client_id)
        client_name = (client.display_name or client.name) if client else None
    request = CompanyPeopleRequest(
        names=_lookup_names(company, client_name), nip=company.nip, limit=limit
    )
    return await lookup_company_people(db, request)


@router.get("/{company_id}/people", response_model=CompanyPeopleOut)
# Każde żądanie to do 22 skanów kandydatów (firma, matka, do 20 spółek
# zależnych) — bramka uprawnienia nie ogranicza przepustowości, jak przy
# trasie OAuth `/companies/people` (60/min).
@limiter.limit("30/minute")
async def company_people(
    request: Request,  # wymagane przez slowapi
    company_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=200, ge=1, le=200),
) -> CompanyPeopleOut:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    result = await _people_for(db, company, limit=limit)

    related: list[tuple[SalesCompany, Literal["parent", "child"]]] = []
    if company.parent_company_id is not None:
        parent = await db.get(SalesCompany, company.parent_company_id)
        if parent is not None:
            related.append((parent, "parent"))
    children = (
        await db.execute(
            select(SalesCompany)
            .where(
                SalesCompany.parent_company_id == company.id,
                SalesCompany.archived_at.is_(None),
            )
            .order_by(SalesCompany.name)
            .limit(20)
        )
    ).scalars()
    related.extend((child, "child") for child in children)
    group = []
    for other, relation in related:
        # Liczby wystarczą — szczegóły to karta tamtej firmy.
        counted = await _people_for(db, other, limit=1)
        group.append(
            GroupCompanyPeople(
                company=CompanyRef(id=other.id, name=other.name),
                relation=relation,
                counts=counted.counts,
            )
        )
    return CompanyPeopleOut(
        matched_client=(
            CompanyRef(id=result.matched_client.id, name=result.matched_client.name)
            if result.matched_client
            else None
        ),
        counts=result.counts,
        truncated=result.truncated,
        people=result.people,
        group=group,
        dates_backfill=company_dates.visible_state(
            company.dates_backfill, now=datetime.now(timezone.utc)
        ),
    )


@router.post("/{company_id}/people/dates", response_model=dict[str, Any])
# Bieg płaci za model AI — przycisk nie może iść w pętli.
@limiter.limit("20/hour")
async def fill_people_dates(
    request: Request,  # wymagane przez slowapi
    company_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Uzupełnij daty” w panelu — bieg w tle dla osób „bez dat” z tej firmy."""

    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    state = company.dates_backfill or {}
    if company_dates.is_running(state, now=datetime.now(timezone.utc)):
        return {"scheduled": False, "state": state}
    scheduled = company_dates.schedule_company_dates(company_id)
    if not scheduled:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Uzupełnianie dat jest teraz wyłączone albo już trwa.",
        )
    return {"scheduled": True, "state": state}
