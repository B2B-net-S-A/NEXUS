"""Admin API wersjonowanych workflow (M4 plan PR-05) — shadow mode.

Endpoints (AdminUser):

- ``POST /api/admin/workflows/bootstrap`` — idempotentny bootstrap definitions
  + published rev 1 z legacy templates; zwraca raport mappingu (AC planu:
  100% aktywnych stages zmapowane albo w kwarantannie ``unmapped``),
- ``GET /api/admin/workflows`` — lista definitions z rewizjami i statystyką
  mappingu (ile etapów w kwarantannie),
- ``POST /api/admin/workflows/revisions/{revision_id}/draft`` — nowy draft
  jako pełna kopia rewizji (clone parity: semantic_key, scorecard_schema,
  terminalność, SLA, tracker, krawędzie — wszystko),
- ``PATCH /api/admin/workflows/stage-revisions/{id}`` — edycja etapu
  WYŁĄCZNIE w rewizji draft (np. przypisanie semantic_key kwarantannie);
  próba na published/archived → 409 (immutability),
- ``POST /api/admin/workflows/revisions/{revision_id}/publish`` — walidacja
  grafu (``validate_revision_graph``) + atomowa podmiana published.

Runtime pipeline NIC z tego nie czyta w tym PR — adopcja w PR-06/07.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.workflow_revision import (
    StageRevision,
    WorkflowDefinition,
    WorkflowEdge,
    WorkflowRevision,
    WorkflowRevisionStatus,
)
from app.services.semantic_states import SEMANTIC_STATES
from app.services.workflow_registry_service import (
    bootstrap_workflow_revisions,
    validate_revision_graph,
)

router = APIRouter()


@router.post("/workflows/bootstrap")
async def bootstrap_workflows(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    report = await bootstrap_workflow_revisions(db, created_by=current_user.id)
    await db.commit()
    return report.as_dict()


@router.get("/workflows")
async def list_workflows(
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    definitions = (
        (
            await db.execute(
                select(WorkflowDefinition).options(
                    selectinload(WorkflowDefinition.revisions)
                )
            )
        )
        .scalars()
        .all()
    )
    unmapped_counts = dict(
        (
            await db.execute(
                select(
                    StageRevision.workflow_revision_id,
                    func.count(StageRevision.id),
                )
                .where(StageRevision.semantic_key == "unmapped")
                .group_by(StageRevision.workflow_revision_id)
            )
        ).all()
    )
    return [
        {
            "id": d.id,
            "name": d.name,
            "template_id": d.template_id,
            "client_id": d.client_id,
            "archived": d.archived,
            "revisions": [
                {
                    "id": r.id,
                    "revision_no": r.revision_no,
                    "status": r.status.value,
                    "source": r.source,
                    "registry_version": r.registry_version,
                    "published_at": (
                        r.published_at.isoformat() if r.published_at else None
                    ),
                    "unmapped_stages": unmapped_counts.get(r.id, 0),
                }
                for r in d.revisions
            ],
        }
        for d in definitions
    ]


async def _load_revision(db: AsyncSession, revision_id: int) -> WorkflowRevision:
    rev = await db.scalar(
        select(WorkflowRevision)
        .options(
            selectinload(WorkflowRevision.stages),
            selectinload(WorkflowRevision.edges),
        )
        .where(WorkflowRevision.id == revision_id)
    )
    if rev is None:
        raise HTTPException(status_code=404, detail="Rewizja nie istnieje")
    return rev


@router.post("/workflows/revisions/{revision_id}/draft")
async def create_draft_from_revision(
    revision_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Nowy draft = pełna kopia (clone parity — audyt P0.2: legacy clone
    gubił legacy_enum_value/scorecard/client binding)."""
    src = await _load_revision(db, revision_id)
    next_no = (
        await db.scalar(
            select(func.max(WorkflowRevision.revision_no)).where(
                WorkflowRevision.workflow_id == src.workflow_id
            )
        )
        or 0
    ) + 1
    draft = WorkflowRevision(
        workflow_id=src.workflow_id,
        revision_no=next_no,
        status=WorkflowRevisionStatus.draft,
        source=f"draft-from-rev-{src.revision_no}",
        registry_version=src.registry_version,
    )
    db.add(draft)
    await db.flush()

    id_map: dict[int, int] = {}
    for s in src.stages:
        copy = StageRevision(
            workflow_revision_id=draft.id,
            source_stage_def_id=s.source_stage_def_id,
            name=s.name,
            order=s.order,
            category=s.category,
            semantic_key=s.semantic_key,
            is_terminal=s.is_terminal,
            terminal_type=s.terminal_type,
            tracker_enabled=s.tracker_enabled,
            tracker_public_name=s.tracker_public_name,
            sla_max_days=s.sla_max_days,
            scorecard_schema=s.scorecard_schema,
        )
        db.add(copy)
        await db.flush()
        id_map[s.id] = copy.id
    for e in src.edges:
        db.add(
            WorkflowEdge(
                workflow_revision_id=draft.id,
                from_stage_revision_id=(
                    id_map[e.from_stage_revision_id]
                    if e.from_stage_revision_id is not None
                    else None
                ),
                to_stage_revision_id=id_map[e.to_stage_revision_id],
            )
        )
    await db.commit()
    return {"draft_revision_id": draft.id, "revision_no": next_no}


class StageRevisionPatch(BaseModel):
    semantic_key: Optional[str] = None
    name: Optional[str] = Field(None, max_length=100)
    sla_max_days: Optional[int] = Field(None, ge=1)
    tracker_public_name: Optional[str] = Field(None, max_length=100)


@router.patch("/workflows/stage-revisions/{stage_revision_id}")
async def patch_stage_revision(
    stage_revision_id: int,
    payload: StageRevisionPatch,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    stage = await db.scalar(
        select(StageRevision).where(StageRevision.id == stage_revision_id)
    )
    if stage is None:
        raise HTTPException(status_code=404, detail="Etap nie istnieje")
    rev = await db.scalar(
        select(WorkflowRevision).where(
            WorkflowRevision.id == stage.workflow_revision_id
        )
    )
    # Immutability opublikowanej rewizji (audyt P1.2): edycja tylko draftu.
    if rev.status != WorkflowRevisionStatus.draft:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Rewizja jest '{rev.status.value}' — opublikowane rewizje są "
                "niemutowalne; utwórz draft."
            ),
        )
    data = payload.model_dump(exclude_unset=True)
    if "semantic_key" in data and data["semantic_key"] not in SEMANTIC_STATES:
        raise HTTPException(
            status_code=422,
            detail=f"Nieznany semantic_key {data['semantic_key']!r}",
        )
    for key, value in data.items():
        setattr(stage, key, value)
    await db.commit()
    return {"id": stage.id, **data}


@router.post("/workflows/revisions/{revision_id}/publish")
async def publish_revision(
    revision_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rev = await _load_revision(db, revision_id)
    if rev.status == WorkflowRevisionStatus.published:
        return {"revision_id": rev.id, "status": "published", "noop": True}
    if rev.status == WorkflowRevisionStatus.archived:
        raise HTTPException(
            status_code=409, detail="Nie można publikować zarchiwizowanej rewizji"
        )

    problems = validate_revision_graph(list(rev.stages), list(rev.edges))
    if problems:
        raise HTTPException(
            status_code=422,
            detail={"message": "Walidacja rewizji nie przeszła", "problems": problems},
        )

    # Atomowa podmiana: dotychczasowa published → archived, draft → published
    # (partial unique ux_workflow_one_published pilnuje niezmiennika).
    current_published = await db.scalar(
        select(WorkflowRevision).where(
            WorkflowRevision.workflow_id == rev.workflow_id,
            WorkflowRevision.status == WorkflowRevisionStatus.published,
        )
    )
    if current_published is not None:
        current_published.status = WorkflowRevisionStatus.archived
        await db.flush()
    rev.status = WorkflowRevisionStatus.published
    rev.published_at = datetime.now(timezone.utc)
    rev.published_by = current_user.id
    await db.commit()
    return {
        "revision_id": rev.id,
        "status": "published",
        "archived_revision_id": (current_published.id if current_published else None),
    }
