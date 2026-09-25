"""Multiposting rekrutacji na portale (JustJoin.IT, RocketJobs, Pracuj.pl).

    GET   /api/job-portals/config                          — które portale działają
    GET   /api/job-boards/{board}/dictionaries             — słowniki JJIT/RocketJobs
    GET   /api/jobs/{job_id}/portal-listing-defaults       — podpowiedź ustawień
    GET   /api/jobs/{job_id}/portals                       — publikacje rekrutacji
    POST  /api/jobs/{job_id}/portals/{portal}/publish      — do kolejki
    PATCH /api/jobs/{job_id}/portals/{portal}/options      — zmiana ustawień
    POST  /api/jobs/{job_id}/portals/{portal}/unpublish    — wycofanie

Portale są za flagami (domyślnie OFF) — publikacja zwraca 409, a sekcja
w oknie zlecenia się nie renderuje. Logika: ``services/job_portals``.
Połączenie konta JustJoin.IT/RocketJobs: ``api/job_board_connection.py``.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Literal, Optional

from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, RecruiterPlus
from app.api.recruitment_access import ensure_job_editor, ensure_job_read_access
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.job import Job
from app.models.job_posting import JobPosting, Portal
from app.services import job_portals
from app.services.job_portals.base import JJIT_FAMILY, PortalError
from app.services.job_portals.service import (
    PortalRequestError,
    default_listing_options,
    request_publish,
    request_unpublish,
    update_options,
)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


class PortalConfigItem(BaseModel):
    portal: str
    label: str
    state: str  # disabled | misconfigured | not_connected | ready
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
    options: Optional[dict[str, Any]] = None
    pending_action: Optional[str] = None


class PortalSalary(BaseModel):
    from_: float = Field(alias="from", gt=0, le=10_000_000)
    to: float = Field(gt=0, le=10_000_000)
    unit: Literal["hour", "month"] = "month"

    model_config = {"populate_by_name": True}


class PortalListingOptions(BaseModel):
    category: Optional[str] = Field(default=None, max_length=80)
    experience_level: Optional[str] = Field(default=None, max_length=40)
    working_time: Optional[str] = Field(default=None, max_length=40)
    workplace_type: Optional[Literal["remote", "office", "hybrid"]] = None
    office_days: Optional[int] = Field(default=None, ge=0, le=5)
    city: Optional[str] = Field(default=None, max_length=120)
    salary: Optional[PortalSalary] = None

    def as_dict(self) -> dict[str, Any]:
        data = self.model_dump()
        if self.salary is not None:
            data["salary"] = self.salary.model_dump(by_alias=True)
        return data


class PublishRequest(BaseModel):
    options: Optional[PortalListingOptions] = None


class OptionsRequest(BaseModel):
    options: PortalListingOptions


class DictionaryItem(BaseModel):
    key: str
    name: str


class BoardDictionaries(BaseModel):
    categories: list[DictionaryItem]
    experience_levels: list[DictionaryItem]
    working_times: list[DictionaryItem]
    workplace_types: list[DictionaryItem]


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
        options=posting.options,
        pending_action=posting.pending_action,
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
    detail: dict[str, Any] = {"code": exc.code, "message": exc.message}
    if exc.problems:
        detail["problems"] = exc.problems
    return HTTPException(status_code=exc.status_code, detail=detail)


async def _job(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(404, detail="Nie znaleziono rekrutacji")
    return job


@router.get("/job-portals/config", response_model=PortalConfigResponse)
async def get_job_portals_config(
    current_user: OperationalUser, db: AsyncSession = Depends(get_db)
) -> PortalConfigResponse:
    """Stan portali bez sekretów — front renderuje sekcję tylko przy ``any_ready``."""

    items = []
    for config in job_portals.portal_configs():
        adapter = job_portals.ADAPTERS[config.portal]
        items.append(
            PortalConfigItem(
                portal=config.portal.value,
                label=adapter.label,
                state=await job_portals.resolve_state(db, config),
                enabled=config.enabled,
            )
        )
    return PortalConfigResponse(
        portals=items, any_ready=any(i.state == "ready" for i in items)
    )


# Słowniki dostawcy zmieniają się rzadko — pamięć procesu na dobę.
_DICTIONARY_TTL_SECONDS = 24 * 3600
_dictionary_cache: dict[str, tuple[float, BoardDictionaries]] = {}


def _dictionary_items(raw: Any) -> list[DictionaryItem]:
    items: list[DictionaryItem] = []
    for item in raw or []:
        if isinstance(item, str):
            items.append(DictionaryItem(key=item, name=item))
        elif isinstance(item, dict):
            key = item.get("key") or item.get("value") or item.get("id")
            if key:
                items.append(
                    DictionaryItem(key=str(key), name=str(item.get("name") or key))
                )
    return items


@router.get("/job-boards/{board}/dictionaries", response_model=BoardDictionaries)
async def get_board_dictionaries(
    board: str,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> BoardDictionaries:
    """Kategorie, poziomy, wymiary i tryby pracy — wartości do formularza ogłoszenia."""
    portal = _portal(board)
    if portal not in JJIT_FAMILY:
        raise HTTPException(422, detail="Ten portal nie ma słowników w NEXUSIE.")
    config = job_portals.PortalConfig.from_settings(portal)
    if await job_portals.resolve_state(db, config) != "ready":
        raise HTTPException(
            409,
            detail={
                "code": "portal_not_ready",
                "message": "Portal nie jest włączony albo konto nie jest połączone.",
            },
        )
    cached = _dictionary_cache.get("jjit")
    if cached and time.monotonic() - cached[0] < _DICTIONARY_TTL_SECONDS:
        return cached[1]
    from app.services.job_portals.jjit_client import JjitApi

    try:
        raw = await JjitApi().dictionaries()
    except PortalError as exc:
        raise HTTPException(
            502, detail={"code": "portal_error", "message": exc.message}
        ) from exc
    result = BoardDictionaries(
        categories=_dictionary_items(raw.get("categories")),
        experience_levels=_dictionary_items(raw.get("experienceLevels")),
        working_times=_dictionary_items(raw.get("workingTimes")),
        workplace_types=_dictionary_items(raw.get("workplaceTypes")),
    )
    _dictionary_cache["jjit"] = (time.monotonic(), result)
    return result


@router.get(
    "/jobs/{job_id}/portal-listing-defaults", response_model=PortalListingOptions
)
async def get_portal_listing_defaults(
    job_id: int,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> PortalListingOptions:
    job = await _job(db, job_id)
    await ensure_job_read_access(db, current_user, job_id)
    return PortalListingOptions.model_validate(default_listing_options(job))


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
    body: Optional[PublishRequest] = Body(default=None),
    db: AsyncSession = Depends(get_db),
) -> JobPostingRead:
    job = await _job(db, job_id)
    await ensure_job_editor(db, current_user, job)
    options = body.options.as_dict() if body and body.options else None
    try:
        posting = await request_publish(
            db,
            job=job,
            portal=_portal(portal),
            user_id=current_user.id,
            options=options,
        )
    except PortalRequestError as exc:
        raise _http(exc) from exc
    await db.commit()
    await db.refresh(posting)
    return _read(posting)


@router.patch("/jobs/{job_id}/portals/{portal}/options", response_model=JobPostingRead)
async def update_job_posting_options(
    job_id: int,
    portal: str,
    body: OptionsRequest,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> JobPostingRead:
    job = await _job(db, job_id)
    await ensure_job_editor(db, current_user, job)
    try:
        posting = await update_options(
            db, job=job, portal=_portal(portal), options=body.options.as_dict()
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
