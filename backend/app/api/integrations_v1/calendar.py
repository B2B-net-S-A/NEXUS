"""Kalendarz w API v1: rozmowy kandydatów u klienta i prepy (odczyt).

Scope ``calendar:read``. Rozmowa u klienta to wydarzenie ``client_interview``
z parą (kandydat, rekrutacja) — powstaje przy potwierdzeniu terminu od
klienta. Fazę rozmowy, cykl pary (ten sam co plakietka na Tablicy), prepy
i zamknięcie rundy debriefem liczą funkcje ekranu „Rozmowy u klienta”
(``services/integration_calendar_reads``).

Z wydarzenia wychodzą tylko termin, status i para: bez tytułu, opisu, miejsca,
uczestników (e-maili) i linków spotkań — wydarzenie z Outlooka bywa prywatne.
Treść debriefu (komentarz kandydata, pytania klienta) tylko z ``notes:read``;
warunek kandydata (zwykle stawka albo warunki umowy) dodatkowo z
``amounts:read``. Rozmowy rekrutacji klienta ukrytego albo usuniętego nie
istnieją dla klucza.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.integrations_v1.common import (
    INT4_MAX,
    AmountLevel,
    CalendarRead,
    IdPath,
    IntegrationRoute,
    Page,
    PageQuery,
    PageSizeQuery,
    amount_level,
    page_of,
    principal_of,
    principal_rate_key,
    read_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.calendar_event import EventStatus
from app.models.service_account import ServiceScope
from app.services import integration_calendar_reads as reads

router = APIRouter(route_class=IntegrationRoute)


# ── Wyjście ──────────────────────────────────────────────────────────────────


class InterviewCycleOut(BaseModel):
    """Cykl pary (kandydat, rekrutacja) — ten sam, co plakietka na Tablicy."""

    phase: Optional[str] = Field(
        description="awaiting_recruiter_pick · awaiting_dl_confirm · scheduled · "
        "debrief_due · debriefed; null = w cyklu nic się nie dzieje."
    )
    current_step: Optional[str] = Field(
        description="Pierwszy krok wymagający ruchu: slots · choice · prep · prep2 · "
        "interview · call · debrief."
    )
    slot_request_status: Optional[str] = Field(
        description="Wniosek o terminy od klienta: awaiting_recruiter · awaiting_dl · "
        "confirmed (otwarty wygrywa z potwierdzonym); null = brak wniosku."
    )
    interview_event_id: Optional[int] = Field(
        description="Rozmowa, którą cykl prowadzi teraz (telefon i debrief)."
    )


class InterviewOut(BaseModel):
    event_id: int
    status: str = Field(description="scheduled · completed · cancelled")
    start: datetime
    end: Optional[datetime]
    started: bool
    phase: str = Field(
        description="Faza tej rozmowy: scheduled (przed końcem) · call_due (okno "
        "telefonu po rozmowie) · debrief_overdue (po oknie, bez debriefu) · "
        "debriefed · cancelled."
    )
    debrief_done: bool = Field(
        description="Debrief zapisany po rozpoczęciu rozmowy, z pytaniami klienta "
        "albo „klient nie pytał” — zamyka rundę jak bramka ruchu karty."
    )
    current_round: bool = Field(
        description="Rozmowa jest rundą, którą cykl pary prowadzi teraz "
        "(do debriefu albo do prepów)."
    )
    candidate_id: int
    candidate_first_name: str
    candidate_last_name: str
    job_id: int
    job_title: str = Field(description="Nazwa rekrutacji od klienta.")
    client_id: Optional[int]
    client_name: Optional[str]
    cycle: InterviewCycleOut
    updated_at: datetime


class InterviewPrepOut(BaseModel):
    event_id: int
    prep_no: Optional[int] = Field(
        description="1 albo 2 (Prep 1 — DL, Prep 2 — rekruter)."
    )
    start: datetime
    end: Optional[datetime]
    status: str
    from_nexus: bool = Field(
        description="Prep założony w NEXUSIE (Teams) — ma stan transkryptu i ocenę."
    )
    transcription_setup: Optional[str] = Field(
        description="pending · enabled · failed · disabled"
    )
    transcript_status: Optional[str] = Field(
        description="waiting · fetched · missing (bez nagrania) · cancelled · "
        "forbidden · error"
    )
    review_status: Optional[str] = Field(description="ok · unavailable")
    review_level: Optional[str] = Field(description="weak · ok · good")
    late: bool = Field(
        description="Prep wypada po rozmowie, do której miał przygotować — do przełożenia."
    )


class InterviewDebriefOut(BaseModel):
    done: bool
    saved_at: Optional[datetime]
    outcome: Optional[str] = Field(description="good · medium · bad")
    offer_acceptance: Optional[str] = Field(description="yes · likely · no · unknown")
    client_questions_count: int
    no_client_questions: bool
    has_acceptance_condition: bool
    notes_redacted: bool = Field(
        description="true = bez ``notes:read``: komentarz i pytania klienta są null."
    )
    candidate_comment: Optional[str]
    client_questions: Optional[list[str]]
    costs_redacted: bool = Field(
        description="true = bez ``amounts:read``: warunek kandydata jest null."
    )
    acceptance_condition: Optional[str] = Field(
        description="Warunek kandydata (zwykle stawka albo warunki umowy) — "
        "``notes:read`` i ``amounts:read``."
    )


class InterviewDetailOut(InterviewOut):
    preps: list[InterviewPrepOut]
    debrief: Optional[InterviewDebriefOut] = Field(
        description="Debrief strony kandydata pod tą rozmową; null = nie zapisano."
    )


# ── Trasy ────────────────────────────────────────────────────────────────────


@router.get(
    "/interviews",
    response_model=Page[InterviewOut],
    summary="Rozmowy kandydatów u klienta",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_interviews(
    request: Request,
    _caller: CalendarRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 100,
    job_id: Optional[int] = Query(None, ge=1, le=INT4_MAX),
    candidate_id: Optional[int] = Query(None, ge=1, le=INT4_MAX),
    start_from: Optional[datetime] = Query(
        None, alias="from", description="Start rozmowy od (włącznie); bez strefy = UTC."
    ),
    start_to: Optional[datetime] = Query(
        None,
        alias="to",
        description="Start rozmowy przed (wyłącznie); bez strefy = UTC.",
    ),
    status: Optional[list[EventStatus]] = Query(
        None, description="scheduled · completed · cancelled; powtarzalny."
    ),
) -> dict:
    """Rozmowy u klienta rosnąco po starcie: para, termin, faza rozmowy,
    debrief zrobiony i cykl pary. Bez treści wydarzenia i bez e-maili
    uczestników."""
    filters = reads.InterviewFilters(
        job_id=job_id,
        candidate_id=candidate_id,
        start_from=start_from,
        start_to=start_to,
        statuses=tuple(status or ()),
    )
    rows, total = await reads.list_interview_rows(
        db, filters, page=page, page_size=page_size
    )
    items = await reads.interviews_out(db, rows, now=datetime.now(timezone.utc))
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get(
    "/interviews/{event_id}",
    response_model=InterviewDetailOut,
    summary="Rozmowa u klienta",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_interview(
    request: Request,
    event_id: IdPath,
    caller: CalendarRead,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pola listy, prepy tej rozmowy (stan transkryptu i ocena, bez treści)
    i debrief: flagi zawsze, komentarz i pytania klienta z ``notes:read``,
    warunek kandydata dodatkowo z ``amounts:read``."""
    row = await reads.load_interview_row(db, event_id)
    if row is None:
        raise HTTPException(404, detail="Rozmowa nie istnieje.")
    now = datetime.now(timezone.utc)
    (item,) = await reads.interviews_out(db, [row], now=now)
    feedback = await reads.load_debrief(db, row.id)
    notes = ServiceScope.notes_read.value in principal_of(caller).scopes
    return {
        **item,
        "preps": await reads.round_preps(db, row=row, now=now),
        "debrief": (
            reads.debrief_out(
                feedback,
                start=row.start_time,
                notes=notes,
                costs=amount_level(caller) is AmountLevel.all,
            )
            if feedback is not None
            else None
        ),
    }
