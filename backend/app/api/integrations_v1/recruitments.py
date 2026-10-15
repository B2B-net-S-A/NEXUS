"""Rekrutacje w API v1: lista, szczegóły, wymagania, Tablica, historia ruchów.

Scope ``recruitments:read``. Kwoty rekrutacji (budżet dla kandydata, stawka
Championa, oczekiwania kandydata na karcie) to koszt — tylko z
``amounts:read``; stawka do klienta na karcie Tablicy — sprzedaż
(``sales_amounts:read``). Imiona osób na kartach to dane osobowe: kontakt
kandydata nigdy tu nie wychodzi (od tego jest profil z ``candidates:contact``).

Odczyt liczy tymi samymi funkcjami co ekrany (klauzule listy z
``api/jobs.py``, zespół z ``services/job_team``, Tablica z
``api/pipeline.build_kanban_view``, dziennik ruchów z ``_JOB_MOVES_SQL``),
ale bez efektów ubocznych ekranu (``services/integration_recruitment_reads``).
Rekrutacje klienta ukrytego albo usuniętego nie wychodzą — ani na liście,
ani pod własnym id (``jobs_register_base_clause``).

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import date, datetime, time
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Caller
from app.api.integrations_v1.common import (
    INT4_MAX,
    AmountLevel,
    IdPath,
    IntegrationRoute,
    Money,
    Page,
    PageQuery,
    PageSizeQuery,
    RecruitmentsRead,
    amount_level,
    page_of,
    principal_rate_key,
    read_rate_limit,
)
from app.api.jobs import (
    jobs_open_only_clause,
    jobs_register_base_clause,
    jobs_search_clause,
)
from app.api.pipeline import _process_v4_cards, build_kanban_view
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.client import Client
from app.models.contact import Contact
from app.models.job import Job, JobStatus
from app.models.user import User
from app.services.champion_intake import effective_skill_names
from app.services.client_identity import client_display_name_expression
from app.services.critical_skills import effective_critical
from app.services.integration_recruitment_reads import (
    CARD_COST_FIELDS,
    MoneyVisibility,
    card_money,
    job_budget,
    job_moves_page,
    latest_client_rates,
    public_interview_badge,
    requirements_view,
    stage_counts_for_jobs,
    stage_definitions,
    visible_card_warnings,
)
from app.services.job_previous_recruiters import previous_recruiters_for_jobs
from app.services.job_priority import level_of, priorities_for_levels
from app.services.job_team import jobs_worked_by_clause, recruiters_for_jobs
from app.services.request_work_state import visible_state

router = APIRouter(route_class=IntegrationRoute)

_Id = Annotated[int, Field(ge=1, le=INT4_MAX)]
StatusFilter = Literal["open", "closed", "all", "draft", "published"]
PriorityFilter = Literal["p1", "p2", "accepting"]


def _visibility(caller: Caller) -> MoneyVisibility:
    level = amount_level(caller)
    return MoneyVisibility(
        sales=level >= AmountLevel.sales, costs=level is AmountLevel.all
    )


def _value(value: Any) -> Any:
    return getattr(value, "value", value)


# ── Modele odpowiedzi ────────────────────────────────────────────────────────


class RefOut(BaseModel):
    id: int
    name: Optional[str]


class RecruiterOut(BaseModel):
    id: int
    name: Optional[str]
    via: str = Field(description="owner | assignment | collaborator")
    proposed: bool = Field(
        description="Propozycja automatu czekająca na akceptację — jeszcze nie praca."
    )


class PreviousRecruiterOut(BaseModel):
    id: int
    name: Optional[str]
    reason: str = Field(description="closed | priority")
    parked_at: datetime


class StageCountOut(BaseModel):
    stage_def_id: Optional[int]
    stage: str
    name: Optional[str]
    order: Optional[int]
    category: str
    terminal_type: Optional[str]
    count: int


class RecruitmentOut(BaseModel):
    id: int
    reference_number: Optional[str]
    title: str = Field(description="Nazwa od klienta (idzie do klienta).")
    working_title: Optional[str] = Field(
        description="Tytuł dla rekrutera (ekrany wewnętrzne, nigdy do klienta)."
    )
    client_reference: Optional[str] = Field(
        description="Numer zapytania klienta (ZOB, SAP…)."
    )
    client: RefOut
    status: str = Field(description="draft | published | closed")
    is_open: bool = Field(description="Rekrutacja przekazana do searchu.")
    priority: str = Field(description="p1 | p2 | accepting")
    work_state: str = Field(
        description="to_review | searching | champion | client_silent | finished"
    )
    recruiters: list[RecruiterOut]
    previous_recruiters: list[PreviousRecruiterOut]
    delivery_lead: Optional[RefOut]
    headcount: int
    deadline: Optional[date]
    opened_at: datetime = Field(
        description="Data otwarcia: z importu, a bez niej data założenia."
    )
    closed_at: Optional[datetime]
    close_reason: Optional[str]
    candidate_count: int = Field(description="Osoby w rekrutacji (każdy etap).")
    stage_counts: list[StageCountOut] = Field(
        description="Osoby w kolumnach Tablicy (bieżący etap pary)."
    )
    off_template_count: int
    created_at: datetime
    updated_at: datetime


class RecruitmentDetailOut(RecruitmentOut):
    description: Optional[str]
    requirements: Optional[str]
    must_skills: list[str]
    nice_skills: list[str]
    critical_skills: list[str]
    seniority: Optional[str]
    work_mode: str = Field(description="fulltime | parttime | contract")
    remote_policy: Optional[str] = Field(description="onsite | hybrid | remote")
    onsite_days_per_week: Optional[int]
    onsite_days_per_month: Optional[int]
    location: Optional[str]
    deadline_time: Optional[time]
    industry: Optional[str]
    competence_category_id: Optional[int]
    hiring_manager: Optional[RefOut]
    pipeline_template_id: Optional[int]
    amounts_redacted: bool
    costs_redacted: bool
    rate_budget_hourly: Money = Field(description="Budżet dla kandydata, PLN/h.")
    rate_budget_hourly_min: Money = Field(description="„Od” przedziału, PLN/h.")
    effective_budget_hourly: Money = Field(
        description="Budżet używany przez wyszukiwanie (pole albo Champion), PLN/h."
    )
    effective_budget_hourly_min: Money
    salary_min: Money = Field(description="Historyczne widełki, PLN/mies.")
    salary_max: Money


async def _recruitment_rows(db: AsyncSession, jobs: list[Job]) -> list[dict]:
    """Wiersze listy — stała liczba zapytań na stronę."""
    job_ids = [job.id for job in jobs]
    client_ids = {job.client_id for job in jobs}
    clients: dict[int, str] = {}
    if client_ids:
        clients = dict(
            (
                await db.execute(
                    select(Client.id, client_display_name_expression()).where(
                        Client.id.in_(client_ids)
                    )
                )
            ).all()
        )
    lead_ids = {job.delivery_lead_id for job in jobs if job.delivery_lead_id}
    leads: dict[int, str] = {}
    if lead_ids:
        leads = dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(lead_ids))
                )
            ).all()
        )
    recruiters = await recruiters_for_jobs(db, job_ids)
    previous = await previous_recruiters_for_jobs(db, job_ids)
    counts = await stage_counts_for_jobs(db, jobs)
    rows = []
    for job in jobs:
        tally = counts.get(job.id)
        rows.append(
            {
                "id": job.id,
                "reference_number": job.reference_number,
                "title": job.title,
                "working_title": job.working_title,
                "client_reference": job.client_reference,
                "client": {"id": job.client_id, "name": clients.get(job.client_id)},
                "status": _value(job.status),
                "is_open": bool(job.is_open),
                "priority": level_of(job.priority),
                "work_state": visible_state(job.work_state, job.champion_found_at),
                "recruiters": [
                    {
                        "id": person.user_id,
                        "name": person.name,
                        "via": person.via,
                        "proposed": person.proposed,
                    }
                    for person in recruiters.get(job.id, [])
                ],
                "previous_recruiters": [
                    {
                        "id": person.user_id,
                        "name": person.name,
                        "reason": person.reason,
                        "parked_at": person.parked_at,
                    }
                    for person in previous.get(job.id, [])
                ],
                "delivery_lead": (
                    {
                        "id": job.delivery_lead_id,
                        "name": leads.get(job.delivery_lead_id),
                    }
                    if job.delivery_lead_id
                    else None
                ),
                "headcount": job.headcount,
                "deadline": job.deadline,
                "opened_at": job.opened_at or job.created_at,
                "closed_at": job.closed_at,
                "close_reason": _value(job.close_reason),
                "candidate_count": tally.candidates if tally else 0,
                "stage_counts": tally.columns if tally else [],
                "off_template_count": tally.off_template if tally else 0,
                "created_at": job.created_at,
                "updated_at": job.updated_at,
            }
        )
    return rows


async def _job_or_404(db: AsyncSession, job_id: int) -> Job:
    job = await db.scalar(
        select(Job).where(Job.id == job_id, jobs_register_base_clause())
    )
    if job is None:
        raise HTTPException(404, detail="Rekrutacja nie istnieje.")
    return job


def _status_clause(values: list[str]):
    """``open`` = wszystko poza zamkniętymi (klauzula listy ekranu), ``all`` = bez filtra."""
    if "all" in values:
        return None
    clauses = []
    for value in sorted(set(values)):
        if value == "open":
            clauses.append(jobs_open_only_clause())
        else:
            clauses.append(Job.status == JobStatus(value))
    return or_(*clauses)


def _may_include_closed(values: Optional[list[str]]) -> bool:
    return not values or bool({"all", "closed"} & set(values))


# ── Lista i szczegóły ────────────────────────────────────────────────────────


@router.get(
    "/recruitments", response_model=Page[RecruitmentOut], summary="Lista rekrutacji"
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_recruitments(
    request: Request,
    _caller: RecruitmentsRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 100,
    status: Optional[list[StatusFilter]] = Query(
        None,
        description=(
            "open (wszystko poza zamkniętymi) · closed · draft · published · all. "
            "Powtarzalny, łączony przez LUB; brak = wszystkie."
        ),
    ),
    priority: Optional[list[PriorityFilter]] = Query(
        None,
        description="p1 („P1 Pilne”) · p2 („Bez priorytetu”) · accepting. Powtarzalny.",
    ),
    client_id: Optional[list[_Id]] = Query(None),
    recruiter_id: Optional[list[_Id]] = Query(
        None,
        description=(
            "Osoby, które pracują nad rekrutacją (prowadzący, aktywne przypisanie, "
            "ręcznie dopisany współpracownik); propozycja automatu się nie liczy. "
            "Gdy filtr statusu dopuszcza zamknięte — także „Poprzedni rekruter”."
        ),
    ),
    delivery_lead_id: Optional[list[_Id]] = Query(None),
    q: Optional[str] = Query(
        None,
        max_length=200,
        description="Tytuł, numer, tytuł dla rekrutera, numer klienta, klient, technologia.",
    ),
    updated_since: Optional[datetime] = Query(
        None, description="Zmiana wiersza rekrutacji (nie ruch karty — patrz /moves)."
    ),
) -> dict:
    """Rekrutacje sortowane po id, z zespołem i liczbą osób w kolumnach Tablicy."""
    query = select(Job).where(jobs_register_base_clause())
    if status:
        clause = _status_clause(list(status))
        if clause is not None:
            query = query.where(clause)
    if priority:
        query = query.where(Job.priority.in_(priorities_for_levels(priority)))
    if client_id:
        query = query.where(Job.client_id.in_(client_id))
    if recruiter_id:
        query = query.where(
            jobs_worked_by_clause(
                list(recruiter_id), include_parked=_may_include_closed(status)
            )
        )
    if delivery_lead_id:
        query = query.where(Job.delivery_lead_id.in_(delivery_lead_id))
    if q and q.strip():
        query = query.where(jobs_search_clause(q))
    if updated_since is not None:
        query = query.where(Job.updated_at >= updated_since)
    total = (
        await db.execute(
            select(func.count()).select_from(query.with_only_columns(Job.id).subquery())
        )
    ).scalar() or 0
    jobs = list(
        (
            await db.execute(
                query.order_by(Job.id).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    items = await _recruitment_rows(db, jobs)
    return page_of(items, page=page, page_size=page_size, total=total)


@router.get(
    "/recruitments/{job_id}",
    response_model=RecruitmentDetailOut,
    summary="Rekrutacja",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_recruitment(
    request: Request,
    job_id: IdPath,
    caller: RecruitmentsRead,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pola listy, opis i wymagania, tryb pracy oraz budżet dla kandydata.

    Budżet to koszt: bez ``amounts:read`` pola kwot są ``null``,
    a ``costs_redacted = true``.
    """
    job = await _job_or_404(db, job_id)
    visibility = _visibility(caller)
    (row,) = await _recruitment_rows(db, [job])
    hiring_manager = None
    if job.hiring_manager_contact_id:
        hiring_manager = {
            "id": job.hiring_manager_contact_id,
            "name": await db.scalar(
                select(Contact.name).where(Contact.id == job.hiring_manager_contact_id)
            ),
        }
    return {
        **row,
        "description": job.description,
        "requirements": job.requirements,
        "must_skills": list(effective_skill_names(job, "must")),
        "nice_skills": list(effective_skill_names(job, "nice")),
        "critical_skills": list(effective_critical(job).labels),
        "seniority": _value(job.seniority),
        "work_mode": _value(job.work_mode),
        "remote_policy": _value(job.remote_policy),
        "onsite_days_per_week": job.onsite_days_per_week,
        "onsite_days_per_month": job.onsite_days_per_month,
        "location": job.location,
        "deadline_time": job.deadline_time,
        "industry": job.industry,
        "competence_category_id": job.competence_category_id,
        "hiring_manager": hiring_manager,
        "pipeline_template_id": job.pipeline_template_id,
        "amounts_redacted": visibility.amounts_redacted,
        "costs_redacted": visibility.costs_redacted,
        **job_budget(job, visibility=visibility),
    }


# ── Wymagania (Champion) ─────────────────────────────────────────────────────


class RequirementRowOut(BaseModel):
    words: list[str] = Field(description="Warianty słowa — wystarczy jedno.")
    level: str = Field(description="critical | must | nice")


class TalkItemOut(BaseModel):
    name: str
    level: str = Field(description="must | nice")
    min_years: Optional[int]
    note: str


class TalkChecksOut(BaseModel):
    skills: list[TalkItemOut] = Field(
        description="„Doświadczenie i umiejętności” — zdania do sprawdzenia w rozmowie."
    )
    domains: list[TalkItemOut]
    certifications: list[TalkItemOut]
    regulations: list[TalkItemOut]
    notes: str


class CriticalOut(BaseModel):
    effective: list[str] = Field(description="Krytyczne, na których działa bramka.")
    source: str = Field(description="dl | suggested | none")
    decided: bool = Field(description="Delivery Lead zdecydował (lista albo brak).")
    suggested: list[str]


class RequirementGroupOut(BaseModel):
    any_of: list[str]
    level: str = Field(description="must | nice | excluded | uncertain")


class ScreeningQuestionOut(BaseModel):
    id: str
    question: str
    ideal_answer: str
    deal_breaker: str


class RecruitmentRequirementsOut(BaseModel):
    job_id: int
    title: str
    has_champion_profile: bool
    role_name: Optional[str]
    seniority_min_years: Optional[int]
    language: Optional[str]
    work_mode: Optional[str]
    onsite_days_per_week: Optional[int]
    candidate_location_pref: Optional[str]
    start_date: Optional[str]
    contract_length: Optional[str]
    must_skills: list[str]
    nice_skills: list[str]
    critical: CriticalOut
    search_rows: list[RequirementRowOut] = Field(
        description="„Szukamy po tych słowach” — wiersze wymagań Championa."
    )
    requirements_reviewed: bool
    requirement_groups: list[RequirementGroupOut]
    talk_checks: TalkChecksOut = Field(
        description="„Rekruter sprawdza w rozmowie” — nie filtruje kandydatów."
    )
    stack_notes: str
    disqualifiers: list[str]
    requirements_text: Optional[str]
    project_about: str
    project_responsibilities: str
    screening_questions: list[ScreeningQuestionOut]
    amounts_redacted: bool
    costs_redacted: bool
    champion_rate_hourly: Money = Field(
        description="Stawka dla kandydata z Profilu Championa, PLN/h (koszt)."
    )
    champion_rate_raw: Optional[str] = Field(
        description="Stawka Championa tak, jak ją wpisano (koszt)."
    )


@router.get(
    "/recruitments/{job_id}/requirements",
    response_model=RecruitmentRequirementsOut,
    summary="Wymagania rekrutacji (Profil Championa)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_recruitment_requirements(
    request: Request,
    job_id: IdPath,
    caller: RecruitmentsRead,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Dwie listy wymagań: słowa do szukania i to, co rekruter sprawdza w rozmowie.

    Do tego krytyczne, pytania screeningowe i opis projektu z Profilu Championa.
    Odczyt niczego nie zmienia (powiadomienia o zmianie Championa zostają
    nieprzeczytane). Stawka Championa to koszt — tylko z ``amounts:read``.
    """
    job = await _job_or_404(db, job_id)
    return requirements_view(job, visibility=_visibility(caller))


# ── Tablica ──────────────────────────────────────────────────────────────────


class BoardCardOut(BaseModel):
    card_id: int = Field(description="Wiersz bieżącego etapu pary.")
    candidate: RefOut
    stage: str
    stage_def_id: Optional[int]
    process_id: Optional[int]
    process_status: Optional[str] = Field(description="open | closed | voided")
    process_state_version: int = Field(
        description="Wersja procesu — odsyłana przy przesunięciu karty."
    )
    entered_stage_at: datetime
    days_in_stage: Optional[int]
    added_to_job_at: Optional[datetime]
    added_to_job_by: Optional[RefOut]
    recruiter: Optional[RefOut] = Field(
        description="Właściciel procesu, a bez niego osoba, która dodała kandydata."
    )
    entry_source: Optional[str]
    reassign_from_job_id: Optional[int]
    claimed_by: Optional[RefOut]
    claim_until: Optional[datetime]
    next_action_owner: Optional[str] = Field(
        description="recruiter | client | candidate | delivery | none"
    )
    screening_done: bool
    scorecard_done: bool
    company_cv: Optional[bool]
    auto_cv_ready: bool
    qc_status: Optional[str]
    recommendation_card_status: Optional[str]
    interview_badge: Optional[dict] = Field(
        description="Etap rozmowy u klienta: kind, label, tone, at, steps, "
        "interview_event_id, tentative_interview_at — bez treści debriefu."
    )
    availability_status: Optional[str]
    rejection_reason_id: Optional[int]
    ended_by: Optional[str]
    warnings: list[str]
    amounts_redacted: bool
    costs_redacted: bool
    client_rate_value: Money = Field(description="Stawka do klienta (sprzedaż).")
    client_rate_unit: Optional[str]
    client_rate_currency: Optional[str]
    expected_rate_value: Money = Field(description="Stawka kandydata z ruchu (koszt).")
    expected_rate_unit: Optional[str]
    expected_rate_currency: Optional[str]
    budget_max_at_move: Money = Field(
        description="Budżet zamrożony przy ruchu (koszt)."
    )
    budget_exceeded: Optional[bool]


class BoardColumnOut(BaseModel):
    stage_def_id: Optional[int]
    stage: str
    name: Optional[str]
    order: Optional[int]
    category: str
    terminal_type: Optional[str]
    count: int
    cards: list[BoardCardOut]


class BoardOffTemplateOut(BaseModel):
    name: str
    count: int
    missing_stage_labels: list[str]
    cards: list[BoardCardOut]


class RecruitmentBoardOut(BaseModel):
    job_id: int
    columns: list[BoardColumnOut]
    off_template: Optional[BoardOffTemplateOut] = Field(
        description="Karty na etapach spoza szablonu rekrutacji (brak = żadnych)."
    )


def _ref(user_id: Optional[int], name: Optional[str]) -> Optional[dict]:
    return {"id": user_id, "name": name} if user_id is not None else None


def _card_out(card, *, process, client_rate, visibility: MoneyVisibility) -> dict:
    """Karta Tablicy (``CandidateStageResponse``) w kształcie v1 — wybrane pola."""
    name = " ".join(part for part in (card.name, card.lastname) if part).strip()
    qc = card.qc if isinstance(card.qc, dict) else {}
    recommendation = card.card if isinstance(card.card, dict) else {}
    costs = {key: getattr(card, key) for key in CARD_COST_FIELDS}
    return {
        "card_id": card.id,
        "candidate": {"id": card.candidate_id, "name": name or None},
        "stage": _value(card.stage),
        "stage_def_id": card.stage_def_id,
        "process_id": process.id if process is not None else None,
        "process_status": _value(process.status) if process is not None else None,
        "process_state_version": card.process_state_version or 0,
        "entered_stage_at": card.moved_at,
        "days_in_stage": card.days_in_stage,
        "added_to_job_at": card.added_to_job_at,
        "added_to_job_by": _ref(card.added_to_job_by_id, card.added_to_job_by_name),
        "recruiter": _ref(card.recruiter_id, card.recruiter_name),
        "entry_source": card.entry_source,
        "reassign_from_job_id": card.reassign_from_job_id,
        "claimed_by": _ref(card.claim_user_id, card.claim_user_name),
        "claim_until": card.claim_until,
        "next_action_owner": card.next_action_owner,
        "screening_done": card.screening_done,
        "scorecard_done": card.scorecard_done,
        "company_cv": card.company_cv,
        "auto_cv_ready": card.auto_cv_ready,
        "qc_status": qc.get("status"),
        "recommendation_card_status": recommendation.get("status"),
        "interview_badge": public_interview_badge(card.interview_badge),
        "availability_status": card.availability_status,
        "rejection_reason_id": card.rejection_reason_id,
        "ended_by": card.ended_by,
        "warnings": visible_card_warnings(card.warnings, show_costs=visibility.costs),
        **card_money(costs, client_rate=client_rate, visibility=visibility),
    }


@router.get(
    "/recruitments/{job_id}/board",
    response_model=RecruitmentBoardOut,
    summary="Tablica rekrutacji",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_recruitment_board(
    request: Request,
    job_id: IdPath,
    caller: RecruitmentsRead,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Kolumny szablonu z kartami osób — ta sama Tablica co na ekranie.

    Karta niesie imię i nazwisko kandydata, bez danych kontaktowych. Stawka
    do klienta (sprzedaż) z ``sales_amounts:read``; stawka kandydata
    z ruchu i budżet przy ruchu (koszt) tylko z ``amounts:read``.
    """
    job = await _job_or_404(db, job_id)
    visibility = _visibility(caller)
    view = await build_kanban_view(
        db,
        job,
        viewer=None,
        with_followups=False,
        with_employment=False,
        with_other_jobs=False,
    )
    off = view.off_template
    all_cards = [card for column in view.columns for card in column.items]
    if off is not None:
        all_cards.extend(off.items)
    processes = await _process_v4_cards(
        db, job_id=job.id, candidate_ids=[card.candidate_id for card in all_cards]
    )
    client_rates = await latest_client_rates(db, job.id) if visibility.sales else {}

    def cards(items) -> list[dict]:
        return [
            _card_out(
                card,
                process=processes.get(card.candidate_id),
                client_rate=client_rates.get(card.candidate_id),
                visibility=visibility,
            )
            for card in items
        ]

    return {
        "job_id": job.id,
        "columns": [
            {
                "stage_def_id": column.stage_def_id,
                "stage": _value(column.stage),
                "name": column.name,
                "order": column.order,
                "category": _value(column.category),
                "terminal_type": column.terminal_type,
                "count": column.count,
                "cards": cards(column.items),
            }
            for column in view.columns
        ],
        "off_template": (
            {
                "name": off.name,
                "count": off.count,
                "missing_stage_labels": list(off.missing_stage_labels),
                "cards": cards(off.items),
            }
            if off is not None
            else None
        ),
    }


# ── Historia ruchów i kolumny ────────────────────────────────────────────────


class MoveOut(BaseModel):
    id: int
    candidate: RefOut
    from_stage: Optional[str]
    from_stage_name: Optional[str]
    to_stage: Optional[str]
    to_stage_name: Optional[str]
    moved_by: Optional[RefOut]
    moved_at: datetime
    source: str = Field(description="nexus | traffit")
    rejection_reason: Optional[RefOut]
    ended_by: Optional[str] = Field(
        description="candidate | recruiter | delivery_lead | client"
    )


@router.get(
    "/recruitments/{job_id}/moves",
    response_model=Page[MoveOut],
    summary="Historia ruchów kart rekrutacji",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_recruitment_moves(
    request: Request,
    job_id: IdPath,
    _caller: RecruitmentsRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 100,
    candidate_id: Optional[int] = Query(
        None, ge=1, le=INT4_MAX, description="Ruchy jednej osoby w tej rekrutacji."
    ),
) -> dict:
    """Ruchy etapów od najnowszych, z poprzednim etapem osoby i powodem odrzucenia."""
    job = await _job_or_404(db, job_id)
    items, total = await job_moves_page(
        db, job.id, page=page, page_size=page_size, candidate_id=candidate_id
    )
    return page_of(items, page=page, page_size=page_size, total=total)


class StageOut(BaseModel):
    stage_def_id: Optional[int]
    stage: str
    name: Optional[str]
    order: Optional[int]
    category: str = Field(description="internal | external | terminal")
    is_terminal: bool
    terminal_type: Optional[str] = Field(description="hired | rejected | withdrawn")


class RecruitmentStagesOut(BaseModel):
    job_id: int
    template_id: Optional[int]
    template_name: Optional[str]
    stages: list[StageOut]


@router.get(
    "/recruitments/{job_id}/stages",
    response_model=RecruitmentStagesOut,
    summary="Kolumny Tablicy rekrutacji",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_recruitment_stages(
    request: Request,
    job_id: IdPath,
    _caller: RecruitmentsRead,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Definicje kolumn szablonu rekrutacji (bez szablonu — kolumny domyślne)."""
    job = await _job_or_404(db, job_id)
    template, stages = await stage_definitions(db, job)
    return {
        "job_id": job.id,
        "template_id": template.id if template is not None else None,
        "template_name": template.name if template is not None else None,
        "stages": stages,
    }
