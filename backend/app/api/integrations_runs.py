"""Runy integracji zewnętrznych — zapis przez scrapery, odczyt w Insights.

Dwa routery, dwie publiczności:

- ``writer`` (``/api/integrations``) — wołany przez scrapery pracuj.pl / JJIT
  tokenem klienta OAuth (``acting_user`` z rolą operacyjną, migracja 0311).
  Bramka ``OperationalUser``: każda rola operacyjna, żeby raport z Maca nie
  wymagał admina. Kontrakt jest celowo prosty i fail-soft po stronie klienta:
  start → (batch zdarzeń)* → finish. Zgubiony ``finish`` = run wisi jako
  ``running`` i po ``stale_after_hours`` liczy się jak martwy.
- ``reader`` (``/api/insights/integrations``) — sekcja „Integracje" w Insights,
  bramka sekcji ``insights`` jak reszta zakładki.

Czego tu świadomie NIE ma: usuwania runów (historia integracji jest dowodem,
co zrobiono z aplikacją kandydata) i osobnego scope'u OAuth (rola usera
serwisowego wystarcza; granularne scope'y — patrz komentarz w deps.py).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.models.integration_run import (
    EVENT_ACTIONS,
    INTEGRATION_SOURCES,
    RUN_MODES,
    IntegrationRun,
    IntegrationRunEvent,
)
from app.services.integration_runs import build_summary, run_to_dict

writer = APIRouter()
reader = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

SourceLiteral = Literal["pracuj", "jjit"]
ModeLiteral = Literal["import", "replay", "test", "dry_run"]
StatusLiteral = Literal["ok", "errors", "failed"]
ActionLiteral = Literal["created", "duplicate", "cv_refreshed", "error", "skipped"]

assert set(SourceLiteral.__args__) == set(INTEGRATION_SOURCES)  # type: ignore[attr-defined]
assert set(ModeLiteral.__args__) == set(RUN_MODES)  # type: ignore[attr-defined]
assert set(ActionLiteral.__args__) == set(EVENT_ACTIONS)  # type: ignore[attr-defined]

MAX_EVENTS_PER_BATCH = 500


# ── Schemas ─────────────────────────────────────────────────────────────────


class RunStart(BaseModel):
    source: SourceLiteral
    mode: ModeLiteral = "import"
    host: Optional[str] = Field(None, max_length=64)
    version: Optional[str] = Field(None, max_length=64)
    started_at: Optional[datetime] = Field(
        None, description="Czas startu po stronie scrapera; domyślnie teraz."
    )


class RunFinish(BaseModel):
    status: StatusLiteral
    stats: dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = Field(None, max_length=4000)
    finished_at: Optional[datetime] = None


class RunEventIn(BaseModel):
    action: ActionLiteral
    external_id: Optional[str] = Field(None, max_length=128)
    candidate_id: Optional[int] = None
    traffit_id: Optional[int] = None
    candidate_name: Optional[str] = Field(None, max_length=255)
    offer_title: Optional[str] = Field(None, max_length=255)
    matched_jobs: list[dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = Field(None, max_length=2000)
    occurred_at: Optional[datetime] = None


class RunOut(BaseModel):
    id: int
    source: str
    mode: str
    status: str
    started_at: datetime
    finished_at: Optional[datetime]
    host: Optional[str]
    version: Optional[str]
    stats: dict[str, Any]
    error: Optional[str]


# ── Writer (scrapery) ───────────────────────────────────────────────────────


async def _load_run(db: AsyncSession, run_id: int) -> IntegrationRun:
    run = await db.get(IntegrationRun, run_id)
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Run nie istnieje"
        )
    return run


@writer.post("/runs", response_model=RunOut, status_code=status.HTTP_201_CREATED)
async def start_run(
    payload: RunStart,
    request: Request,
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = IntegrationRun(
        source=payload.source,
        mode=payload.mode,
        status="running",
        started_at=payload.started_at or datetime.now(timezone.utc),
        host=payload.host,
        version=payload.version,
        stats={},
        oauth_client_id=getattr(request.state, "oauth_client_id", None),
        created_by=current_user.id,
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run_to_dict(run)


@writer.patch("/runs/{run_id}", response_model=RunOut)
async def finish_run(
    run_id: int,
    payload: RunFinish,
    _: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await _load_run(db, run_id)
    run.status = payload.status
    run.stats = {**(run.stats or {}), **payload.stats}
    run.error = payload.error
    run.finished_at = payload.finished_at or datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(run)
    return run_to_dict(run)


@writer.post("/runs/{run_id}/events", status_code=status.HTTP_201_CREATED)
async def add_run_events(
    run_id: int,
    payload: List[RunEventIn],
    _: OperationalUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if len(payload) > MAX_EVENTS_PER_BATCH:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Max {MAX_EVENTS_PER_BATCH} zdarzeń w jednym batchu",
        )
    run = await _load_run(db, run_id)
    now = datetime.now(timezone.utc)
    for item in payload:
        db.add(
            IntegrationRunEvent(
                run_id=run.id,
                source=run.source,
                external_id=item.external_id,
                candidate_id=item.candidate_id,
                traffit_id=item.traffit_id,
                action=item.action,
                candidate_name=item.candidate_name,
                offer_title=item.offer_title,
                matched_jobs=item.matched_jobs,
                error=item.error,
                occurred_at=item.occurred_at or now,
            )
        )
    await db.commit()
    return {"inserted": len(payload), "run_id": run.id}


# ── Reader (Insights) ───────────────────────────────────────────────────────


@reader.get("/summary")
async def integrations_summary(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await build_summary(
        db,
        days=days,
        stale_after_hours=float(settings.INTEGRATION_STALE_AFTER_HOURS),
    )


@reader.get("/runs", response_model=List[RunOut])
async def list_runs(
    source: Optional[SourceLiteral] = Query(None),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    stmt = select(IntegrationRun).order_by(desc(IntegrationRun.started_at)).limit(limit)
    if source:
        stmt = stmt.where(IntegrationRun.source == source)
    runs = (await db.execute(stmt)).scalars().all()
    return [run_to_dict(run) for run in runs]


@reader.get("/runs/{run_id}/events")
async def list_run_events(
    run_id: int,
    limit: int = Query(200, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    await _load_run(db, run_id)
    events = (
        (
            await db.execute(
                select(IntegrationRunEvent)
                .where(IntegrationRunEvent.run_id == run_id)
                .order_by(desc(IntegrationRunEvent.occurred_at))
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": e.id,
            "action": e.action,
            "external_id": e.external_id,
            "candidate_id": e.candidate_id,
            "traffit_id": e.traffit_id,
            "candidate_name": e.candidate_name,
            "offer_title": e.offer_title,
            "matched_jobs": e.matched_jobs,
            "error": e.error,
            "occurred_at": e.occurred_at,
        }
        for e in events
    ]
