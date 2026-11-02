"""Panel klienta pod linkiem z CV: publiczne trasy bez logowania.

Reguły: ``docs/claude/klienci/panel-klienta-pod-linkiem.md``. Odpowiedzi składa
``services/client_panel.py`` z jawnych list pól. Bez
``from __future__ import annotations``: slowapi #579.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.http_headers import content_disposition, safe_document_disposition
from app.core.rate_limit import client_ip_key, limiter
from app.models.user import User
from app.services import client_panel as panel_service
from app.services import client_panel_requests as requests_service
from app.services import interview_slots
from app.services.interview_slot_requests import (
    SlotsAlreadyOpen,
    after_slot_request_commit,
    create_slot_request_for_pair,
)

READ_LIMIT = "60/minute"
WRITE_LIMIT = "5/minute"
# Każda zamiana na PDF to LibreOffice na serwerze (jak `cv_pdf_preview`).
PDF_LIMIT = "20/minute"
# Przeglądanie panelu wysyła kilka zdarzeń na minutę.
EVENT_LIMIT = "60/minute"

_NOINDEX_HEADERS = {
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _noindex(response: Response) -> None:
    response.headers.update(_NOINDEX_HEADERS)


router = APIRouter(dependencies=[Depends(_noindex)])


class AuthorIn(BaseModel):
    author_name: str = Field(..., min_length=1, max_length=120)
    author_email: EmailStr
    honeypot: Optional[str] = Field(None, max_length=200)

    @field_validator("author_name")
    @classmethod
    def _plain_name(cls, value: str) -> str:
        # Imię trafia do dzwonka i maila DL-a: bez znaczników i adresów.
        cleaned = " ".join(value.split())
        if not cleaned or any(mark in cleaned for mark in ("<", ">", "://")):
            raise ValueError("Podaj samo imię i nazwisko.")
        return cleaned


class QuestionIn(AuthorIn):
    body: str = Field(..., min_length=1, max_length=2000)


class SlotIn(BaseModel):
    start: datetime
    end: Optional[datetime] = None
    window_end: Optional[datetime] = None


class InterviewIn(AuthorIn):
    duration_minutes: int = Field(60, ge=15, le=480)
    slots: list[SlotIn] = Field(..., min_length=1, max_length=interview_slots.MAX_SLOTS)
    interviewers: Optional[str] = Field(None, max_length=300)
    prep_note: Optional[str] = Field(None, max_length=600)


class NotFitIn(AuthorIn):
    reasons: list[str] = Field(default_factory=list, max_length=10)
    body: Optional[str] = Field(None, max_length=2000)

    @field_validator("reasons")
    @classmethod
    def _short_reasons(cls, value: list[str]) -> list[str]:
        cleaned = [" ".join(item.split())[:120] for item in value]
        return [item for item in cleaned if item]


class EventIn(BaseModel):
    public_id: Optional[str] = None
    action: str = ""
    detail: Optional[str] = None


def _ignored_write() -> dict:
    """Odpowiedź dla wypełnionego pola-pułapki: wygląda jak zapis, nic nie zapisuje."""
    return {
        "id": 0,
        "kind": "question",
        "author": None,
        "at": None,
        "body": None,
        "answer": None,
        "answered_at": None,
    }


@router.get("/{token}")
@limiter.limit(READ_LIMIT)
async def get_panel(
    token: str,
    request: Request,
    c: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Panel rekrutacji: wymagania i lista osób, którym wysłano CV."""
    panel, job = await panel_service.load_public_panel(db, token)
    view = await panel_service.public_panel_view(db, panel, job, c)
    await panel_service.log_view(
        db, panel_id=panel.id, action="open", ip=client_ip_key(request)
    )
    await db.commit()
    return view


@router.get("/{token}/candidates/{public_id}")
@limiter.limit(READ_LIMIT)
async def get_candidate(
    token: str,
    public_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Jedna osoba: dowody z CV, warunki, pliki, pytania i stan rozmowy."""
    panel, job = await panel_service.load_public_panel(db, token)
    visible = await panel_service.visible_person(db, panel, job, public_id)
    view = await panel_service.public_candidate_view(db, panel, job, token, visible)
    await panel_service.log_view(
        db,
        panel_id=panel.id,
        action="candidate",
        ip=client_ip_key(request),
        candidate_id=visible.candidate_id,
    )
    await db.commit()
    return view


@router.get("/{token}/candidates/{public_id}/cv.pdf")
@limiter.limit(PDF_LIMIT)
async def get_candidate_cv(
    token: str,
    public_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """CV osoby jako PDF, ten sam dokument co plik wysłany do klienta."""
    panel, job = await panel_service.load_public_panel(db, token)
    visible = await panel_service.visible_person(db, panel, job, public_id)
    # Podgląd wczytuje ten plik sam, więc pobranie zgłasza przycisk (`/events`).
    pdf, filename = await panel_service.candidate_pdf(db, visible)
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            **_NOINDEX_HEADERS,
            "Content-Disposition": content_disposition(filename, "inline"),
        },
    )


@router.get("/{token}/candidates/{public_id}/files/{document_id}")
@limiter.limit(PDF_LIMIT)
async def get_candidate_file(
    token: str,
    public_id: str,
    document_id: int,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Plik udostępniony w panelu."""
    panel, job = await panel_service.load_public_panel(db, token)
    visible = await panel_service.visible_person(db, panel, job, public_id)
    content, document = await panel_service.shared_document_bytes(
        db, visible, document_id
    )
    media_type = document.content_type or "application/octet-stream"
    filename = document.filename
    await panel_service.log_view(
        db,
        panel_id=panel.id,
        action="file",
        ip=client_ip_key(request),
        candidate_id=visible.candidate_id,
        detail=filename,
    )
    await db.commit()
    return Response(
        content=content,
        media_type=media_type,
        headers={
            **_NOINDEX_HEADERS,
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": content_disposition(
                filename, safe_document_disposition(media_type, "inline")
            ),
        },
    )


@router.post(
    "/{token}/candidates/{public_id}/questions",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(WRITE_LIMIT)
async def post_question(
    token: str,
    public_id: str,
    body: QuestionIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Pytanie o osobę; odpowiada Delivery Lead."""
    panel, job = await panel_service.load_public_panel(db, token)
    await requests_service.guard_write(db, panel)
    visible = await panel_service.visible_person(db, panel, job, public_id)
    if body.honeypot:
        return _ignored_write()
    row = await requests_service.create_request(
        db,
        panel=panel,
        job=job,
        kind="question",
        author_name=body.author_name,
        author_email=str(body.author_email),
        body=body.body,
        candidate_id=visible.candidate_id,
    )
    await db.commit()
    return panel_service.thread_item(row)


def _slot_note(body: InterviewIn) -> str:
    parts = [f"Z panelu klienta: {body.author_name}"]
    if body.interviewers:
        parts.append(f"Rozmawiają: {body.interviewers.strip()}")
    if body.prep_note:
        parts.append(f"Do przygotowania: {body.prep_note.strip()}")
    return " · ".join(parts)[:1000]


@router.post(
    "/{token}/candidates/{public_id}/interview",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(WRITE_LIMIT)
async def post_interview(
    token: str,
    public_id: str,
    body: InterviewIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Prośba o rozmowę z terminami; termin z osobą ustala rekruter."""
    panel, job = await panel_service.load_public_panel(db, token)
    await requests_service.guard_write(db, panel)
    visible = await panel_service.visible_person(db, panel, job, public_id)
    if body.honeypot:
        return {"interview": panel_service.interview_block(None)}
    slots = interview_slots.normalize_slots(
        [slot.model_dump() for slot in body.slots],
        duration_minutes=body.duration_minutes,
        now=datetime.now(timezone.utc),
    )
    actor = await db.get(User, job.delivery_lead_id) if job.delivery_lead_id else None
    if actor is not None and not actor.is_active:
        actor = None
    try:
        created = await create_slot_request_for_pair(
            db,
            job=job,
            candidate_id=visible.candidate_id,
            slots=slots,
            duration_minutes=body.duration_minutes,
            note=_slot_note(body),
            actor=actor,
        )
    except SlotsAlreadyOpen as exc:
        raise HTTPException(
            status_code=409,
            detail="Dla tej osoby czekają już terminy do potwierdzenia. Jeśli trzeba je zmienić, napisz pytanie.",
        ) from exc
    await requests_service.create_request(
        db,
        panel=panel,
        job=job,
        kind="interview",
        author_name=body.author_name,
        author_email=str(body.author_email),
        body=body.prep_note,
        candidate_id=visible.candidate_id,
        slot_request_id=created.request.id,
    )
    await db.commit()
    await db.refresh(created.request)
    state = panel_service.interview_block(created.request)
    await after_slot_request_commit(db, created)
    return {"interview": state}


@router.post(
    "/{token}/candidates/{public_id}/not-fit",
    status_code=status.HTTP_201_CREATED,
)
@limiter.limit(WRITE_LIMIT)
async def post_not_fit(
    token: str,
    public_id: str,
    body: NotFitIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Informacja, że osoba nie pasuje; decyzja zostaje u Delivery Leada."""
    panel, job = await panel_service.load_public_panel(db, token)
    await requests_service.guard_write(db, panel)
    visible = await panel_service.visible_person(db, panel, job, public_id)
    if body.honeypot:
        return _ignored_write()
    row = await requests_service.create_request(
        db,
        panel=panel,
        job=job,
        kind="not_fit",
        author_name=body.author_name,
        author_email=str(body.author_email),
        body=body.body,
        reasons=body.reasons,
        candidate_id=visible.candidate_id,
    )
    await db.commit()
    return panel_service.thread_item(row)


@router.post("/{token}/requirements-change", status_code=status.HTTP_201_CREATED)
@limiter.limit(WRITE_LIMIT)
async def post_requirements_change(
    token: str,
    body: QuestionIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zmiana wymagań rekrutacji zgłoszona przez klienta."""
    panel, job = await panel_service.load_public_panel(db, token)
    await requests_service.guard_write(db, panel)
    if body.honeypot:
        return _ignored_write()
    row = await requests_service.create_request(
        db,
        panel=panel,
        job=job,
        kind="requirements_change",
        author_name=body.author_name,
        author_email=str(body.author_email),
        body=body.body,
    )
    await db.commit()
    return panel_service.thread_item(row)


@router.post("/{token}/events", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(EVENT_LIMIT)
async def post_event(
    token: str,
    body: EventIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Zdarzenie przeglądania panelu."""
    try:
        panel, job = await panel_service.load_public_panel(db, token)
        candidate_id = None
        if body.public_id:
            rows = await panel_service.candidate_rows(db, panel.id)
            candidate_id = next(
                (c for c, r in rows.items() if r.public_id == body.public_id), None
            )
        await panel_service.log_view(
            db,
            panel_id=panel.id,
            action=body.action,
            ip=client_ip_key(request),
            candidate_id=candidate_id,
            detail=body.detail,
        )
        await db.commit()
    except HTTPException:
        # Nieważny link dostaje tę samą odpowiedź: zdarzenie niczego nie zmienia.
        pass
    return Response(status_code=status.HTTP_204_NO_CONTENT, headers=_NOINDEX_HEADERS)
