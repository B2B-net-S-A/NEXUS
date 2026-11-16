"""Sprzedaż → „Kogo znamy w firmie”: osoby z bazy, inne nazwy z CV, uzupełnianie dat.

Prefiks ``/api/sales/companies`` (drugi router obok ``sales_companies``).
Osobny moduł, bo trasy mają ``@limiter.limit``, a moduł z limiterem nie może
mieć ``from __future__ import annotations`` (ciało żądania ląduje wtedy jako
parametr query — CLAUDE.md). Pełny profil kandydata to decyzja D4
(26.10.2026), daty per firma — D3. Inne nazwy z CV i dziennik odczytu: P8
(09.11.2026), reguły w ``services/sales/company_aliases.py``.
"""

# NIE dodawaj tu `from __future__ import annotations` (patrz wyżej).

import logging
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_companies import (
    CompanyPeopleRequest,
    CompanyPeopleResponse,
    MatchedPerson,
    _client_by_id,
    _client_known_names,
    _is_statement_timeout,
    _normalize_nip,
    _resolve_client,
    lookup_company_people,
)
from app.api.sales_companies import NOT_FOUND_DETAIL, CompanyRef
from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.client import Client
from app.models.sales import SalesCompany, SalesCompanyAlias
from app.services import candidate_audit
from app.services.company_names import normalize_company_name
from app.services.sales import company_aliases, company_dates

logger = logging.getLogger(__name__)

router = APIRouter()


# ── „Kogo znamy w firmie” ────────────────────────────────────────────────


class GroupCompanyPeople(BaseModel):
    company: CompanyRef
    relation: Literal["parent", "child"]
    #: ``None`` = tej spółki nie udało się policzyć (limit czasu skanu).
    counts: Optional[dict[str, int]]


class CompanyPeopleOut(BaseModel):
    """Osoby z bazy NEXUSA przy firmie — z pełnym profilem (decyzja D4, 26.10.2026)."""

    matched_client: Optional[CompanyRef]
    counts: dict[str, int]
    truncated: bool
    people: list[MatchedPerson]
    #: Stan uzupełniania dat osób z tej firmy (D3): ``status``, ``total``, ``updated``.
    dates_backfill: Optional[dict[str, Any]]
    #: Prawda tylko po udanym zapisie odczytu listy osób w dzienniku.
    read_logged: bool = False
    #: Karta naszej własnej firmy: listy osób celowo nie ma.
    own_company: bool = False


def _lookup_names(company: SalesCompany, client_name: Optional[str]) -> list[str]:
    names: list[str] = []
    for name in (company.name, company.legal_name, client_name):
        if name and name.strip() and name.strip() not in names:
            names.append(name.strip())
    return names[:10]


async def _people_for(
    db: AsyncSession, company: SalesCompany, *, limit: int
) -> CompanyPeopleResponse:
    if company_aliases.is_own_company(company.normalized_name):
        return CompanyPeopleResponse(
            query=company.name,
            canonical=company.normalized_name,
            counts={"via_us": 0, "current": 0, "past": 0, "unknown": 0},
            people=[],
        )
    client_name = None
    if company.client_id is not None:
        client = await db.get(Client, company.client_id)
        client_name = (client.display_name or client.name) if client else None
    request = CompanyPeopleRequest(
        names=_lookup_names(company, client_name), nip=company.nip, limit=limit
    )
    return await lookup_company_people(
        db,
        request,
        extra_names=await company_aliases.joined_names(db, company.id),
        priority_order=True,
        linked_client_id=company.client_id,
    )


async def _log_people_read(
    db: AsyncSession, user_id: int, company_id: int, people: list[MatchedPerson]
) -> bool:
    """Zapisz, kto dostał listę osób firmy. ``False``, gdy zapis się nie udał.

    Tylko identyfikatory, jak w całym dzienniku. Awaria dziennika nie odbiera
    handlowcowi listy, ale ekran nie może wtedy mówić, że odczyt jest zapisany.
    """
    if not people:
        return False
    ids = [person.candidate_id for person in people]
    try:
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.SALES_COMPANY_PEOPLE_READ,
            user_id=user_id,
            details={
                "sales_company_id": company_id,
                "candidate_ids": ids,
                "count": len(ids),
            },
        )
        await db.commit()
    except Exception:  # noqa: BLE001 — odczyt listy nie zależy od dziennika
        logger.exception("[sales-people] nie udało się zapisać odczytu listy osób")
        await db.rollback()
        return False
    return True


@router.get("/{company_id}/people", response_model=CompanyPeopleOut)
# Skan kandydatów po JSONB — bramka uprawnienia nie ogranicza przepustowości,
# jak przy trasie OAuth `/companies/people` (60/min).
@limiter.limit("30/minute", key_func=user_or_ip_key)
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
    out = CompanyPeopleOut(
        matched_client=(
            CompanyRef(id=result.matched_client.id, name=result.matched_client.name)
            if result.matched_client
            else None
        ),
        counts=result.counts,
        truncated=result.truncated,
        people=result.people,
        dates_backfill=company_dates.visible_state(
            company.dates_backfill, now=datetime.now(timezone.utc)
        ),
        own_company=company_aliases.is_own_company(company.normalized_name),
    )
    out.read_logged = await _log_people_read(
        db, current_user.id, company_id, result.people
    )
    return out


@router.get("/{company_id}/people/group", response_model=list[GroupCompanyPeople])
# Do 21 skanów (matka + do 20 spółek zależnych) — osobne zapytanie, żeby panel
# firmy nie czekał na grupę i nie padał przez jedną wolną spółkę.
@limiter.limit("10/minute", key_func=user_or_ip_key)
async def company_group_people(
    request: Request,  # wymagane przez slowapi
    company_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> list[GroupCompanyPeople]:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
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
        if company_aliases.is_own_company(other.normalized_name):
            continue
        try:
            # Liczby wystarczą — szczegóły to karta tamtej firmy.
            counts: Optional[dict[str, int]] = (
                await _people_for(db, other, limit=1)
            ).counts
        except HTTPException as exc:
            # Limit czasu (503) albo zbyt krótka nazwa (422) jednej spółki — reszta
            # grupy zostaje, ta pokazuje „nie policzyliśmy”.
            if exc.status_code not in (
                status.HTTP_503_SERVICE_UNAVAILABLE,
                status.HTTP_422_UNPROCESSABLE_ENTITY,
            ):
                raise
            counts = None
        group.append(
            GroupCompanyPeople(
                company=CompanyRef(id=other.id, name=other.name),
                relation=relation,
                counts=counts,
            )
        )
    return group


@router.post("/{company_id}/people/dates", response_model=dict[str, Any])
# Bieg płaci za model AI — przycisk nie może iść w pętli.
@limiter.limit("20/hour", key_func=user_or_ip_key)
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


# ── Inne nazwy z CV ──────────────────────────────────────────────────────


class AliasDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=500)
    status: Literal["joined", "rejected"]


class AliasDecisionOut(BaseModel):
    id: int
    name: str
    status: Literal["joined", "rejected"]


class AliasVariantOut(BaseModel):
    key: str
    name: str
    people: int
    current: int


class OwnCardOut(BaseModel):
    id: int
    name: str
    current: int


class CompanyAliasesOut(BaseModel):
    decisions: list[AliasDecisionOut]
    suggestions: list[AliasVariantOut]
    other_count: int = 0
    other_min: int = 0
    other_max: int = 0
    own_cards: list[OwnCardOut] = []


def _decision_out(row: SalesCompanyAlias) -> AliasDecisionOut:
    return AliasDecisionOut(id=row.id, name=row.alias, status=row.status)


async def _company_or_404(db: AsyncSession, company_id: int) -> SalesCompany:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    return company


async def _card_names(db: AsyncSession, company: SalesCompany) -> list[str]:
    client_name = None
    if company.client_id is not None:
        client = await db.get(Client, company.client_id)
        client_name = (client.display_name or client.name) if client else None
    return _lookup_names(company, client_name)


async def _suggest(db: AsyncSession, company: SalesCompany) -> CompanyAliasesOut:
    decided = await company_aliases.decisions(db, company.id)
    decisions = [_decision_out(row) for row in decided]
    if company_aliases.is_own_company(company.normalized_name):
        return CompanyAliasesOut(decisions=decisions, suggestions=[])

    names = await _card_names(db, company)
    joined = [row.alias for row in decided if row.status == company_aliases.JOINED]
    seeds = {
        canonical
        for canonical in map(normalize_company_name, (*names, *joined))
        if len(canonical) >= company_aliases.MIN_NAME_LEN
    }
    if not seeds:
        return CompanyAliasesOut(decisions=decisions, suggestions=[])

    await db.execute(
        select(
            func.set_config(
                "statement_timeout", str(company_aliases.STATEMENT_TIMEOUT_MS), True
            )
        )
    )
    # Nazwy, które panel i tak dolicza z klienta, nie są „innymi nazwami”.
    skip = {row.normalized_alias for row in decided}
    client = None
    if company.client_id is not None:
        client = await _client_by_id(db, company.client_id)
    if client is None:
        client = await _resolve_client(db, seeds, _normalize_nip(company.nip))
    if client is not None:
        skip |= {
            normalize_company_name(label)
            for label in await _client_known_names(db, client.id)
        }

    entries = await company_aliases.scan_cv_entries(
        db, company_aliases.search_patterns([*names, *joined])
    )
    collected = company_aliases.collect(entries, seeds=seeds, skip=skip)
    variants = collected.variants

    cards = await _other_cards(db, company.id, set(variants))
    bridges = [
        name
        for name in company_aliases.supported_bridges(collected.bridges)
        if name not in variants
    ]
    with_cards = await _other_cards(db, company.id, set(bridges))
    bridges = [name for name in bridges if name not in with_cards]
    if bridges:
        extra = await company_aliases.scan_cv_entries(
            db, company_aliases.search_patterns(bridges, whole=True)
        )
        loyal = company_aliases.names_mostly_bridged(
            extra, bridges, anchors=company_aliases.anchors_of(seeds)
        )
        variants.update(company_aliases.exact_variants(extra, set(loyal)))

    own_cards = sorted(
        (
            OwnCardOut(id=card_id, name=name, current=variants[key].current_count)
            for key, (card_id, name) in cards.items()
        ),
        key=lambda card: (-card.current, card.name),
    )[: company_aliases.MAX_OWN_CARDS]
    open_variants = {key: v for key, v in variants.items() if key not in cards}
    top, rest = company_aliases.rank(open_variants)
    return CompanyAliasesOut(
        decisions=decisions,
        suggestions=[
            AliasVariantOut(
                key=variant.key,
                name=variant.name,
                people=variant.people_count,
                current=variant.current_count,
            )
            for variant in top
        ],
        other_count=rest.count,
        other_min=rest.fewest,
        other_max=rest.most,
        own_cards=own_cards,
    )


async def _other_cards(
    db: AsyncSession, company_id: int, keys: set[str]
) -> dict[str, tuple[int, str]]:
    """Karty innych firm o tych nazwach kanonicznych (nazwa → id, nazwa karty)."""
    if not keys:
        return {}
    rows = await db.execute(
        select(SalesCompany.normalized_name, SalesCompany.id, SalesCompany.name)
        .where(
            SalesCompany.normalized_name.in_(keys),
            SalesCompany.archived_at.is_(None),
            SalesCompany.id != company_id,
        )
        .order_by(SalesCompany.id.desc())
    )
    return {key: (card_id, name) for key, card_id, name in rows}


@router.get("/{company_id}/people/aliases", response_model=CompanyAliasesOut)
# Skan wpisów CV po marce, osobno od listy osób, żeby panel na niego nie czekał.
@limiter.limit("30/minute", key_func=user_or_ip_key)
async def company_people_aliases(
    request: Request,  # wymagane przez slowapi
    company_id: int,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> CompanyAliasesOut:
    company = await _company_or_404(db, company_id)
    try:
        return await _suggest(db, company)
    except DBAPIError as exc:
        if not _is_statement_timeout(exc):
            raise
        await db.rollback()
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Nie udało się teraz sprawdzić innych nazw z CV. Spróbuj później.",
        ) from exc


@router.post("/{company_id}/people/aliases", response_model=AliasDecisionOut)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def decide_company_alias(
    request: Request,  # wymagane przez slowapi
    company_id: int,
    body: AliasDecisionIn,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> AliasDecisionOut:
    """„Dołącz” albo „Nie ta firma”. Druga decyzja o tej nazwie zastępuje pierwszą."""
    company = await _company_or_404(db, company_id)
    alias = body.name.strip()
    canonical = normalize_company_name(alias)
    if len(canonical) < company_aliases.MIN_NAME_LEN:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ta nazwa jest za krótka."
        )
    if canonical == company.normalized_name:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail="To już nazwa tej karty."
        )
    if body.status == company_aliases.JOINED:
        if not company_aliases.can_be_alias(canonical):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tej nazwy nie doliczamy do firmy.",
            )
        if await _other_cards(db, company.id, {canonical}):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="Ta nazwa ma własną kartę firmy. Jeśli to duplikat, scal karty.",
            )
    row = (
        await db.execute(
            insert(SalesCompanyAlias)
            .values(
                company_id=company.id,
                alias=alias,
                normalized_alias=canonical,
                status=body.status,
                created_by_user_id=current_user.id,
            )
            .on_conflict_do_update(
                constraint="uq_sales_company_aliases_name",
                set_={
                    "alias": alias,
                    "status": body.status,
                    "created_by_user_id": current_user.id,
                    "updated_at": func.now(),
                },
            )
            .returning(SalesCompanyAlias)
        )
    ).scalar_one()
    out = _decision_out(row)
    await db.commit()
    return out


@router.delete(
    "/{company_id}/people/aliases/{alias_id}", status_code=status.HTTP_204_NO_CONTENT
)
@limiter.limit("60/minute", key_func=user_or_ip_key)
async def undo_company_alias(
    request: Request,  # wymagane przez slowapi
    company_id: int,
    alias_id: int,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Cofnięcie decyzji: nazwa wraca do podpowiedzi, liczby się przeliczają."""
    row = await db.get(SalesCompanyAlias, alias_id)
    if row is None or row.company_id != company_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    await db.delete(row)
    await db.commit()
