"""Zespół dla klienta: zakładanie, skład, link dla klienta (0711).

Bramka jak w panelu rekrutacji (``api/client_panel.py``): uprawnienie
„Rekrutacje” i prawo do panelu na KAŻDEJ rekrutacji zespołu, bo link zespołu
włącza panele stanowisk i wypuszcza stawki na zewnątrz.
Reguły: ``docs/claude/klienci/zespol-dla-klienta.md``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.client_panel import _audit, _ensure_panel_manager
from app.api.deps import CurrentUser
from app.api.permission_access import RecruitmentManageUser
from app.api.recruitment_access import (
    assert_delivery_lead_job_visible,
    delivery_lead_job_pairs,
    ensure_job_membership,
)
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.job import Job
from app.models.job_team_panel import JobTeam
from app.models.user import User, UserRole
from app.services import client_panel as panel_service
from app.services import job_team_panel as team_service
from app.services import job_team_variants as variants_service

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

LIST_LIMIT = 200


def _clean_name(value: str) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        raise ValueError("Podaj nazwę zespołu.")
    return cleaned


def _unique(ids: list[int]) -> list[int]:
    return list(dict.fromkeys(ids))


class TeamCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    job_ids: list[int] = Field(..., min_length=1, max_length=team_service.MAX_JOBS)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return _clean_name(value)

    @field_validator("job_ids")
    @classmethod
    def _ids(cls, value: list[int]) -> list[int]:
        return _unique(value)


class TeamUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=160)
    add_job_ids: list[int] = Field(
        default_factory=list, max_length=team_service.MAX_JOBS
    )
    remove_job_ids: list[int] = Field(
        default_factory=list, max_length=team_service.MAX_JOBS
    )

    @field_validator("name")
    @classmethod
    def _name(cls, value: Optional[str]) -> Optional[str]:
        return _clean_name(value) if value is not None else None

    @field_validator("add_job_ids", "remove_job_ids")
    @classmethod
    def _ids(cls, value: list[int]) -> list[int]:
        return _unique(value)


class TeamPanelUpdate(BaseModel):
    enabled: Optional[bool] = None
    show_rate: Optional[bool] = None


class VariantPickIn(BaseModel):
    job_id: int
    candidate_ids: list[int] = Field(default_factory=list, max_length=50)


class VariantIn(BaseModel):
    """Gotowy skład od DL-a; nazwę i uzasadnienie czyta klient."""

    key: str = Field(..., min_length=1, max_length=variants_service.KEY_MAX)
    name: str = Field(..., min_length=1, max_length=4 * variants_service.NAME_MAX)
    why: str = Field("", max_length=4 * variants_service.WHY_MAX)
    picks: list[VariantPickIn] = Field(..., max_length=team_service.MAX_JOBS)

    @field_validator("key")
    @classmethod
    def _key(cls, value: str) -> str:
        return variants_service.clean_key(value)

    @field_validator("name")
    @classmethod
    def _name(cls, value: str) -> str:
        return variants_service.clean_text(
            value, limit=variants_service.NAME_MAX, required=True
        )

    @field_validator("why")
    @classmethod
    def _why(cls, value: str) -> str:
        return variants_service.clean_text(
            value, limit=variants_service.WHY_MAX, required=False
        )


class VariantsUpdate(BaseModel):
    variants: list[VariantIn] = Field(..., max_length=variants_service.MAX_VARIANTS)


async def _ensure_manages(db: AsyncSession, user: User, jobs: Iterable[Job]) -> None:
    for job in jobs:
        await ensure_job_membership(db, user, job.id)
        await _ensure_panel_manager(db, user, job)


def _oversight(user: User) -> bool:
    return user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)


async def _team_for(
    db: AsyncSession, user: User, team_id: int, *, lock: bool = False
) -> tuple[JobTeam, list[Job]]:
    team = await db.get(JobTeam, team_id, with_for_update=lock)
    if team is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono zespołu.")
    jobs = await team_service.team_jobs(db, team.id)
    if not jobs and not _oversight(user):
        raise HTTPException(
            status_code=403, detail="Zespołem zarządza Delivery Lead jego rekrutacji."
        )
    await _ensure_manages(db, user, jobs)
    return team, jobs


async def _jobs_by_id(db: AsyncSession, job_ids: list[int]) -> list[Job]:
    if not job_ids:
        return []
    found = {
        job.id: job
        for job in (
            await db.scalars(select(Job).where(Job.id.in_(job_ids)).with_for_update())
        ).all()
    }
    missing = [job_id for job_id in job_ids if job_id not in found]
    if missing:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    return [found[job_id] for job_id in job_ids]


@router.get("")
async def list_teams(
    current_user: RecruitmentManageUser,
    client_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    # Limit dopiero po filtrze uprawnień: inaczej DL nie widziałby swojego
    # zespołu spoza najnowszych LIST_LIMIT (przegląd 15.11.2026).
    query = select(JobTeam).order_by(JobTeam.id.desc())
    if client_id is not None:
        query = query.where(JobTeam.client_id == client_id)
    oversight = _oversight(current_user)
    if oversight:
        query = query.limit(LIST_LIMIT)
    teams = list((await db.scalars(query)).all())
    if not oversight:
        allowed = []
        for team in teams:
            if len(allowed) >= LIST_LIMIT:
                break
            jobs = await team_service.team_jobs(db, team.id)
            try:
                if not jobs:
                    continue
                await _ensure_manages(db, current_user, jobs)
            except HTTPException:
                continue
            allowed.append(team)
        teams = allowed
    return await team_service.summaries(db, teams)


@router.post("")
async def create_team(
    body: TeamCreate,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    jobs = await _jobs_by_id(db, body.job_ids)
    await _ensure_manages(db, current_user, jobs)
    team_service.check_jobs_joinable(jobs, client_id=jobs[0].client_id, team_id=None)
    team = JobTeam(
        client_id=jobs[0].client_id, name=body.name, created_by=current_user.id
    )
    db.add(team)
    await db.flush()
    for job in jobs:
        job.team_id = team.id
        db.add(_audit(job.id, current_user, "job_team_added", team_id=team.id))
    await db.flush()
    view = await team_service.team_detail(db, team, jobs)
    await db.commit()
    return view


@router.get("/by-job/{job_id}")
async def team_of_job(
    job_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    job = await db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Nie znaleziono rekrutacji.")
    # Ta sama bramka co karta rekrutacji (`GET /api/jobs/{id}`).
    assert_delivery_lead_job_visible(
        job, await delivery_lead_job_pairs(current_user, db)
    )
    team = await db.get(JobTeam, job.team_id) if job.team_id else None
    return {"team": {"id": team.id, "name": team.name} if team else None}


@router.get("/{team_id}")
async def get_team(
    team_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    team, jobs = await _team_for(db, current_user, team_id)
    view = await team_service.team_detail(db, team, jobs)
    await db.commit()
    return view


@router.patch("/{team_id}")
async def update_team(
    team_id: int,
    body: TeamUpdate,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    team, jobs = await _team_for(db, current_user, team_id, lock=True)
    if set(body.add_job_ids) & set(body.remove_job_ids):
        raise HTTPException(
            status_code=422, detail="Tej samej rekrutacji nie da się dodać i usunąć."
        )
    current = {job.id: job for job in jobs}
    if not set(body.remove_job_ids) <= set(current):
        raise HTTPException(
            status_code=422, detail="Tej rekrutacji nie ma w tym zespole."
        )
    added = [
        job for job in await _jobs_by_id(db, body.add_job_ids) if job.id not in current
    ]
    await _ensure_manages(db, current_user, added)
    team_service.check_jobs_joinable(added, client_id=team.client_id, team_id=team.id)
    kept = [job for job in jobs if job.id not in body.remove_job_ids]
    if not kept and not added:
        raise HTTPException(
            status_code=422, detail="Zespół musi mieć co najmniej jedną rekrutację."
        )
    if len(kept) + len(added) > team_service.MAX_JOBS:
        raise HTTPException(
            status_code=422,
            detail=f"Zespół może mieć najwyżej {team_service.MAX_JOBS} rekrutacji.",
        )
    if body.name is not None:
        team.name = body.name
    for job_id in body.remove_job_ids:
        current[job_id].team_id = None
        db.add(_audit(job_id, current_user, "job_team_removed", team_id=team.id))
    for job in added:
        job.team_id = team.id
        db.add(_audit(job.id, current_user, "job_team_added", team_id=team.id))
    if team.panel_enabled and added:
        # Nowe stanowisko włączonego zespołu dostaje panel jak pozostałe.
        await team_service.sync_position_panels(
            db, team, added, current_user.id, enable_positions=True
        )
    await db.flush()
    view = await team_service.team_detail(db, team, kept + added)
    await db.commit()
    return view


@router.put("/{team_id}/panel")
async def update_team_panel(
    team_id: int,
    body: TeamPanelUpdate,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    team, jobs = await _team_for(db, current_user, team_id, lock=True)
    was_enabled = team.panel_enabled
    if body.show_rate is not None:
        team.panel_show_rate = body.show_rate
    if body.enabled and not was_enabled:
        if all(team_service.is_closed(job) for job in jobs):
            raise HTTPException(
                status_code=409, detail=team_service.MSG_NO_OPEN_POSITIONS
            )
        if team.panel_token_nonce is None:
            team_service.issue_token(team)
        if team.panel_expires_at is None or team_service.is_expired(team):
            team.panel_expires_at = panel_service.default_expiry()
    if body.enabled is not None:
        team.panel_enabled = body.enabled
    if team.panel_enabled or was_enabled:
        changed = set(
            await team_service.sync_position_panels(
                db,
                team,
                jobs,
                current_user.id,
                # Panele stanowisk włącza tylko włączenie linku zespołu; sama
                # zmiana stawki nie wskrzesza stanowiska wyłączonego przez DL-a.
                enable_positions=team.panel_enabled and not was_enabled,
                rate_from_team=body.show_rate is not None,
            )
        )
        if team.panel_enabled != was_enabled:
            action = (
                "job_team_panel_enabled"
                if team.panel_enabled
                else "job_team_panel_disabled"
            )
            for job in jobs:
                if team.panel_enabled and team_service.is_closed(job):
                    continue
                db.add(
                    _audit(
                        job.id,
                        current_user,
                        action,
                        team_id=team.id,
                        position_panel_changed=job.id in changed,
                    )
                )
    await db.flush()
    view = await team_service.team_detail(db, team, jobs)
    await db.commit()
    return view


@router.post("/{team_id}/panel/rotate-link")
async def rotate_team_link(
    team_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    team, jobs = await _team_for(db, current_user, team_id, lock=True)
    if team.panel_token_nonce is None:
        raise HTTPException(status_code=409, detail="Ten zespół nie ma jeszcze linku.")
    team_service.issue_token(team)
    for job in jobs:
        panel = await panel_service.panel_for_job(db, job.id)
        if panel is not None and panel.token_nonce is not None:
            panel_service.issue_token(panel)
        db.add(
            _audit(job.id, current_user, "job_team_panel_link_rotated", team_id=team.id)
        )
    await db.flush()
    view = await team_service.team_detail(db, team, jobs)
    await db.commit()
    return view


# ── Gotowe składy (Z3, 0713) ─────────────────────────────────────────────────


@router.get("/{team_id}/variants/proposal")
async def propose_variants(
    team_id: int,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Trzy składy automatu do przejrzenia przez DL-a; nic nie zapisuje."""
    _, jobs = await _team_for(db, current_user, team_id)
    return {"variants": await variants_service.proposal(db, jobs)}


@router.put("/{team_id}/variants")
async def approve_variants(
    team_id: int,
    body: VariantsUpdate,
    current_user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Zatwierdzone składy dla klienta; pusta lista = wycofanie."""
    team, jobs = await _team_for(db, current_user, team_id, lock=True)
    variants = variants_service.validate_variants(
        [variant.model_dump() for variant in body.variants],
        seats={job.id: team_service.headcount(job) for job in jobs},
        sent=await variants_service.sent_by_job(db, jobs),
    )
    team.variants = variants
    team.variants_approved_at = datetime.now(timezone.utc) if variants else None
    team.variants_approved_by = current_user.id if variants else None
    action = "job_team_variants_approved" if variants else "job_team_variants_withdrawn"
    for job in jobs:
        db.add(
            _audit(job.id, current_user, action, team_id=team.id, count=len(variants))
        )
    await db.flush()
    view = await team_service.team_detail(db, team, jobs)
    await db.commit()
    return view
