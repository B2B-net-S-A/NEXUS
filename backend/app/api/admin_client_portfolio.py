"""Read-only administration for the local client-portfolio import.

The first rollout intentionally exposes only planning and historical run
inspection.  Applying the checked-in manifest is wired in the cutover rollout,
after this preview has been exercised against production data.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_roles
from app.core.database import get_db
from app.models.client_directory import ClientImportRun
from app.models.user import User, UserRole
from app.services.client_portfolio_import import build_client_portfolio_plan

router = APIRouter()

ClientPortfolioReadUser = Annotated[
    User,
    Depends(require_roles(UserRole.admin, UserRole.finance)),
]


def _run_payload(run: ClientImportRun, *, include_rows: bool = False) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": run.id,
        "source_system": run.source_system,
        "source_filename": run.source_filename,
        "source_sha256": run.source_sha256,
        "status": run.status.value,
        "summary": run.summary,
        "error_message": run.error_message,
        "created_by": run.created_by,
        "approved_by": run.approved_by,
        "approved_at": run.approved_at,
        "applied_at": run.applied_at,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }
    if include_rows:
        payload["rows"] = [
            {
                "id": row.id,
                "sheet_name": row.sheet_name,
                "row_number": row.row_number,
                "source_key": row.source_key,
                "source_name": row.source_name,
                "category": row.category.value,
                "status": row.status.value,
                "matched_client_id": row.matched_client_id,
                "portfolio_scope_id": row.portfolio_scope_id,
                "framework_contract_id": row.framework_contract_id,
                "raw_payload": row.raw_payload,
                "error_message": row.error_message,
            }
            for row in run.rows
        ]
    return payload


@router.get("/import-preview")
async def preview_client_portfolio_import(
    _user: ClientPortfolioReadUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Build the deterministic production plan without writing any data."""

    return await build_client_portfolio_plan(db)


@router.get("/import-runs")
async def list_client_portfolio_import_runs(
    _user: ClientPortfolioReadUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
) -> dict[str, Any]:
    runs = (
        (
            await db.execute(
                select(ClientImportRun).order_by(ClientImportRun.id.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    return {"items": [_run_payload(run) for run in runs]}


@router.get("/import-runs/{run_id}")
async def get_client_portfolio_import_run(
    run_id: int,
    _user: ClientPortfolioReadUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    run = await db.scalar(
        select(ClientImportRun)
        .options(selectinload(ClientImportRun.rows))
        .where(ClientImportRun.id == run_id)
    )
    if run is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Client import run not found",
        )
    return _run_payload(run, include_rows=True)
