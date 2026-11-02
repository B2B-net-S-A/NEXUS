"""Panel klienta: ustawienia i sprawy od klienta dla Delivery Leada (0632).

Bramka jak przy wysyłce CV: uprawnienie „Rekrutacje” i członkostwo w rekrutacji.
Reguły: ``docs/claude/klienci/panel-klienta-pod-linkiem.md``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.permission_access import RecruitmentManageUser
from app.api.recruitment_access import ensure_job_membership, job_read_scope_clause
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate_document import CandidateDocument
from app.models.client_panel import ClientPanelCandidate, ClientPanelRequest
from app.models.job import Job
from app.models.user import User, UserRole
from app.services import client_panel as panel_service
from app.services import client_panel_evidence as evidence_service
from app.services import client_panel_requests as requests_service
from app.services.board_tasks import dl_portfolio_client_ids
from app.services.job_membership import is_member_of_job

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class PanelUpdate(BaseModel):
    enabled: Optional[bool] = None
    show_rate: Optional[bool] = None
    show_other_candidates: Optional[bool] = None
    allow_actions: Optional[bool] = None
    expires_at: Optional[datetime] = None


class CandidateUpdate(BaseModel):
    hidden: Optional[bool] = None
    rejected_evidence: Optional[list[str]] = Field(None, max_length=200)
    shared_document_ids: Optional[list[int]] = Field(None, max_length=50)


class AnswerIn(BaseModel):
    answer: str = Field(..., min_length=1, max_length=4000)
    send_email: bool = False


async def _job_for(db: AsyncSession, user: User, job_id: int) -> Job:
    await ensure_job_membership(db, user, job_id)
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    await _ensure_panel_manager(db, user, job)
    return job


async def _ensure_panel_manager(db: AsyncSession, user: User, job: Job) -> None:
    # Panel wypuszcza stawki i kandydatów na zewnątrz, więc nie wystarcza zwykły
    # dostęp do rekrutacji, który ma każdy Delivery Lead: tylko jej zespół albo
    # DL z portfelem klienta, poza tym admin i Head of Recruitment.
    if user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        return
    if await is_member_of_job(db, user, job.id, admin_bypass=False):
        return
    if user.has_role(
        UserRole.delivery_lead
    ) and job.client_id in await dl_portfolio_client_ids(db, user.id):
        return
    raise HTTPException(
        status_code=403,
        detail="Panelem klienta zarządza Delivery Lead tej rekrutacji.",
    )


def _audit(job_id: int, user: User, action: str, **details: object) -> Activity:
    return Activity(
        entity_type="job",
        entity_id=job_id,
        action=action,
        user_id=user.id,
        details=details,
    )


def _checked_expiry(value: datetime) -> datetime:
    moment = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    if moment <= now:
        raise HTTPException(
            status_code=422, detail="Data ważności linku musi być w przyszłości."
        )
    if moment > now + timedelta(days=panel_service.MAX_VALID_DAYS):
        raise HTTPException(
            status_code=422, detail="Link może być ważny najwyżej przez rok."
        )
    return moment


@router.get("/jobs/{job_id}")
async def get_job_panel(
    job_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _job_for(db, current_user, job_id)
    view = await panel_service.admin_view(db, job)
    await db.commit()
    return view


@router.put("/jobs/{job_id}")
async def update_job_panel(
    job_id: int,
    body: PanelUpdate,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _job_for(db, current_user, job_id)
    panel = await panel_service.get_or_create_panel(db, job_id, current_user.id)
    was_enabled = panel.enabled
    for field in ("show_rate", "show_other_candidates", "allow_actions"):
        value = getattr(body, field)
        if value is not None:
            setattr(panel, field, value)
    if body.expires_at is not None:
        panel.expires_at = _checked_expiry(body.expires_at)
    if body.enabled is not None:
        panel.enabled = body.enabled
    if panel.enabled and not was_enabled:
        if panel.token_nonce is None:
            panel_service.issue_token(panel)
        if body.expires_at is None and (
            panel.expires_at is None or panel_service.is_expired(panel)
        ):
            panel.expires_at = panel_service.default_expiry()
        db.add(_audit(job_id, current_user, "client_panel_enabled"))
    if was_enabled and not panel.enabled:
        db.add(_audit(job_id, current_user, "client_panel_disabled"))
    await db.flush()
    view = await panel_service.admin_view(db, job)
    await db.commit()
    return view


@router.post("/jobs/{job_id}/rotate-link")
async def rotate_job_panel_link(
    job_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _job_for(db, current_user, job_id)
    panel = await panel_service.panel_for_job(db, job_id)
    if panel is None or panel.token_nonce is None:
        raise HTTPException(status_code=409, detail="Ten panel nie ma jeszcze linku.")
    panel_service.issue_token(panel)
    db.add(_audit(job_id, current_user, "client_panel_link_rotated"))
    await db.flush()
    view = await panel_service.admin_view(db, job)
    await db.commit()
    return view


@router.patch("/jobs/{job_id}/candidates/{candidate_id}")
async def update_panel_candidate(
    job_id: int,
    candidate_id: int,
    body: CandidateUpdate,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await _job_for(db, current_user, job_id)
    if candidate_id not in await panel_service.sent_pairs(db, job_id):
        raise HTTPException(
            status_code=404, detail="Tej osoby nie ma na liście panelu."
        )
    panel = await panel_service.get_or_create_panel(db, job_id, current_user.id)
    rows = await panel_service.ensure_candidate_rows(db, panel.id, [candidate_id])
    row: ClientPanelCandidate = rows[candidate_id]
    if body.hidden is not None:
        row.hidden = body.hidden
    if body.rejected_evidence is not None:
        known = {
            req.key
            for req in evidence_service.requirements_from_job(
                job.must_skills, job.nice_skills
            )
        }
        if not set(body.rejected_evidence) <= known:
            raise HTTPException(
                status_code=422, detail="Tego wymagania nie ma w tej rekrutacji."
            )
        row.rejected_evidence = sorted(set(body.rejected_evidence))
    if body.shared_document_ids is not None:
        wanted = sorted(set(body.shared_document_ids))
        for document_id in wanted:
            document = await db.get(CandidateDocument, document_id)
            if document is None or document.candidate_id != candidate_id:
                raise HTTPException(
                    status_code=422, detail="Ten plik nie należy do tej osoby."
                )
        row.shared_document_ids = wanted
    await db.commit()
    return {
        "candidate_id": candidate_id,
        "public_id": row.public_id,
        "hidden": row.hidden,
        "rejected_evidence": row.rejected_evidence,
        "shared_document_ids": row.shared_document_ids,
    }


@router.get("/requests")
async def list_panel_requests(
    current_user: RecruitmentManageUser,
    job_id: Optional[int] = None,
    status: Optional[Literal["open", "answered", "closed"]] = Query(None),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    scope = None
    if job_id is not None:
        await _job_for(db, current_user, job_id)
    else:
        scope = job_read_scope_clause(
            current_user,
            ClientPanelRequest.job_id,
            oversight_bypass=current_user.has_any_role(
                UserRole.admin, UserRole.head_of_recruitment
            ),
        )
    return await requests_service.list_requests(
        db, job_id=job_id, status=status, scope_clause=scope
    )


async def _request_for(
    db: AsyncSession, user: User, request_id: int
) -> ClientPanelRequest:
    row = await db.get(ClientPanelRequest, request_id, with_for_update=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono tej sprawy.")
    await _job_for(db, user, row.job_id)
    return row


@router.post("/requests/{request_id}/answer")
async def answer_panel_request(
    request_id: int,
    body: AnswerIn,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _request_for(db, current_user, request_id)
    email_sent = await requests_service.answer_request(
        db,
        row=row,
        answer=body.answer,
        send_mail=body.send_email,
        user=current_user,
    )
    return {"id": request_id, "status": "answered", "email_sent": email_sent}


@router.post("/requests/{request_id}/close")
async def close_panel_request(
    request_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _request_for(db, current_user, request_id)
    requests_service.close_request(row)
    await db.commit()
    return {"id": request_id, "status": "closed"}


@router.get("/jobs/{job_id}/activity")
async def get_panel_activity(
    job_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _job_for(db, current_user, job_id)
    return await panel_service.activity(db, job_id)
