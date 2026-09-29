"""Dokumenty kontraktów z SharePointa — trasy admina (ticket 9, 0402).

Prefiks ``/api/contract-docs-sharepoint``. Pierwsze pobranie: podgląd (spis
folderu w tle) → zapis (pobieranie w tle) → cofnięcie; raport XLSX; kolejka
„Do przypisania” z synchronizacji. Bez ``from __future__ import annotations``
(pułapka slowapi #579 dla modułów, którym ktoś kiedyś doda limit).
"""

from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.config import settings
from app.core.database import get_db
from app.core.tasks import spawn
from app.models.candidate import Candidate
from app.models.contract import Contract
from app.models.contract_doc_sharepoint import (
    ContractDocSpItem,
    ContractDocSpRun,
    ContractDocSpRunItem,
)
from app.models.contract_document import ContractDocument
from app.models.user import User
from app.services.contract_folder_docs import service
from app.services.contract_folder_docs.store import FROM_SHAREPOINT
from app.services.contract_folder_docs.sync import (
    decide_review,
    health_status,
    run_sync,
)
from app.services.m365 import sharepoint_docs as sp

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


class PreviewRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=2000)
    folder_name: Optional[str] = Field(None, max_length=255)


class ApplyRequest(BaseModel):
    deselected_item_ids: list[int] = Field(default_factory=list, max_length=20000)


class ReviewDecision(BaseModel):
    action: Literal["assign", "dismiss"]
    contract_ids: list[int] = Field(default_factory=list, max_length=50)


def _run_dict(
    run: ContractDocSpRun, author: Optional[str], latest_applied: Optional[int]
) -> dict[str, Any]:
    return {
        "id": run.id,
        "mode": run.mode,
        "source_url": run.source_url,
        "counters": run.counters or {},
        "error": run.error,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "created_by_name": author,
        "applied_at": run.applied_at.isoformat() if run.applied_at else None,
        "rolled_back_at": run.rolled_back_at.isoformat()
        if run.rolled_back_at
        else None,
        "can_rollback": run.mode == "applied" and run.id == latest_applied,
    }


async def _latest_applied(db: AsyncSession) -> Optional[int]:
    return await db.scalar(
        select(func.max(ContractDocSpRun.id)).where(ContractDocSpRun.mode == "applied")
    )


@router.get("/status")
async def get_status(
    _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    state = await service.load_settings(db)
    review_count = await db.scalar(
        select(func.count())
        .select_from(ContractDocSpItem)
        .where(ContractDocSpItem.status == "review")
    )
    push_rows = (
        await db.execute(
            select(ContractDocument.sharepoint_push_status, func.count())
            .where(
                (ContractDocument.source.is_(None))
                | (ContractDocument.source.not_in(FROM_SHAREPOINT))
            )
            .group_by(ContractDocument.sharepoint_push_status)
        )
    ).all()
    push = {str(status or "waiting"): int(count) for status, count in push_rows}
    return {
        "configured": sp.credentials_configured(),
        "sync_enabled": settings.CONTRACT_DOCS_SP_SYNC_ENABLED,
        "health": await health_status(db),
        "url": state.get("url"),
        "folder_name": state.get("folder_name"),
        "folder_label": state.get("folder_label"),
        "folder_resolved": bool(state.get("folder_item_id")),
        "initial_import_run_id": state.get("initial_import_run_id"),
        "last_sync_at": state.get("last_sync_at"),
        "last_sync_status": state.get("last_sync_status"),
        "last_sync_error": state.get("last_sync_error"),
        "last_sync_stats": state.get("last_sync_stats") or {},
        "review_count": int(review_count or 0),
        "push_counts": push,
    }


@router.post("/preview")
async def start_preview(
    body: PreviewRequest, admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if not sp.credentials_configured():
        raise HTTPException(
            409,
            detail="NEXUS nie ma jeszcze dostępu do SharePointa — dokończ konfigurację w Azure.",
        )
    url = body.url.strip()
    if not url.lower().startswith("https://") or ".sharepoint.com" not in url.lower():
        raise HTTPException(
            422,
            detail="Wklej link do folderu w SharePoincie (https://…sharepoint.com/…).",
        )
    try:
        run = await service.start_preview(
            db, url=url, folder_name=body.folder_name, user_id=admin.id
        )
    except service.RunConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    run_id = run.id
    await db.commit()
    spawn(service.build_preview(run_id), f"contract_docs_sp preview {run_id}")
    return {"run_id": run_id, "mode": "listing"}


@router.get("/runs")
async def list_runs(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ContractDocSpRun, User.name)
            .outerjoin(User, User.id == ContractDocSpRun.created_by)
            .order_by(ContractDocSpRun.id.desc())
            .limit(limit)
        )
    ).all()
    latest = await _latest_applied(db)
    return [_run_dict(run, author, latest) for run, author in rows]


@router.get("/runs/{run_id}")
async def get_run(
    run_id: int, _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    run = await db.get(ContractDocSpRun, run_id)
    if run is None:
        raise HTTPException(404, detail="Przebieg nie istnieje.")
    author = (
        await db.scalar(select(User.name).where(User.id == run.created_by))
        if run.created_by
        else None
    )
    items = (
        (
            await db.execute(
                select(ContractDocSpRunItem)
                .where(ContractDocSpRunItem.run_id == run_id)
                .order_by(ContractDocSpRunItem.id)
            )
        )
        .scalars()
        .all()
    )
    progress = {"total": 0, "done": 0}
    for item in items:
        if item.kind == "assignment" and item.status != "not_selected":
            progress["total"] += 1
            if item.status in ("done", "skipped_existing", "failed"):
                progress["done"] += 1
    return {
        **_run_dict(run, author, await _latest_applied(db)),
        "progress": progress,
        "items": [
            {
                "id": i.id,
                "kind": i.kind,
                "folder_name": i.folder_name,
                "file_name": i.file_name,
                "size_bytes": i.size_bytes,
                "doc_type": i.doc_type,
                "contract_id": i.contract_id,
                "person_name": i.person_name,
                "match_kind": i.match_kind,
                "reasons": list(i.reasons or []),
                "note": i.note,
                "selected": i.selected,
                "status": i.status,
                "error": i.error,
            }
            for i in items
        ],
    }


@router.post("/runs/{run_id}/apply")
async def apply_run(
    run_id: int,
    body: ApplyRequest,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        await service.start_apply(
            db,
            run_id=run_id,
            deselected_item_ids=body.deselected_item_ids,
            user_id=admin.id,
        )
    except LookupError as exc:
        raise HTTPException(404, detail="Przebieg nie istnieje.") from exc
    except service.RunConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    await db.commit()
    spawn(service.apply_run(run_id), f"contract_docs_sp apply {run_id}")
    return {"run_id": run_id, "mode": "applying"}


@router.post("/runs/{run_id}/rollback")
async def rollback_run(
    run_id: int, admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    try:
        result = await service.rollback_run(db, run_id=run_id, user_id=admin.id)
    except LookupError as exc:
        raise HTTPException(404, detail="Przebieg nie istnieje.") from exc
    except service.RunConflict as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    await db.commit()
    service.delete_files_after_commit(db)
    return {"run_id": run_id, **result}


@router.get("/runs/{run_id}/report.xlsx")
async def run_report(
    run_id: int, _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> Response:
    if await db.get(ContractDocSpRun, run_id) is None:
        raise HTTPException(404, detail="Przebieg nie istnieje.")
    payload = await service.report_xlsx(db, run_id)
    return Response(
        content=payload,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="dokumenty-sharepoint-{run_id}.xlsx"'
        },
    )


@router.get("/review")
async def list_review(
    _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    rows = (
        (
            await db.execute(
                select(ContractDocSpItem)
                .where(ContractDocSpItem.status == "review")
                .order_by(ContractDocSpItem.folder_name, ContractDocSpItem.file_name)
                .limit(500)
            )
        )
        .scalars()
        .all()
    )
    contract_ids = {cid for r in rows for cid in (r.proposed_contract_ids or [])}
    people: dict[int, str] = {}
    if contract_ids:
        for cid, first, last in (
            await db.execute(
                select(Contract.id, Candidate.name, Candidate.lastname)
                .join(Candidate, Candidate.id == Contract.candidate_id)
                .where(Contract.id.in_(contract_ids))
            )
        ).all():
            people[cid] = f"{first or ''} {last or ''}".strip()
    return [
        {
            "item_id": r.item_id,
            "folder_name": r.folder_name,
            "file_name": r.file_name,
            "reasons": list(r.reasons or []),
            "proposed": [
                {"contract_id": cid, "person_name": people.get(cid)}
                for cid in (r.proposed_contract_ids or [])
            ],
        }
        for r in rows
    ]


@router.post("/review/{item_id}")
async def decide(
    item_id: str,
    body: ReviewDecision,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        result = await decide_review(
            db,
            item_id=item_id,
            action=body.action,
            contract_ids=body.contract_ids,
            user_id=admin.id,
        )
    except LookupError as exc:
        await db.rollback()
        raise HTTPException(404, detail="Tego pliku nie ma już w kolejce.") from exc
    except ValueError as exc:
        await db.rollback()
        raise HTTPException(422, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — błąd SharePointa jako zdanie
        await db.rollback()
        raise HTTPException(502, detail=service.polish_error(exc)) from exc
    await db.commit()
    return result


async def _sync_in_background() -> None:
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await run_sync(db)


@router.post("/sync-now")
async def sync_now(
    _admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    if not sp.credentials_configured():
        raise HTTPException(409, detail="NEXUS nie ma jeszcze dostępu do SharePointa.")
    state = await service.load_settings(db)
    if not state.get("initial_import_run_id"):
        raise HTTPException(409, detail="Najpierw zapisz pierwsze pobranie z folderu.")
    spawn(_sync_in_background(), "contract_docs_sp sync-now")
    return {"started": True}
