"""Global app-level settings.

Today: `candidates_columns` — the default column set + order that every user
starts from on `/candidates`. Admin edits via PUT; GET is available to all
authenticated users (they need the default to render the list even if they
have no per-user override yet).

Per-user overrides live client-side in zustand (`columnPreferences`) and are
not stored here — that would be premature for a ~5-user org.
"""

from __future__ import annotations

from typing import Any, List

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.app_setting import AppSetting


router = APIRouter()


# Column ids the candidates list knows how to render. Mirrors `ALL_COLUMNS`
# on the frontend — keep in sync.
ALLOWED_CANDIDATE_COLUMNS: set[str] = {
    "candidate",
    "position",
    "status",
    "match",
    "created",
    "added_by",
}

# "candidate" is always first and always visible; it carries the avatar/name
# that identifies the row. Other columns are optional.
REQUIRED_CANDIDATE_COLUMNS: set[str] = {"candidate"}

DEFAULT_CANDIDATES_COLUMNS: dict[str, Any] = {
    "columns": ["candidate", "position", "status", "match", "created"],
}


class CandidatesColumnsConfig(BaseModel):
    columns: List[str] = Field(..., min_length=1)

    @field_validator("columns")
    @classmethod
    def _check_columns(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        for col in v:
            if col not in ALLOWED_CANDIDATE_COLUMNS:
                raise ValueError(
                    f"unknown column id {col!r}; allowed: {sorted(ALLOWED_CANDIDATE_COLUMNS)}"
                )
            if col in seen:
                raise ValueError(f"duplicate column id {col!r}")
            seen.add(col)
        missing_required = REQUIRED_CANDIDATE_COLUMNS - seen
        if missing_required:
            raise ValueError(
                f"required columns missing: {sorted(missing_required)}"
            )
        return v


@router.get("/candidates-columns")
async def get_candidates_columns(
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(AppSetting).where(AppSetting.key == "candidates_columns")
    )
    return row.value if row else DEFAULT_CANDIDATES_COLUMNS


@router.put("/candidates-columns")
async def put_candidates_columns(
    payload: CandidatesColumnsConfig,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    value = payload.model_dump()
    row = await db.scalar(
        select(AppSetting).where(AppSetting.key == "candidates_columns")
    )
    if row is None:
        row = AppSetting(key="candidates_columns", value=value, updated_by=admin.id)
        db.add(row)
    else:
        row.value = value
        row.updated_by = admin.id
    await db.commit()
    return value
