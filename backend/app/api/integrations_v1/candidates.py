"""Kandydaci w API v1: lista, profil, pliki CV, notatki i screening.

Scope'y: ``candidates:read`` (profil bez kontaktu), ``candidates:contact``
(e-mail, telefon, LinkedIn, dane firmy — pola profilu), ``candidates:cv``
(pliki i tekst CV), ``notes:read`` (notatki, screening, karta rekomendacji).
Oczekiwania stawkowe kandydata to koszt — tylko z ``amounts:read``; notatki
ze stawką do klienta (sprzedaż) — od ``sales_amounts:read``.

Zapytania i projekcje: ``services/integration_candidate_reads``. Pobranie
pliku zapisuje ślad w ``candidate_audit`` (jak pobranie na ekranie) — bez
osoby, ``details.via`` niesie stempel konta serwisowego. Pliki, tekst CV
i notatki uznane w kwarantannie tożsamości za cudze nie wychodzą.

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

from datetime import date, datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import hidden_send_note_ids, note_content_hidden
from app.api.candidates import _candidate_document_bytes
from app.api.integrations_v1.common import (
    INT4_MAX,
    AmountLevel,
    CandidatesCv,
    CandidatesRead,
    IdPath,
    IntegrationRoute,
    Money,
    NotesRead,
    Page,
    PageQuery,
    PageSizeQuery,
    amount_level,
    page_of,
    principal_rate_key,
    read_rate_limit,
    sees_candidate_contact,
)
from app.api.notes import _enriched_select
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.core.rate_limit import limiter
from app.models.candidate import AvailabilityStatus
from app.models.job import Job
from app.models.note import Note
from app.services import candidate_audit, note_kinds
from app.services import integration_candidate_reads as reads

router = APIRouter(route_class=IntegrationRoute)

_CANDIDATE_404 = "Kandydat nie istnieje."


# ── Lista ────────────────────────────────────────────────────────────────────


class CandidateListItemOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    city: Optional[str]
    country: Optional[str]
    region: Optional[str]
    competence_category_id: Optional[int]
    status: str
    availability_status: str
    availability_date: Optional[date]
    added_to_base_at: Optional[datetime]
    added_to_base_exact: bool
    created_at: datetime
    updated_at: datetime


@router.get(
    "/candidates",
    response_model=Page[CandidateListItemOut],
    summary="Lista kandydatów",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_candidates(
    request: Request,
    caller: CandidatesRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 200,
    q: Optional[str] = Query(
        None,
        max_length=200,
        description=(
            "Imię i/lub nazwisko (każde słowo w imieniu albo nazwisku, bez "
            "polskich znaków). Fraza z „@” = dokładny e-mail — tylko z "
            "``candidates:contact``."
        ),
    ),
    updated_since: Optional[datetime] = Query(None),
    ids: Optional[str] = Query(
        None, max_length=2400, description="Id po przecinku, najwyżej 200."
    ),
    competence_category_id: Optional[int] = Query(None, ge=1, le=INT4_MAX),
    availability: Optional[list[AvailabilityStatus]] = Query(None),
    city: Optional[str] = Query(None, max_length=120),
) -> dict:
    """Kandydaci sortowani po id, bez danych kontaktowych i kwot."""
    phrase = (q or "").strip()
    email: Optional[str] = None
    name: Optional[str] = None
    if phrase and reads.looks_like_email(phrase):
        if not sees_candidate_contact(caller):
            # E-mail nie może nawet potwierdzić, że osoba jest w bazie.
            raise HTTPException(
                403,
                detail={
                    "error": "insufficient_scope",
                    "message": "Szukanie po e-mailu wymaga scope'u candidates:contact.",
                    "missing": ["candidates:contact"],
                },
            )
        email = phrase
    elif phrase:
        name = phrase
    try:
        id_list = reads.parse_ids(ids)
    except reads.InvalidIds as exc:
        raise HTTPException(
            422, detail={"error": "validation_error", "message": str(exc)}
        ) from exc
    filters = reads.CandidateListFilters(
        name=name,
        email=email,
        updated_since=updated_since,
        ids=tuple(id_list),
        competence_category_id=competence_category_id,
        availability=tuple(availability or ()),
        city=city,
    )
    items, total = await reads.list_candidates_page(
        db, filters, page=page, page_size=page_size
    )
    return page_of(items, page=page, page_size=page_size, total=total)


# ── Profil ───────────────────────────────────────────────────────────────────


class CompetenceCategoryOut(BaseModel):
    id: int
    name: str


class SkillOut(BaseModel):
    name: str
    level: Optional[str]
    years: Optional[float]


class WorkPreferencesOut(BaseModel):
    work_modes: list[str]
    contract_types: list[str]
    max_onsite_days_per_week: Optional[int]
    b2b_willingness: Optional[str]
    work_time_preference: Optional[str]


class EmploymentClientOut(BaseModel):
    client_id: Optional[int]
    client_name: Optional[str]
    contract_id: Optional[int]
    phase: str
    order_end_date: Optional[date]
    starts_on: Optional[date]
    delivery_lead_name: Optional[str]


class EmploymentMarkerOut(BaseModel):
    """Znacznik „Pracuje u nas” (``services/employment_marker``)."""

    phase: str
    source: str
    clients: list[EmploymentClientOut]


class CandidateRecruitmentOut(BaseModel):
    job_id: int
    job_title: str
    client_id: Optional[int]
    client_name: Optional[str]
    stage: str
    in_progress: bool
    moved_at: Optional[datetime]


class CandidateOut(BaseModel):
    id: int
    first_name: str
    last_name: str
    status: str
    city: Optional[str]
    country: Optional[str]
    region: Optional[str]
    location: Optional[str]
    competence_category: Optional[CompetenceCategoryOut]
    skills: list[SkillOut]
    years_it_experience: Optional[int]
    availability_status: str
    availability_date: Optional[date]
    notice_period: Optional[int]
    notice_period_unit: Optional[str]
    work_preferences: WorkPreferencesOut
    added_to_base_at: Optional[datetime]
    added_to_base_exact: bool
    employment_marker: Optional[EmploymentMarkerOut]
    active_recruitments: list[CandidateRecruitmentOut]
    contact_redacted: bool
    email: Optional[str]
    phone: Optional[str]
    linkedin: Optional[str]
    nip: Optional[str]
    regon: Optional[str]
    legal_name: Optional[str]
    costs_redacted: bool
    rate_from_hourly: Money
    rate_from_at: Optional[datetime]
    rate_latest_hourly: Money
    rate_latest_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


def _marker_out(marker: Any) -> Optional[EmploymentMarkerOut]:
    if marker is None:
        return None
    return EmploymentMarkerOut(
        phase=marker.phase,
        source=marker.source,
        clients=[
            EmploymentClientOut(
                client_id=client.client_id,
                client_name=client.client_name,
                contract_id=client.contract_id,
                phase=client.phase,
                order_end_date=client.order_end_date,
                starts_on=client.starts_on,
                delivery_lead_name=client.delivery_lead_name,
            )
            for client in marker.clients
        ],
    )


@router.get(
    "/candidates/{candidate_id}",
    response_model=CandidateOut,
    summary="Profil kandydata",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_candidate(
    request: Request,
    candidate_id: IdPath,
    caller: CandidatesRead,
    db: AsyncSession = Depends(get_db),
) -> CandidateOut:
    """Profil kandydata. Kontakt tylko z ``candidates:contact`` (inaczej
    ``null`` i ``contact_redacted``), stawki kandydata tylko z
    ``amounts:read`` (inaczej ``null`` i ``costs_redacted``)."""
    candidate = await reads.load_candidate(db, candidate_id)
    if candidate is None:
        raise HTTPException(404, detail=_CANDIDATE_404)
    category = candidate.competence_category_ref
    return CandidateOut(
        id=candidate.id,
        first_name=candidate.name,
        last_name=candidate.lastname,
        status=reads.enum_value(candidate.status),
        city=candidate.city,
        country=candidate.country,
        region=candidate.region,
        location=candidate.location,
        competence_category=(
            CompetenceCategoryOut(id=category.id, name=category.name_pl)
            if category is not None
            else None
        ),
        skills=[SkillOut(**skill) for skill in reads.skills_out(candidate.skills)],
        years_it_experience=candidate.years_it_experience,
        availability_status=reads.enum_value(candidate.availability_status),
        availability_date=candidate.availability_date,
        notice_period=candidate.notice_period,
        notice_period_unit=candidate.notice_period_unit,
        work_preferences=WorkPreferencesOut(**reads.work_preferences(candidate)),
        **reads.added_to_base(candidate),
        employment_marker=_marker_out(await reads.employment_marker(db, candidate.id)),
        active_recruitments=[
            CandidateRecruitmentOut(**row)
            for row in await reads.active_recruitments(db, candidate.id)
        ],
        **reads.contact_fields(candidate, visible=sees_candidate_contact(caller)),
        **reads.profile_rates(
            candidate, show_costs=amount_level(caller) is AmountLevel.all
        ),
        created_at=candidate.created_at,
        updated_at=candidate.updated_at,
    )


# ── Pliki i tekst CV ─────────────────────────────────────────────────────────


class CandidateDocumentOut(BaseModel):
    id: int
    kind: str
    file_name: str
    mime_type: Optional[str]
    size_bytes: Optional[int]
    is_primary: bool
    is_outdated: bool
    uploaded_at: Optional[datetime]
    source: Optional[str]
    created_at: datetime


class CandidateDocumentListOut(BaseModel):
    candidate_id: int
    items: list[CandidateDocumentOut]


@router.get(
    "/candidates/{candidate_id}/documents",
    response_model=CandidateDocumentListOut,
    summary="Pliki kandydata",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_candidate_documents(
    request: Request,
    candidate_id: IdPath,
    _caller: CandidatesCv,
    db: AsyncSession = Depends(get_db),
) -> CandidateDocumentListOut:
    """Pliki osoby: główne CV pierwsze, potem najnowsze. Bez plików usuniętych
    z profilu i bez plików uznanych za CV innej osoby."""
    if not await reads.candidate_exists(db, candidate_id):
        raise HTTPException(404, detail=_CANDIDATE_404)
    documents = await reads.list_documents(db, candidate_id)
    return CandidateDocumentListOut(
        candidate_id=candidate_id,
        items=[
            CandidateDocumentOut(
                id=doc.id,
                kind=reads.enum_value(doc.document_kind),
                file_name=doc.filename,
                mime_type=doc.content_type,
                size_bytes=doc.size_bytes,
                is_primary=bool(doc.is_primary),
                is_outdated=doc.outdated_at is not None,
                uploaded_at=doc.uploaded_at,
                source=doc.external_source,
                created_at=doc.created_at,
            )
            for doc in documents
        ],
    )


@router.get(
    "/candidates/{candidate_id}/documents/{document_id}/file",
    summary="Pobranie pliku kandydata",
    response_class=Response,
    responses={200: {"content": {"application/octet-stream": {}}}},
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def download_candidate_document(
    request: Request,
    candidate_id: IdPath,
    document_id: IdPath,
    _caller: CandidatesCv,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Bajty pliku (zawsze ``attachment``). Każde pobranie zostawia ślad
    ``document_downloaded`` w dzienniku kandydata — jak pobranie na ekranie."""
    document = await reads.load_document(db, candidate_id, document_id)
    if document is None:
        raise HTTPException(404, detail="Plik nie istnieje.")
    content = await _candidate_document_bytes(db, document)
    if not content:
        raise HTTPException(404, detail="Treść pliku jest niedostępna.")
    # Ślad dopiero przy oddanych bajtach. Osoby nie ma — ``details.via``
    # (``integration:<konto>``) dopisuje nasłuch sesji klucza.
    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.DOCUMENT_DOWNLOADED,
        user_id=None,
        entity_id=candidate_id,
        details={"doc_id": document.id, "disposition": "attachment"},
    )
    await db.commit()
    filename = document.filename or f"document-{document.id}"
    return Response(
        content=content,
        media_type=document.content_type or "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(filename, "attachment"),
            "Content-Length": str(len(content)),
        },
    )


class CandidateCvTextOut(BaseModel):
    candidate_id: int
    quarantined: bool
    raw_cv_text: Optional[str]
    cv_extracted_data: Optional[dict[str, Any]]
    cv_language: Optional[str]
    cv_parsed_at: Optional[datetime]
    source_document_id: Optional[int]


@router.get(
    "/candidates/{candidate_id}/cv-text",
    response_model=CandidateCvTextOut,
    summary="Tekst i odczyt CV kandydata",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_candidate_cv_text(
    request: Request,
    candidate_id: IdPath,
    _caller: CandidatesCv,
    db: AsyncSession = Depends(get_db),
) -> CandidateCvTextOut:
    """Tekst bieżącego CV i jego odczyt (bez kluczy spoza CV). Gdy źródło
    tekstu jest w kwarantannie tożsamości — ``quarantined`` i pola ``null``."""
    row = await reads.load_cv_text(db, candidate_id)
    if row is None:
        raise HTTPException(404, detail=_CANDIDATE_404)
    raw_text, extracted, language, parsed_at = row
    if await reads.cv_text_quarantined(db, candidate_id, extracted):
        return CandidateCvTextOut(
            candidate_id=candidate_id,
            quarantined=True,
            raw_cv_text=None,
            cv_extracted_data=None,
            cv_language=None,
            cv_parsed_at=None,
            source_document_id=None,
        )
    return CandidateCvTextOut(
        candidate_id=candidate_id,
        quarantined=False,
        raw_cv_text=raw_text,
        cv_extracted_data=reads.public_cv_extracted(extracted),
        cv_language=language,
        cv_parsed_at=parsed_at,
        source_document_id=reads.projected_document_id(extracted),
    )


# ── Notatki ──────────────────────────────────────────────────────────────────


class CandidateNoteOut(BaseModel):
    id: int
    kind: Optional[str]
    group: str
    note_type: str
    content: Optional[str]
    content_hidden: bool
    author_name: Optional[str]
    author_kind: str
    job_id: Optional[int]
    job_title: Optional[str]
    reply_to: Optional[int]
    pinned: bool
    pinned_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]


@router.get(
    "/candidates/{candidate_id}/notes",
    response_model=Page[CandidateNoteOut],
    summary="Notatki kandydata",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_candidate_notes(
    request: Request,
    candidate_id: IdPath,
    caller: NotesRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 200,
    job_id: Optional[int] = Query(None, ge=1, le=INT4_MAX),
) -> dict:
    """Notatki i odpowiedzi chronologicznie (``reply_to`` = notatka główna).

    Notatka ze stawką do klienta (wpis Delivery Leada, notatka z wysyłki CV)
    bez ``sales_amounts:read`` ma ``content = null`` i ``content_hidden`` —
    ta sama reguła co na ekranie dla roli bez tej stawki.
    """
    if not await reads.candidate_exists(db, candidate_id):
        raise HTTPException(404, detail=_CANDIDATE_404)
    conditions = [Note.candidate_id == candidate_id, *reads.eligible_note_conditions()]
    if job_id is not None:
        conditions.append(Note.job_id == job_id)
    total = (
        await db.scalar(select(func.count()).select_from(Note).where(*conditions))
    ) or 0
    rows = (
        await db.execute(
            _enriched_select()
            .add_columns(Note.source_ref)
            .where(*conditions)
            .order_by(Note.created_at, Note.id)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    sees_sales = amount_level(caller) >= AmountLevel.sales
    send_ids = (
        frozenset()
        if sees_sales
        else await hidden_send_note_ids(db, None, [row[0].id for row in rows])
    )
    items = []
    for note, author_name, job_title, _pinned_by, source_ref in rows:
        hidden = not sees_sales and note_content_hidden(
            None,
            kind=note.kind,
            author_id=note.author_id,
            send_note=note.id in send_ids,
        )
        label, author_kind = reads.note_author(
            author_name, source_ref=source_ref, external_source=note.external_source
        )
        items.append(
            CandidateNoteOut(
                id=note.id,
                kind=note.kind,
                group=note_kinds.group_of(note.kind, note.external_source),
                note_type=reads.enum_value(note.note_type),
                content=None if hidden else note.content,
                content_hidden=hidden,
                author_name=label,
                author_kind=author_kind,
                job_id=note.job_id,
                job_title=job_title,
                reply_to=note.parent_note_id,
                pinned=note.pinned_at is not None,
                pinned_at=note.pinned_at,
                created_at=note.created_at,
                updated_at=note.updated_at,
            )
        )
    return page_of(items, page=page, page_size=page_size, total=int(total))


# ── Screening i karta rekomendacji ───────────────────────────────────────────


class ScreeningAnswerOut(BaseModel):
    question_id: str
    question_text: Optional[str]
    response: str
    deal_breaker_hit: bool
    skipped: bool
    origin: Optional[str]


class ExperienceCheckOut(BaseModel):
    kind: Optional[str]
    name: str
    status: Optional[str]
    note: str


class ScreeningSheetOut(BaseModel):
    answers: list[ScreeningAnswerOut]
    experience_checks: list[ExperienceCheckOut]
    overall_fit: Optional[str]
    notes: Optional[str]
    internal_note: Optional[str]
    answered_at: Optional[datetime]
    answered_by_name: Optional[str]


class CardFieldOut(BaseModel):
    key: str
    label: str
    text: str
    source: Optional[str]
    at: Optional[datetime]


class CardCompletenessOut(BaseModel):
    status: str
    filled: int
    total: int
    missing: list[str]


class RecommendationCardOut(BaseModel):
    fields: list[CardFieldOut]
    completeness: CardCompletenessOut
    updated_at: Optional[datetime]


class PairRateOut(BaseModel):
    """Stawka kandydata w tej rekrutacji, PLN netto za godzinę (B2B)."""

    amount_hourly: Money
    raw: Optional[str]
    at: Optional[datetime]
    source: Optional[str]


class CandidateScreeningOut(BaseModel):
    job_id: int
    candidate_id: int
    stage_id: int
    stage: str
    screening: Optional[ScreeningSheetOut]
    recommendation_card: Optional[RecommendationCardOut]
    costs_redacted: bool
    candidate_rate: Optional[PairRateOut]


@router.get(
    "/recruitments/{job_id}/candidates/{candidate_id}/screening",
    response_model=CandidateScreeningOut,
    summary="Screening i karta rekomendacji osoby w rekrutacji",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_candidate_screening(
    request: Request,
    job_id: IdPath,
    candidate_id: IdPath,
    caller: NotesRead,
    db: AsyncSession = Depends(get_db),
) -> CandidateScreeningOut:
    """Odpowiedzi screeningu pary (jak ``GET /pipeline/stages/{id}/screening``)
    i karta rekomendacji bieżącej próby procesu. Narodowość z karty nie
    wychodzi nigdy; stawka kandydata (pole „Stawka” karty i ``candidate_rate``
    — stawka podana w tej rekrutacji) — tylko z ``amounts:read``."""
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, detail="Rekrutacja nie istnieje.")
    if not await reads.candidate_exists(db, candidate_id):
        raise HTTPException(404, detail=_CANDIDATE_404)
    stage = await reads.latest_pair_stage(db, candidate_id=candidate_id, job_id=job_id)
    if stage is None:
        raise HTTPException(404, detail="Kandydata nie ma w tej rekrutacji.")
    show_costs = amount_level(caller) is AmountLevel.all
    sheet = await reads.screening_sheet(db, stage, job)
    card = await reads.recommendation_card(
        db, candidate_id=candidate_id, job_id=job_id, show_costs=show_costs
    )
    rate = (
        await reads.pair_candidate_rate(db, candidate_id=candidate_id, job_id=job_id)
        if show_costs
        else None
    )
    return CandidateScreeningOut(
        job_id=job_id,
        candidate_id=candidate_id,
        stage_id=stage.id,
        stage=reads.enum_value(stage.stage),
        screening=ScreeningSheetOut(**sheet) if sheet else None,
        recommendation_card=RecommendationCardOut(**card) if card else None,
        costs_redacted=not show_costs,
        candidate_rate=(
            PairRateOut(
                amount_hourly=rate["amount"],
                raw=rate.get("raw"),
                at=rate.get("at"),
                source=rate.get("source"),
            )
            if rate
            else None
        ),
    )
