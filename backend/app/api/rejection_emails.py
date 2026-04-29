"""HTTP surface for ScheduledRejectionEmail lifecycle management.

Three endpoints:
  GET  /api/rejection-emails/{id}              — status + preview
  POST /api/rejection-emails/{id}/cancel       — cancel (pending only)
  GET  /api/candidates/{id}/rejection-emails   — timeline for a candidate

The FE uses these to power the "Cofnij" toast after rejection, the
candidate-detail timeline, and audit views.

AuthZ: cancel requires either the row's `recruiter_id` OR an elevated role
(admin / delivery_lead). Rationale: if the recruiter is on leave or offline,
a DL should be able to pull the trigger to prevent a misfire; admins can
always intervene.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.notification import Notification, NotificationType
from app.models.rejection_email import (
    RejectionEmailStatus,
    ScheduledRejectionEmail,
)
from app.models.user import UserRole

router = APIRouter()


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
    others = [
        OtherProcessEntry(job_id=int(o["job_id"]), title=str(o.get("title", "")))
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


# ── Endpoints ───────────────────────────────────────────────────────────────


@router.get("/{rejection_email_id}", response_model=RejectionEmailResponse)
async def get_rejection_email(
    rejection_email_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RejectionEmailResponse:
    """Fetch a scheduled rejection email by id (for toast preview / timeline)."""
    row = await db.get(ScheduledRejectionEmail, rejection_email_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled rejection email not found",
        )
    return _to_response(row)


@router.post("/{rejection_email_id}/cancel", response_model=RejectionEmailResponse)
async def cancel_rejection_email(
    rejection_email_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> RejectionEmailResponse:
    """Cancel a pending rejection email (undo the 15-minute countdown).

    Idempotent semantics: a row that's already `cancelled` returns 200 with
    the row unchanged; any other terminal state returns 409 because we
    cannot "un-send" an email.
    """
    row = await db.get(ScheduledRejectionEmail, rejection_email_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Scheduled rejection email not found",
        )

    # AuthZ — recruiter who owns the row, admin, or delivery lead.
    if current_user.id != row.recruiter_id and current_user.role not in (
        UserRole.admin,
        UserRole.delivery_lead,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the assigned recruiter or an admin/delivery lead can cancel.",
        )

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
    current_user: CurrentUser,
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
    return [_to_response(r) for r in rows]
