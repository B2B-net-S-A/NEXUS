"""Sprzedaż → ocena potencjału firmy i baza wiedzy oceny (decyzja Artura 23.11.2026).

* ``/api/sales/companies/{id}/potential``: stan oceny (odczyt „Sprzedaż: podgląd”)
  i zamówienie nowej („Sprzedaż: edycja”, płatny bieg bota i modelu, więc limit
  10 na godzinę na osobę i 30 minut przerwy dla tej samej firmy).
* ``/api/sales/potential-knowledge``: baza wiedzy (oferta i referencje); odczyt
  „Sprzedaż: podgląd”, zapis „Sprzedaż: edycja” (decyzja Artura z 23.11.2026).

Wyłączona flaga ``SALES_BOT_TASKS_ENABLED``: start odpowiada 409, odczyt oceny
``enabled: false``. Baza wiedzy działa zawsze (to dane NEXUSA, nie bieg bota).

Bez ``from __future__ import annotations`` (slowapi #579). Logi: numery i liczby.
→ docs/claude/sprzedaz/ocena-potencjalu.md
"""

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.core.scheduling import business_today
from app.models.sales import SalesCompany, SalesSignalRun
from app.models.user import User
from app.services.sales import bot_tasks, bots, potential, potential_knowledge, signals
from app.services.sales.bot_tasks.potential import OFFER_LINES, POTENTIAL

logger = logging.getLogger(__name__)

router = APIRouter()
knowledge_router = APIRouter()

TASKS_OFF_DETAIL = "Zadania bota są wyłączone."
NOT_CONFIGURED_DETAIL = "Bot researchu nie jest podłączony. Daj znać administratorowi."
NOT_FOUND_DETAIL = "Nie ma takiej firmy w kartotece sprzedaży."
ARCHIVED_DETAIL = "Firma jest w archiwum. Przywróć ją, żeby ocenić potencjał."
CLIENT_DETAIL = (
    "Tej firmy nie wysyłamy do bota: to klient NEXUSA, nasza firma "
    "albo karta ma „Nie kontaktować”."
)
NO_KNOWLEDGE_DETAIL = (
    "Baza wiedzy jest pusta. Uzupełnij ją w Sprzedaż → Leady → Boty → Baza wiedzy."
)
COOLDOWN_DETAIL = (
    "Ocena tej firmy już trwa albo powstała przed chwilą. Odśwież za kilka minut."
)
COOLDOWN = timedelta(minutes=30)


class RunOut(BaseModel):
    id: int
    status: str
    started_at: datetime


class ReferenceOut(BaseModel):
    id: str
    client: str
    kind: str
    sectors: list[str]
    services: list[str]
    scope: str
    since: str
    letter_date: Optional[date]
    valid_until: Optional[date]
    signed_by: str
    quote: str
    public_tender: bool
    note: str
    #: Aktualność listu (``None`` dla realizacji i logo).
    fresh: Optional[bool] = None
    #: Aktywne kontrakty klienta w NEXUSIE; ``None`` = takiego klienta nie ma.
    nexus_active: Optional[int] = None


class PickedReferenceOut(BaseModel):
    reference: ReferenceOut
    why: str


class PotentialResultOut(BaseModel):
    id: int
    #: ``pending`` (research jest, ocena w toku), ``ready``, ``failed``.
    state: str
    error: Optional[str] = None
    created_at: datetime
    assessed_at: Optional[str] = None
    research: dict[str, Any]
    ksc: Optional[dict[str, Any]] = None
    assessment: Optional[dict[str, Any]] = None
    references: list[PickedReferenceOut] = Field(default_factory=list)


class PotentialOut(BaseModel):
    enabled: bool
    lines: dict[str, str] = Field(default_factory=dict)
    run: Optional[RunOut] = None
    result: Optional[PotentialResultOut] = None


class HistoryOut(BaseModel):
    at: str
    by_name: str
    summary: str


class KnowledgeOut(BaseModel):
    offer: str
    references: list[ReferenceOut]
    history: list[HistoryOut]
    updated_at: Optional[datetime]
    can_edit: bool


class ParseIn(BaseModel):
    text: str = Field(max_length=200_000)


class ParseOut(BaseModel):
    references: list[ReferenceOut]


def _ref_out(
    ref: potential_knowledge.Reference, today: date, active: Optional[int] = None
) -> ReferenceOut:
    return ReferenceOut(
        **ref.model_dump(),
        fresh=potential_knowledge.is_fresh(ref, today),
        nexus_active=active,
    )


async def _last_run(db: AsyncSession, company_id: int) -> Optional[SalesSignalRun]:
    return (
        await db.execute(
            select(SalesSignalRun)
            .where(
                SalesSignalRun.kind == "briefing",
                SalesSignalRun.company_ids.contains([company_id]),
                SalesSignalRun.modes[str(company_id)].astext == POTENTIAL,
            )
            .order_by(SalesSignalRun.started_at.desc(), SalesSignalRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _potential_out(db: AsyncSession, company_id: int) -> PotentialOut:
    run = await _last_run(db, company_id)
    row = await potential.latest(db, company_id)
    result = None
    if row is not None:
        payload = row.payload or {}
        assessment = payload.get("assessment")
        picked: list[PickedReferenceOut] = []
        if assessment:
            knowledge = await potential_knowledge.load(db)
            by_id = {ref.id: ref for ref in knowledge.references}
            today = business_today()
            picked = [
                PickedReferenceOut(
                    reference=_ref_out(by_id[item["id"]], today),
                    why=item.get("why", ""),
                )
                for item in assessment.get("references") or []
                if item.get("id") in by_id
            ]
        result = PotentialResultOut(
            id=row.id,
            state=str(payload.get("state") or "pending"),
            error=payload.get("error"),
            created_at=row.created_at,
            assessed_at=payload.get("assessed_at"),
            research=payload.get("research") or {},
            ksc=payload.get("ksc"),
            assessment=assessment,
            references=picked,
        )
    return PotentialOut(
        enabled=True,
        lines=OFFER_LINES,
        run=None
        if run is None
        else RunOut(id=run.id, status=run.status, started_at=run.started_at),
        result=result,
    )


@router.get("/{company_id}/potential", response_model=PotentialOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def company_potential(
    company_id: int,
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> PotentialOut:
    if not bot_tasks.enabled():
        return PotentialOut(enabled=False)
    return await _potential_out(db, company_id)


@router.post("/{company_id}/potential", response_model=PotentialOut)
@limiter.limit("10/hour", key_func=user_or_ip_key)
async def start_potential(
    company_id: int,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> PotentialOut:
    if not bot_tasks.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail=TASKS_OFF_DETAIL)
    user_id = current_user.id
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if company.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=ARCHIVED_DETAIL)
    # Te same bramki co każdy research bota: klient NEXUSA, „Nie kontaktować”, nasza firma.
    from app.services.sales import signal_targets  # noqa: PLC0415

    if company_id not in await signal_targets.eligible_companies(db, [company_id]):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=CLIENT_DETAIL)
    if (await potential_knowledge.load(db)).empty:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NO_KNOWLEDGE_DETAIL)
    now = datetime.now(timezone.utc)
    last = await _last_run(db, company_id)
    if (
        last is not None
        and last.status != "failed"
        and last.started_at >= now - COOLDOWN
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail=COOLDOWN_DETAIL)
    paused = await bots.paused_refusal(db, "briefing")
    if paused:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=paused)
    run = await signals.start_run(
        db,
        "briefing",
        [company_id],
        now=now,
        modes={company_id: POTENTIAL},
        requested_by_user_id=user_id,
    )
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_CONFIGURED_DETAIL)
    logger.info(
        "sales_potential run=%s company=%s status=%s", run.id, company_id, run.status
    )
    return await _potential_out(db, company_id)


# ── Baza wiedzy ────────────────────────────────────────────────────────────


async def _knowledge_out(
    db: AsyncSession, knowledge: potential_knowledge.Knowledge, *, can_edit: bool
) -> KnowledgeOut:
    today = business_today()
    active = await potential_knowledge.active_contracts_by_reference(
        db, knowledge.references
    )
    return KnowledgeOut(
        offer=knowledge.offer,
        references=[
            _ref_out(ref, today, active.get(ref.id)) for ref in knowledge.references
        ],
        history=[
            HistoryOut(
                at=str(item.get("at") or ""),
                by_name=str(item.get("by_name") or ""),
                summary=str(item.get("summary") or ""),
            )
            for item in knowledge.history
        ],
        updated_at=knowledge.updated_at,
        can_edit=can_edit,
    )


def _can_edit(user: User) -> bool:
    from app.services.action_permissions import has_permission  # noqa: PLC0415

    return has_permission(user, "sales_edit")


@knowledge_router.get("", response_model=KnowledgeOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def get_knowledge(
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeOut:
    can_edit = _can_edit(current_user)
    return await _knowledge_out(
        db, await potential_knowledge.load(db), can_edit=can_edit
    )


@knowledge_router.put("", response_model=KnowledgeOut)
@limiter.limit("60/hour", key_func=user_or_ip_key)
async def put_knowledge(
    payload: potential_knowledge.KnowledgeIn,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> KnowledgeOut:
    user_id, user_name = current_user.id, current_user.name
    knowledge = await potential_knowledge.save(
        db, payload, user_id=user_id, user_name=user_name
    )
    await db.commit()
    logger.info(
        "sales_potential knowledge saved by=%s references=%d",
        user_id,
        len(knowledge.references),
    )
    return await _knowledge_out(db, knowledge, can_edit=True)


@knowledge_router.post("/parse-table", response_model=ParseOut)
@limiter.limit("60/hour", key_func=user_or_ip_key)
async def parse_table(
    payload: ParseIn,
    request: Request,
    current_user: SalesEditUser,
) -> ParseOut:
    """Podgląd importu tabeli z dokumentu; zapis idzie potem przez ``PUT``."""

    today = business_today()
    return ParseOut(
        references=[
            _ref_out(ref, today)
            for ref in potential_knowledge.parse_table(payload.text)
        ]
    )
