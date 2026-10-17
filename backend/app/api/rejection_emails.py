"""HTTP surface for ScheduledRejectionEmail lifecycle management.

Endpoints:
  POST /api/rejection-emails/preview           — co wyjdzie, zanim ktoś odrzuci
  GET  /api/rejection-emails/{id}              — status + preview
  POST /api/rejection-emails/{id}/cancel       — cancel (pending only)
  GET  /api/candidates/{id}/rejection-emails   — timeline for a candidate

The FE uses these to power the "Cofnij" toast after rejection, the
candidate-detail timeline, and audit views.

AuthZ: cancel — osoba, która zaplanowała mail (od rundy 9 to ona jest
`recruiter_id`, bo mail wychodzi z jej skrzynki), oversight (admin / DL /
HoR) albo każdy, kto może ruszać kartą w tej rekrutacji (`/move`:
RecruiterPlus + `ensure_job_membership`). Zatrzymać pomyłkę ma móc zespół,
nie tylko jedna osoba (runda 9, R9-N11-1).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.api.recruitment_access import (
    RECRUITMENT_TRANSITION_ROLES,
    RecruitmentReadAccess,
    ensure_job_membership,
    user_has_rejection_email_oversight,
)
from app.core.database import get_db
from app.models.activity import Activity
from app.models.job import Job
from app.models.notification import Notification, NotificationType
from app.models.rejection_email import (
    RejectionEmailStatus,
    ScheduledRejectionEmail,
)
from app.models.user import User
from app.services import rejection_email_scheduler
from app.services.rejection_email_scheduler import send_in_progress

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


# ── Response schemas ────────────────────────────────────────────────────────


class OtherProcessEntry(BaseModel):
    job_id: int
    title: str


class RejectionEmailResponse(BaseModel):
    id: int
    candidate_id: int
    job_id: int
    candidate_stage_id: int
    recruiter_id: int
    to_email: str
    subject: str
    body_html: str
    other_processes: List[OtherProcessEntry]
    status: RejectionEmailStatus
    scheduled_at: datetime
    sent_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    cancelled_by: Optional[int]
    email_id: Optional[int]
    attempts: int
    last_error: Optional[str]
    created_at: datetime

    model_config = {"from_attributes": True}


def _to_response(row: ScheduledRejectionEmail) -> RejectionEmailResponse:
    others_raw = row.other_processes or []
    # Od 17.10.2026 `title` bywa `None` — rekrutacja bez nazwy dla kandydata.
    others = [
        OtherProcessEntry(job_id=int(o["job_id"]), title=str(o.get("title") or ""))
        for o in others_raw
        if isinstance(o, dict) and "job_id" in o
    ]
    return RejectionEmailResponse(
        id=row.id,
        candidate_id=row.candidate_id,
        job_id=row.job_id,
        candidate_stage_id=row.candidate_stage_id,
        recruiter_id=row.recruiter_id,
        to_email=row.to_email,
        subject=row.subject,
        body_html=row.body_html,
        other_processes=others,
        status=row.status,
        scheduled_at=row.scheduled_at,
        sent_at=row.sent_at,
        cancelled_at=row.cancelled_at,
        cancelled_by=row.cancelled_by,
        email_id=row.email_id,
        attempts=row.attempts,
        last_error=row.last_error,
        created_at=row.created_at,
    )


_DbId = Annotated[int, Field(gt=0, le=2_147_483_647)]


class RejectionEmailPreviewRequest(BaseModel):
    job_id: _DbId
    candidate_ids: List[_DbId] = Field(min_length=1, max_length=200)


class RejectionEmailPreviewOtherProcess(BaseModel):
    job_id: int
    # Nazwa w NEXUSIE — tylko do okna.
    title: str
    # Nazwa w mailu; `None` = bez nazwy („inna rekrutacja”).
    mail_title: Optional[str]
    # Kolumna Tablicy osoby w tamtej rekrutacji.
    column: str


class RejectionEmailPreviewPendingMail(BaseModel):
    """Mail odrzucenia, który do tej osoby jeszcze czeka (D3, 17.10.2026)."""

    id: int
    scheduled_at: datetime
    sender_name: str
    # Rekrutacje, o których już mówi — nazwy w NEXUSIE.
    job_titles: List[str]


class RejectionEmailPreviewPerson(BaseModel):
    candidate_id: int
    to_email: Optional[str]
    # Ten sam słownik co `rejection_email_status` z `POST /api/pipeline/move`.
    skip_reason: Optional[str]
    # `before_client` / `after_client` — treść „przed klientem” / „po kliencie”.
    text_kind: Optional[str] = None
    other_processes: List[RejectionEmailPreviewOtherProcess] = []
    pending_mail: Optional[RejectionEmailPreviewPendingMail] = None


class RejectionEmailPreviewSample(BaseModel):
    text_kind: str
    candidate_id: int
    subject: str
    body: str
    closing: str
    other_processes_text: Optional[str]


class RejectionEmailPreviewResponse(BaseModel):
    # Pierwsza osoba, do której mail wyjdzie: temat, część do poprawy (bez
    # zakończenia), zakończenie i dopisek o jej pozostałych rekrutacjach.
    subject: Optional[str]
    body: Optional[str]
    closing: Optional[str] = None
    other_processes_text: Optional[str] = None
    text_kind: Optional[str] = None
    # Nazwa rekrutacji w mailu nadal wygląda na kod zlecenia albo klienta.
    title_warning: bool = False
    people: List[RejectionEmailPreviewPerson]
    # Po jednej osobie każdego rodzaju treści (okno kilku osób).
    samples: List[RejectionEmailPreviewSample] = []
    # Wspólna treść dla pierwszej osoby z czekającym mailem (D3).
    merged: Optional[RejectionEmailPreviewSample] = None


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.post("/preview", response_model=RejectionEmailPreviewResponse)
async def preview_rejection_email(
    data: RejectionEmailPreviewRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> RejectionEmailPreviewResponse:
    """Podgląd maila odrzucenia w oknie odrzucenia (13.10.2026).

    Ten sam dostęp co `POST /api/pipeline/move` (rola + członkostwo w
    rekrutacji) i ta sama reguła kwalifikacji co planowanie wysyłki. Nic nie
    zapisuje; POST, bo lista osób przy odrzuceniu kilku naraz.
    """
    job = await db.get(Job, data.job_id)
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Job not found"
        )
    await ensure_job_membership(db, current_user, job.id)
    result = await rejection_email_scheduler.preview(
        db, job=job, candidate_ids=data.candidate_ids, sender=current_user
    )
    return RejectionEmailPreviewResponse(
        subject=result.subject,
        body=result.body,
        closing=result.closing,
        other_processes_text=result.other_processes_text,
        text_kind=result.text_kind,
        title_warning=result.title_warning,
        people=[
            RejectionEmailPreviewPerson(
                candidate_id=p.candidate_id,
                to_email=p.to_email,
                skip_reason=p.skip_reason,
                text_kind=p.text_kind,
                other_processes=[
                    RejectionEmailPreviewOtherProcess(
                        job_id=o.job_id,
                        title=o.title,
                        mail_title=o.mail_title,
                        column=o.column,
                    )
                    for o in p.other_processes
                ],
                pending_mail=(
                    RejectionEmailPreviewPendingMail(
                        id=p.pending_mail.id,
                        scheduled_at=p.pending_mail.scheduled_at,
                        sender_name=p.pending_mail.sender_name,
                        job_titles=list(p.pending_mail.job_titles),
                    )
                    if p.pending_mail is not None
                    else None
                ),
            )
            for p in result.people
        ],
        samples=[
            RejectionEmailPreviewSample(
                text_kind=s.text_kind,
                candidate_id=s.candidate_id,
                subject=s.subject,
                body=s.body,
                closing=s.closing,
                other_processes_text=s.other_processes_text,
            )
            for s in result.samples
        ],
        merged=(
            RejectionEmailPreviewSample(
                text_kind=result.merged.text_kind,
                candidate_id=result.merged.candidate_id,
                subject=result.merged.subject,
                body=result.merged.body,
                closing=result.merged.closing,
                other_processes_text=result.merged.other_processes_text,
            )
            if result.merged is not None
            else None
        ),
    )


@router.get("/{rejection_email_id}", response_model=RejectionEmailResponse)
async def get_rejection_email(
    rejection_email_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> RejectionEmailResponse:
    """Fetch a scheduled rejection email by id (for toast preview / timeline)."""
    row = await db.get(ScheduledRejectionEmail, rejection_email_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled rejection email not found",
        )
    # M4 PR-04 (audyt P1.14): treść maila (recipient/subject/body/last_error)
    # widzi właściciel wiersza albo oversight (admin/DL/HoR) — nie każdy
    # zalogowany operacyjny.
    if current_user.id != row.recruiter_id and not user_has_rejection_email_oversight(
        current_user
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Podgląd treści maila ma właściciel lub admin/DL/HoR.",
        )
    return _to_response(row)


async def _ensure_can_cancel(
    db: AsyncSession, user: User, row: ScheduledRejectionEmail
) -> None:
    """Planujący, oversight albo osoba z prawem ruchu w tej rekrutacji."""
    if user.id == row.recruiter_id or user_has_rejection_email_oversight(user):
        return
    if user.has_any_role(*RECRUITMENT_TRANSITION_ROLES):
        try:
            await ensure_job_membership(db, user, row.job_id)
        except HTTPException:
            pass
        else:
            return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=(
            "Wysyłkę anuluje osoba, która ją zaplanowała, albo ktoś z prawem "
            "ruchu w tej rekrutacji."
        ),
    )


@router.post("/{rejection_email_id}/cancel", response_model=RejectionEmailResponse)
async def cancel_rejection_email(
    rejection_email_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> RejectionEmailResponse:
    """Cancel a pending rejection email (undo the 15-minute countdown).

    Idempotent semantics: a row that's already `cancelled` returns 200 with
    the row unchanged; any other terminal state returns 409 because we
    cannot "un-send" an email.
    """
    # Blokada wiersza: pętla wysyłki trzyma ją do zatwierdzenia rezerwacji,
    # więc anulowanie widzi znacznik „wysyłka ruszyła” albo wiersz przed nią.
    row = await db.scalar(
        select(ScheduledRejectionEmail)
        .where(ScheduledRejectionEmail.id == rejection_email_id)
        .with_for_update()
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled rejection email not found",
        )

    await _ensure_can_cancel(db, current_user, row)

    if row.status == RejectionEmailStatus.cancelled:
        return _to_response(row)  # idempotent

    if row.status != RejectionEmailStatus.pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Cannot cancel a rejection email in status '{row.status.value}'. "
                "Only 'pending' rows can be cancelled."
            ),
        )
    # Runda 9 (R9-N10-10): wysyłka już ruszyła — „Anulowano” byłoby
    # nieprawdą, bo mail wychodzi (albo właśnie wyszedł).
    if send_in_progress(row):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Wysyłka tego maila już trwa — nie da się jej anulować. "
                "Sprawdź folder Wysłane w Outlooku."
            ),
        )

    row.status = RejectionEmailStatus.cancelled
    row.cancelled_at = datetime.now(timezone.utc)
    row.cancelled_by = current_user.id

    db.add(
        Activity(
            entity_type="candidate",
            entity_id=row.candidate_id,
            action="rejection_email_cancelled",
            user_id=current_user.id,
            details={
                "scheduled_rejection_email_id": row.id,
                "cancelled_by": current_user.id,
                "job_id": row.job_id,
            },
        )
    )
    db.add(
        Notification(
            user_id=row.recruiter_id,
            title="Anulowano email odrzucenia",
            message=(f"Zaplanowany email do {row.to_email} został anulowany."),
            link=f"/candidates/{row.candidate_id}",
            notification_type=NotificationType.rejection_email_cancelled,
            related_entity_type="scheduled_rejection_email",
            related_entity_id=row.id,
        )
    )

    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.get(
    "/by-candidate/{candidate_id}",
    response_model=List[RejectionEmailResponse],
)
async def list_for_candidate(
    candidate_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
) -> List[RejectionEmailResponse]:
    """List all rejection emails scheduled for a candidate (timeline view).

    Ordered newest first so the FE can show the latest status at the top
    without sorting client-side.
    """
    rows = (
        (
            await db.execute(
                select(ScheduledRejectionEmail)
                .where(ScheduledRejectionEmail.candidate_id == candidate_id)
                .order_by(ScheduledRejectionEmail.id.desc())
            )
        )
        .scalars()
        .all()
    )
    # M4 PR-04: timeline pokazuje statusy każdemu operacyjnemu, ale treść
    # (body_html) i diagnostykę (last_error) tylko ownerowi/oversight.
    can_read_all = user_has_rejection_email_oversight(current_user)
    out: List[RejectionEmailResponse] = []
    for r in rows:
        resp = _to_response(r)
        if not can_read_all and current_user.id != r.recruiter_id:
            resp = resp.model_copy(update={"body_html": "", "last_error": None})
        out.append(resp)
    return out
