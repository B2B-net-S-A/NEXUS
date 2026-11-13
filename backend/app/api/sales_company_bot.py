"""Sprzedaż → karta firmy: bot uzupełnia kartę (G-A) i odpowiada na pytania (G-B).

Prefiks ``/api/sales/companies`` (obok ``sales_companies.py``). Start biegu to
„Sprzedaż: edycja”, odczyt stanu „Sprzedaż: podgląd”. Każde wywołanie startu to
płatny bieg bota, więc trasy mają limit na osobę: pytanie 10 na godzinę,
uzupełnienie 20 na godzinę, a ta sama karta nie wraca do bota przez 2 godziny.
Wyłączona flaga ``SALES_BOT_TASKS_ENABLED``: start odpowiada 409, odczyt
``enabled: false`` i karta nic nie pokazuje.

Osobny moduł, bo każda trasa w module z listy ``_RATE_LIMITED_MODULES`` musi
mieć limit. Bez ``from __future__ import annotations`` (slowapi #579: ciało
żądania wylądowałoby jako parametr query, czyli 422 na poprawnym żądaniu).

Logi są publiczne: numery i liczby, bez nazw firm i bez treści pytań.
→ docs/claude/sprzedaz/sygnaly-grok-bot.md („Uzupełnianie kart”, „Zapytaj bota”)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.sales_bot_results import BotResultOut, _out
from app.api.sales_gates import SalesEditUser, SalesViewUser
from app.core.database import get_db
from app.core.rate_limit import limiter, user_or_ip_key
from app.models.sales import SalesBotResult, SalesCompany, SalesSignalRun
from app.models.user import User
from app.services.action_permissions import has_permission
from app.services.sales import bot_card_history, bot_tasks, signals
from app.services.sales.bot_tasks import enrich, people, question

logger = logging.getLogger(__name__)

router = APIRouter()

TASKS_OFF_DETAIL = "Zadania bota są wyłączone."
NOT_CONFIGURED_DETAIL = "Bot researchu nie jest podłączony. Daj znać administratorowi."
NOT_FOUND_DETAIL = "Nie ma takiej firmy w kartotece sprzedaży."
ARCHIVED_DETAIL = "Firma jest w archiwum. Przywróć ją, żeby pytać bota."
COOLDOWN_DETAIL = (
    "Bot sprawdzał tę kartę mniej niż 2 godziny temu. "
    "Propozycje pojawią się na karcie, gdy skończy."
)
QUESTIONS_SHOWN = 5
HISTORY_SHOWN = 30


class PersonRef(BaseModel):
    id: int
    name: str


class AnswerLineOut(BaseModel):
    text: str
    url: Optional[str] = None
    published: Optional[str] = None


class QuestionOut(BaseModel):
    run_id: int
    #: Stan biegu: ``started`` (bot szuka), ``received``, ``failed``, ``expired``.
    status: str
    question: Optional[str]
    asked_by: Optional[PersonRef]
    asked_at: datetime
    answered_at: Optional[datetime]
    minutes: Optional[int]
    answer: Optional[list[AnswerLineOut]]


class QuestionsOut(BaseModel):
    enabled: bool
    items: list[QuestionOut]


class AskIn(BaseModel):
    #: Limit długości sprawdza ``question.clean_question`` z polskim komunikatem.
    question: str = Field(max_length=2000)


class EnrichRunOut(BaseModel):
    id: int
    status: str
    started_at: datetime


class EnrichStateOut(BaseModel):
    enabled: bool
    #: Ostatni bieg uzupełnienia tej karty (także nocny).
    run: Optional[EnrichRunOut] = None
    #: Najnowsza propozycja, o której nie zdecydowano do końca (``new``/``partial``).
    result: Optional[BotResultOut] = None


class HistoryLineOut(BaseModel):
    label: str
    after: Optional[str] = None
    before: Optional[str] = None
    source: Optional[str] = None
    note: Optional[str] = None
    other_company: Optional[PersonRef] = None


class HistoryEntryOut(BaseModel):
    at: datetime
    #: Który bot: „Dane firm” albo „Kontakty”.
    bot: str
    lines: list[HistoryLineOut]


class HistoryOut(BaseModel):
    enabled: bool
    items: list[HistoryEntryOut]


def _refuse_when_off() -> None:
    if not bot_tasks.enabled():
        raise HTTPException(status.HTTP_409_CONFLICT, detail=TASKS_OFF_DETAIL)


async def _live_company(db: AsyncSession, company_id: int) -> SalesCompany:
    company = await db.get(SalesCompany, company_id)
    if company is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if company.archived_at is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=ARCHIVED_DETAIL)
    return company


def _for_company(company_id: int) -> Any:
    return SalesSignalRun.company_ids.contains([company_id])


def _minutes(run: SalesSignalRun) -> Optional[int]:
    if run.received_at is None:
        return None
    return max(0, round((run.received_at - run.started_at).total_seconds() / 60))


def _question_out(
    run: SalesSignalRun, user: Optional[User], result: Optional[SalesBotResult]
) -> QuestionOut:
    answer = None
    if result is not None:
        answer = [
            AnswerLineOut(**line) for line in (result.payload or {}).get("answer", [])
        ]
    return QuestionOut(
        run_id=run.id,
        status=run.status,
        question=(run.request or {}).get("question"),
        asked_by=None if user is None else PersonRef(id=user.id, name=user.name),
        asked_at=run.started_at,
        answered_at=run.received_at,
        minutes=_minutes(run),
        answer=answer,
    )


@router.get("/{company_id}/questions", response_model=QuestionsOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def company_questions(
    company_id: int,
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> QuestionsOut:
    if not bot_tasks.enabled():
        return QuestionsOut(enabled=False, items=[])
    rows = (
        await db.execute(
            select(SalesSignalRun, User, SalesBotResult)
            .outerjoin(User, User.id == SalesSignalRun.requested_by_user_id)
            .outerjoin(
                SalesBotResult,
                (SalesBotResult.run_id == SalesSignalRun.id)
                & (SalesBotResult.kind == question.KIND),
            )
            .where(SalesSignalRun.kind == question.KIND, _for_company(company_id))
            .order_by(SalesSignalRun.started_at.desc(), SalesSignalRun.id.desc())
            .limit(QUESTIONS_SHOWN)
        )
    ).all()
    return QuestionsOut(
        enabled=True, items=[_question_out(run, user, res) for run, user, res in rows]
    )


@router.post(
    "/{company_id}/ask",
    response_model=QuestionOut,
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit("10/hour", key_func=user_or_ip_key)
async def ask_bot(
    company_id: int,
    payload: AskIn,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> QuestionOut:
    _refuse_when_off()
    # Przed commitem w ``start_run``: później obiekt sesji jest wygaszony.
    user_id, user_name = current_user.id, current_user.name
    await _live_company(db, company_id)
    try:
        text = question.clean_question(payload.question)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from None
    run = await signals.start_run(
        db,
        question.KIND,
        [company_id],
        request={"question": text},
        requested_by_user_id=user_id,
    )
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_CONFIGURED_DETAIL)
    logger.info(
        "sales_bot ask run=%s company=%s status=%s", run.id, company_id, run.status
    )
    return QuestionOut(
        run_id=run.id,
        status=run.status,
        question=text,
        asked_by=PersonRef(id=user_id, name=user_name),
        asked_at=run.started_at,
        answered_at=None,
        minutes=None,
        answer=None,
    )


async def _enrich_state(db: AsyncSession, company_id: int) -> EnrichStateOut:
    run = (
        await db.execute(
            select(SalesSignalRun)
            .where(SalesSignalRun.kind == enrich.KIND, _for_company(company_id))
            .order_by(SalesSignalRun.started_at.desc(), SalesSignalRun.id.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    row = (
        await db.execute(
            select(SalesBotResult, SalesCompany)
            .join(SalesCompany, SalesCompany.id == SalesBotResult.company_id)
            .where(
                SalesBotResult.kind == enrich.KIND,
                SalesBotResult.company_id == company_id,
                SalesBotResult.status.in_(("new", "partial")),
            )
            .order_by(SalesBotResult.created_at.desc(), SalesBotResult.id.desc())
            .limit(1)
        )
    ).first()
    return EnrichStateOut(
        enabled=True,
        run=None
        if run is None
        else EnrichRunOut(id=run.id, status=run.status, started_at=run.started_at),
        result=None if row is None else _out(row[0], row[1]),
    )


@router.get("/{company_id}/enrich", response_model=EnrichStateOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def company_enrich_state(
    company_id: int,
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> EnrichStateOut:
    if not bot_tasks.enabled():
        return EnrichStateOut(enabled=False)
    return await _enrich_state(db, company_id)


@router.post("/{company_id}/enrich", response_model=EnrichStateOut)
@limiter.limit("20/hour", key_func=user_or_ip_key)
async def start_enrich(
    company_id: int,
    request: Request,
    current_user: SalesEditUser,
    db: AsyncSession = Depends(get_db),
) -> EnrichStateOut:
    _refuse_when_off()
    user_id = current_user.id
    await _live_company(db, company_id)
    now = datetime.now(timezone.utc)
    recent = await db.scalar(
        select(SalesSignalRun.id)
        .where(
            SalesSignalRun.kind == enrich.KIND,
            _for_company(company_id),
            SalesSignalRun.status != "failed",
            SalesSignalRun.started_at >= now - enrich.MANUAL_COOLDOWN,
        )
        .limit(1)
    )
    if recent is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=COOLDOWN_DETAIL)
    run = await signals.start_run(
        db, enrich.KIND, [company_id], now=now, requested_by_user_id=user_id
    )
    if run is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=NOT_CONFIGURED_DETAIL)
    logger.info(
        "sales_bot enrich run=%s company=%s status=%s", run.id, company_id, run.status
    )
    return await _enrich_state(db, company_id)


@router.get("/{company_id}/bot-history", response_model=HistoryOut)
@limiter.limit("120/minute", key_func=user_or_ip_key)
async def company_bot_history(
    company_id: int,
    request: Request,
    current_user: SalesViewUser,
    db: AsyncSession = Depends(get_db),
) -> HistoryOut:
    """Historia karty: co boty wpisały od razu, co zostawiły i skąd to wzięły.

    Osoby widzi tylko konto z „Sprzedaż: edycja” (jak mapę decydentów).
    """

    if not bot_tasks.enabled():
        return HistoryOut(enabled=False, items=[])
    with_people = has_permission(current_user, "sales_edit")
    kinds = [enrich.KIND, people.KIND] if with_people else [enrich.KIND]
    rows = (
        await db.execute(
            select(
                SalesBotResult.kind,
                SalesBotResult.decided_at,
                SalesBotResult.updated_at,
                SalesBotResult.created_at,
                SalesBotResult.payload,
            )
            .where(
                SalesBotResult.company_id == company_id,
                SalesBotResult.kind.in_(kinds),
                SalesBotResult.status.in_(("accepted", "partial")),
            )
            .order_by(SalesBotResult.created_at.desc(), SalesBotResult.id.desc())
            .limit(HISTORY_SHOWN)
        )
    ).all()
    entries = bot_card_history.build(
        [
            (kind, decided or updated or created, payload)
            for kind, decided, updated, created, payload in rows
        ],
        with_people=with_people,
    )
    return HistoryOut(
        enabled=True,
        items=[
            HistoryEntryOut(
                at=entry.at,
                bot=entry.bot,
                lines=[
                    HistoryLineOut(
                        label=line.label,
                        after=line.after,
                        before=line.before,
                        source=line.source,
                        note=line.note,
                        other_company=None
                        if line.other_company_id is None
                        else PersonRef(
                            id=line.other_company_id,
                            name=line.other_company_name or "",
                        ),
                    )
                    for line in entry.lines
                ],
            )
            for entry in entries
        ],
    )
