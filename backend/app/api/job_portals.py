"""Multiposting rekrutacji na portale (Pracuj.pl, JustJoinIT) — szkielet (0360).

    GET  /api/job-portals/config                         — które portale działają
    GET  /api/jobs/{job_id}/portals                      — publikacje rekrutacji
    POST /api/jobs/{job_id}/portals/{portal}/publish     — do kolejki
    POST /api/jobs/{job_id}/portals/{portal}/unpublish   — wycofanie

Zastępuje symulację z ``api/postings.py`` (losowe ``SIM-…``). Portale są
dziś wyłączone flagami — publikacja zwraca 409, a sekcja w oknie zlecenia
się nie renderuje. Logika: ``services/job_portals``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, RecruiterPlus
from app.api.recruitment_access import ensure_job_editor, ensure_job_read_access
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.job import Job
from app.models.job_posting import JobPosting, Portal
from app.services import job_portals
from app.services.job_portals.service import (
    PortalRequestError,
    request_publish,
    request_unpublish,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


class PortalConfigItem(BaseModel):
    portal: str
    label: str
    state: str  # disabled | misconfigured | ready
    enabled: bool


class PortalConfigResponse(BaseModel):
    portals: list[PortalConfigItem]
    any_ready: bool


class JobPostingRead(BaseModel):
    id: int
    portal: str
    status: str
    external_id: Optional[str] = None
    url: Optional[str] = None
    published_at: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    last_error: Optional[str] = None
    attempts: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


def _read(posting: JobPosting) -> JobPostingRead:
    return JobPostingRead(
        id=posting.id,
        portal=getattr(posting.portal, "value", posting.portal),
        status=getattr(posting.status, "value", posting.status),
        external_id=posting.external_id,
        url=posting.url,
        published_at=posting.published_at,
        last_synced_at=posting.last_synced_at,
        last_error=posting.last_error,
        attempts=posting.attempts or 0,
        created_at=posting.created_at,
        updated_at=posting.updated_at,
    )


def _portal(value: str) -> Portal:
    try:
        portal = Portal(value)
    except ValueError:
        raise HTTPException(422, detail="Nieznany portal.") from None
    if portal not in job_portals.ADAPTERS:
        raise HTTPException(422, detail="Ten portal nie ma integracji w NEXUSIE.")
    return portal


def _http(exc: PortalRequestError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}
    )


async def _job(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, detail="Nie znaleziono rekrutacji")
    return job


@router.get("/job-portals/config", response_model=PortalConfigResponse)
async def get_job_portals_config(current_user: OperationalUser) -> PortalConfigResponse:
    """Stan portali bez sekretów — front renderuje sekcję tylko przy ``any_ready``."""

    items = []
    for config in job_portals.portal_configs():
        adapter = job_portals.ADAPTERS[config.portal]
        items.append(
            PortalConfigItem(
                portal=config.portal.value,
                label=adapter.label,
                state=config.state,
                enabled=config.enabled,
            )
        )
    return PortalConfigResponse(
        portals=items, any_ready=any(i.state == "ready" for i in items)
    )


@router.get("/jobs/{job_id}/portals", response_model=list[JobPostingRead])
async def list_job_postings(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> list[JobPostingRead]:
    await _job(db, job_id)
    await ensure_job_read_access(db, current_user, job_id)
    rows = (
        await db.scalars(
            select(JobPosting)
            .where(
                JobPosting.job_id == job_id,
                JobPosting.portal.in_(list(job_portals.ADAPTERS)),
            )
            .order_by(JobPosting.id.desc())
        )
    ).all()
    return [_read(row) for row in rows]


@router.post("/jobs/{job_id}/portals/{portal}/publish", response_model=JobPostingRead)
async def publish_job_posting(
    job_id: int,
    portal: str,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobPostingRead:
    job = await _job(db, job_id)
    await ensure_job_editor(db, current_user, job)
    try:
        posting = await request_publish(
            db, job=job, portal=_portal(portal), user_id=current_user.id
        )
    except PortalRequestError as exc:
        raise _http(exc) from exc
    await db.commit()
    await db.refresh(posting)
    return _read(posting)


@router.post("/jobs/{job_id}/portals/{portal}/unpublish", response_model=JobPostingRead)
async def unpublish_job_posting(
    job_id: int,
    portal: str,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobPostingRead:
    job = await _job(db, job_id)
    await ensure_job_editor(db, current_user, job)
    try:
        posting = await request_unpublish(db, job=job, portal=_portal(portal))
    except PortalRequestError as exc:
        raise _http(exc) from exc
    if posting is None:
        raise HTTPException(
            404, detail="Rekrutacja nie jest publikowana na tym portalu."
        )
    await db.commit()
    await db.refresh(posting)
    return _read(posting)
