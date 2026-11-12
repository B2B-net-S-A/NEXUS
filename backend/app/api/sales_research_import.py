"""Sprzedaż → Leady: lista osób z researchu do map decyzyjnych Fabryk IT.

Prefiks ``/api/sales/it-factories/research-import`` (wpięty w ``app/main.py``).
Rekomendacja B1, decyzje Artura z 10.11.2026: plik wgrywa człowiek z „Sprzedaż:
edycja”, przegląd pokazuje los każdego wiersza, a akceptacja dodaje osobę do mapy
ze statusem „bez kontaktu”. NEXUS niczego nie pobiera ze strony researchu i nie
wysyła osób do bota. Logika: ``services/sales/research_file.py`` (odczyt pliku)
i ``services/sales/research_import.py`` (dopasowanie firm, zapis).

Plik nie jest nigdzie przechowywany: przegląd odsyła wiersze, a akceptacja
przyjmuje je z powrotem i sprawdza od nowa. Ponowne wgranie tej samej listy
pokazuje osoby już dodane jako obecne na mapie.
"""

# NIE dodawaj tu `from __future__ import annotations`: moduł ma `@limiter.limit`
# (CLAUDE.md, ciało żądania ląduje wtedy jako parametr query).

import asyncio
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_companies import _is_statement_timeout
from app.api.sales_factories import FactoryClientOut
from app.api.sales_gates import SalesEditUser
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_today
from app.models.sales import SalesCompany
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.sales import client_gate, known_counts, research_import
from app.services.sales.research_file import (
    MAX_FILE_BYTES,
    MAX_ROWS,
    TOO_BIG_DETAIL,
    ResearchFile,
    ResearchFileError,
    clean_text,
    parse_research_file,
    site_domain,
    valid_link,
)

router = APIRouter()

OWNER_DETAIL = (
    "Opiekunem nowych kont może być aktywna osoba z uprawnieniem „Sprzedaż: edycja”."
)
SOURCE_REQUIRED = "Wpisz, skąd pochodzi lista (co najmniej 3 znaki)."
#: Sufit kart w jednym skanie „Znamy teraz”: skan po nazwach rośnie z ich liczbą.
KNOWN_SCAN_CARDS = 150

CompanyState = Literal[
    "account", "card", "choose", "no_card", "client", "blocked", "own_company"
]
Confidence = Literal["confirmed", "to_verify"]


# Modele mają przedrostek „Research”: nazwa zajęta w API v1 zmienia nazwy obu
# w OpenAPI i psuje kontrakt v1 (``tests/test_integrations_v1_contract.py``).
class ResearchAccountOut(BaseModel):
    opportunity_id: int
    title: str
    stage_name: str
    status: str
    map_total: int
    map_contacted: int


class ResearchCardOut(BaseModel):
    id: int
    name: str
    #: Nazwa karty to dokładnie nazwa z pliku; pozostałe karty to ta sama marka.
    exact: bool
    contacts: int
    account: Optional[ResearchAccountOut]
    #: Konto w lejku jest tylko w archiwum: akceptacja założy nowe.
    archived_account: bool
    client: Optional[FactoryClientOut]
    #: Firma „Nie kontaktować”: tej karty nie da się wybrać.
    blocked: bool
    #: ``None``: licznika nie udało się policzyć albo karta jest poza skanem.
    known_current: Optional[int]
    known_past: Optional[int]


class ResearchCompanyOut(BaseModel):
    key: str
    name: str
    state: CompanyState
    #: Karta wybrana samoczynnie; przy ``choose`` wskazuje ją człowiek.
    company_id: Optional[int]
    cards: list[ResearchCardOut]
    client: Optional[FactoryClientOut]


class ResearchRowOut(BaseModel):
    line: int
    company_key: str
    company: str
    name: str
    role_in_company: Optional[str]
    email: Optional[str]
    phone: Optional[str]
    linkedin_url: Optional[str]
    source_url: Optional[str]
    domain: Optional[str]
    notes: Optional[str]
    confidence: Confidence
    decision_level: int
    #: Pola opcjonalne, które odpadły przy odczycie pliku.
    warnings: list[str]
    #: ``on_map``: osoba jest już na mapie; ``repeated``: drugi raz w tym pliku.
    person: Literal["new", "on_map", "repeated"]
    on_map_opportunity_id: Optional[int]


class ResearchSkippedOut(BaseModel):
    line: int
    reason: str


class ResearchPreviewOut(BaseModel):
    companies: list[ResearchCompanyOut]
    rows: list[ResearchRowOut]
    #: Wiersze bez firmy albo osoby: nie ma czego dodać.
    skipped: list[ResearchSkippedOut]
    #: Skan „Znamy teraz” się nie udał: liczniki są puste, reszta przeglądu działa.
    known_failed: bool
    #: Skan trafił w sufit wierszy: liczniki są dolną granicą.
    known_truncated: bool
    #: ``"Cognism"`` dla eksportu z Cognism: ekran podpowiada nim pole „Skąd lista”.
    origin: Optional[str] = None


class ResearchPersonIn(BaseModel):
    """Wiersz z przeglądu odesłany do zapisu; serwer sprawdza go od nowa."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    line: int = Field(ge=1, le=1_000_000)
    company: str = Field(min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=255)
    role_in_company: Optional[str] = Field(default=None, max_length=255)
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=50)
    linkedin_url: Optional[str] = Field(default=None, max_length=512)
    source_url: Optional[str] = Field(default=None, max_length=1000)
    domain: Optional[str] = Field(default=None, max_length=255)
    notes: Optional[str] = Field(default=None, max_length=2000)
    confidence: Confidence = "to_verify"
    decision_level: Optional[int] = Field(default=None, ge=1, le=4)
    #: Karta wskazana na ekranie; ``None`` = jedyna karta o tej nazwie albo nowa.
    company_id: Optional[int] = Field(default=None, ge=1)

    @field_validator(
        "company",
        "name",
        "role_in_company",
        "email",
        "phone",
        "linkedin_url",
        "source_url",
        "domain",
        "notes",
        mode="before",
    )
    @classmethod
    def _no_control_chars(cls, value: Any) -> Any:
        # Długość sprawdza pole; tu tylko znaki sterujące i odstępy.
        return (clean_text(value, 10_000) or "") if isinstance(value, str) else value

    @field_validator("role_in_company", "email", "phone", "linkedin_url", "notes")
    @classmethod
    def _blank_is_none(cls, value: Optional[str]) -> Optional[str]:
        return value or None

    @field_validator("source_url")
    @classmethod
    def _http_only(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        url = valid_link(value, 1000)
        if url is None:
            raise ValueError("Link źródła musi zaczynać się od http:// albo https://.")
        return url

    @field_validator("domain")
    @classmethod
    def _domain_shape(cls, value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        domain = site_domain(value)
        if domain is None:
            raise ValueError("Domena firmy wygląda na niepełną.")
        return domain


class ResearchAcceptIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Skąd pochodzi lista; trafia przy każdej osobie na mapie i do historii szansy.
    source_label: str = Field(max_length=255)
    #: Opiekun nowych kont w lejku; bez wartości zalogowana osoba.
    owner_user_id: Optional[int] = Field(default=None, ge=1)
    people: list[ResearchPersonIn] = Field(min_length=1, max_length=MAX_ROWS)

    @field_validator("source_label")
    @classmethod
    def _source_label(cls, value: str) -> str:
        text = clean_text(value, 255) or ""
        if len(text) < 3:
            raise ValueError(SOURCE_REQUIRED)
        return text


class ResearchOutcomeOut(BaseModel):
    line: int
    result: Literal[
        "added",
        "on_map",
        "client",
        "blocked",
        "own_company",
        "choose_card",
        "card_missing",
        "error",
    ]
    detail: Optional[str]
    company_id: Optional[int]
    opportunity_id: Optional[int]
    created_company: bool
    created_account: bool
    client: Optional[FactoryClientOut]


class ResearchAcceptOut(BaseModel):
    outcomes: list[ResearchOutcomeOut]
    added: int
    created_companies: int
    created_accounts: int


def _client_out(match: Optional[client_gate.ClientMatch]) -> Optional[FactoryClientOut]:
    if match is None:
        return None
    return FactoryClientOut(name=match.client_name, delivery_lead=match.delivery_lead)


async def _read_list(file: UploadFile) -> ResearchFile:
    """Plik czytany najwyżej do limitu + 1 bajt; parser biegnie poza pętlą zdarzeń."""

    payload = await file.read(MAX_FILE_BYTES + 1)
    if len(payload) > MAX_FILE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, detail=TOO_BIG_DETAIL
        )
    try:
        return await asyncio.to_thread(
            parse_research_file, file.filename or "", payload
        )
    except ResearchFileError as exc:
        code = (
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
            if exc.too_large
            else status.HTTP_422_UNPROCESSABLE_ENTITY
        )
        raise HTTPException(code, detail=exc.detail) from exc


def _scan_ids(companies: list[research_import.CompanyPlan]) -> list[int]:
    """Karty do skanu „Znamy teraz”: najpierw cele, potem karty do wyboru."""

    targets = [c.company_id for c in companies if c.company_id is not None]
    choices = [
        card.id
        for company in companies
        if company.state == research_import.CHOOSE
        for card in company.cards
        if card.client is None and not card.blocked
    ]
    return list(dict.fromkeys([*targets, *choices]))[:KNOWN_SCAN_CARDS]


async def _known(
    db: AsyncSession, company_ids: list[int]
) -> Optional[known_counts.KnownPeople]:
    """Jeden skan dla całej listy; ``None``, gdy przekroczył limit czasu."""

    if not company_ids:
        return known_counts.KnownPeople(counts={}, truncated=False)
    cards = list(
        (
            await db.execute(
                select(SalesCompany)
                .where(SalesCompany.id.in_(company_ids))
                .order_by(SalesCompany.id)
            )
        ).scalars()
    )
    try:
        return await known_counts.count_known_people(db, cards)
    except DBAPIError as exc:
        if not _is_statement_timeout(exc):
            raise
        # Przegląd jest już policzony; bez cofnięcia odpowiedź skończyłaby się 500.
        await db.rollback()
        return None


@router.post("/preview", response_model=ResearchPreviewOut)
# Odczyt arkusza i skan kandydatów kosztują procesor i bazę: limit chroni proces web.
@limiter.limit("20/minute")
async def preview_research_list(
    request: Request,  # wymagane przez slowapi
    current_user: SalesEditUser,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> ResearchPreviewOut:
    """Los każdego wiersza listy przed zapisem; niczego nie zapisuje."""

    listing = await _read_list(file)
    plan = await research_import.plan(db, listing.rows)
    return await preview_out(db, plan, listing.skipped, origin=listing.origin)


async def preview_out(
    db: AsyncSession,
    plan: research_import.Plan,
    skipped: list[Any],
    *,
    origin: Optional[str] = None,
) -> ResearchPreviewOut:
    """Przegląd z planu i licznikami „Znamy teraz”; też dla osób od bota."""

    # Skan idzie na końcu: po przekroczonym limicie czasu transakcja jest cofana.
    known = await _known(db, _scan_ids(plan.companies))
    counts = known.counts if known is not None else {}

    def card_out(card: research_import.Card) -> ResearchCardOut:
        found = counts.get(card.id)
        account = card.account
        return ResearchCardOut(
            id=card.id,
            name=card.name,
            exact=card.exact,
            contacts=card.contacts,
            account=ResearchAccountOut(
                opportunity_id=account.opportunity_id,
                title=account.title,
                stage_name=account.stage_name,
                status=account.status,
                map_total=account.counts.total,
                map_contacted=account.counts.contacted,
            )
            if account is not None
            else None,
            archived_account=card.archived_account,
            client=_client_out(card.client),
            blocked=card.blocked,
            known_current=found.current if found is not None else None,
            known_past=found.past if found is not None else None,
        )

    return ResearchPreviewOut(
        companies=[
            ResearchCompanyOut(
                key=company.key,
                name=company.name,
                state=company.state,
                company_id=company.company_id,
                cards=[card_out(card) for card in company.cards],
                client=_client_out(company.client),
            )
            for company in plan.companies
        ],
        rows=[
            ResearchRowOut(
                line=item.row.line,
                company_key=item.company_key,
                company=item.row.company,
                name=item.row.name,
                role_in_company=item.row.title,
                email=item.row.email,
                phone=item.row.phone,
                linkedin_url=item.row.linkedin_url,
                source_url=item.row.source_url,
                domain=item.row.domain,
                notes=item.row.note,
                confidence=item.row.confidence,
                decision_level=item.row.decision_level,
                warnings=list(item.row.warnings),
                person=item.person,
                on_map_opportunity_id=item.on_map_opportunity_id,
            )
            for item in plan.rows
        ],
        skipped=[
            ResearchSkippedOut(line=row.line, reason=row.reason) for row in skipped
        ],
        known_failed=known is None,
        known_truncated=bool(known and known.truncated),
        origin=origin,
    )


async def _owner(
    db: AsyncSession, current_user: User, owner_user_id: Optional[int]
) -> int:
    if owner_user_id is None or owner_user_id == current_user.id:
        return current_user.id
    owner = await db.get(User, owner_user_id)
    if owner is None or not owner.is_active:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OWNER_DETAIL)
    await resolve_effective_access(db, [owner])
    if not has_permission(owner, ProductAction.sales_edit):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=OWNER_DETAIL)
    return owner.id


@router.post("/people", response_model=ResearchAcceptOut)
# Akceptacja wiersz po wierszu to jedno żądanie na klik, stąd wyższy limit.
@limiter.limit("120/minute")
async def accept_research_people(
    request: Request,  # wymagane przez slowapi
    payload: ResearchAcceptIn,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> ResearchAcceptOut:
    """Dodaje zaakceptowane osoby do map ze statusem „bez kontaktu”.

    Firma bez konta w lejku dostaje konto, firma bez karty także kartę. Klient
    NEXUSA nie dostaje niczego: wynik wiersza podaje klienta i Delivery Leada.
    """

    owner_id = await _owner(db, current_user, payload.owner_user_id)
    people = [
        research_import.Person(
            line=person.line,
            company=person.company,
            name=person.name,
            title=person.role_in_company,
            email=person.email,
            phone=person.phone,
            linkedin_url=person.linkedin_url,
            source_url=person.source_url,
            domain=person.domain,
            confidence=person.confidence,
            decision_level=person.decision_level,
            note=person.notes,
            company_id=person.company_id,
        )
        for person in payload.people
    ]
    try:
        outcomes = await research_import.accept(
            db,
            people,
            user_id=current_user.id,
            owner_user_id=owner_id,
            source_label=payload.source_label,
            today=business_today(),
            now=datetime.now(timezone.utc),
        )
    except research_import.NoPipelineError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    await db.commit()
    added = [o for o in outcomes if o.result == research_import.ADDED]
    return ResearchAcceptOut(
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
