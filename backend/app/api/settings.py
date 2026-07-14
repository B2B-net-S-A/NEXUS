"""Global app-level settings.

Today: `candidates_columns` — the default column set + order that every user
starts from on `/candidates`. Admin edits via PUT; GET is available to all
authenticated users (they need the default to render the list even if they
have no per-user override yet).

Resolve chain (GET):
  1. `candidates_columns:{current_user.role}` — role-specific default
  2. `candidates_columns`                       — global default
  3. DEFAULT_CANDIDATES_COLUMNS                 — hard-coded fallback

Admin can save either a global default (PUT with `role=null`) or a role-specific
default (PUT with `role=recruiter`, etc.). Only admin can write.

Per-user overrides live client-side in zustand (`columnPreferences`) and are
not stored here — that would be premature for a ~5-user org.
"""

from __future__ import annotations

from typing import Any, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser
from app.core.database import get_db
from app.models.app_setting import AppSetting
from app.models.user import UserRole


router = APIRouter()


# Column ids the candidates list knows how to render. Mirrors `ALL_COLUMNS`
# on the frontend — keep in sync. New columns (phone/email/cv/recruitments,
# rate/last_note/rejection_reason) live here so admin saves don't silently
# drop columns that the user just turned on.
ALLOWED_CANDIDATE_COLUMNS: set[str] = {
    "candidate",
    "contact",
    "status_availability",
    "process",
    "activity",
    "phone",
    "email",
    "cv",
    "recruitments",
    "stage_moved",
    "title",
    "company",
    "location",
    "experience",
    "skills",
    "rate",
    "last_note",
    "rejection_reason",
    "position",
    "status",
    "match",
    "created",
    "added_by",
}

# "candidate" is always first and always visible; it carries the avatar/name
# that identifies the row. Other columns are optional.
REQUIRED_CANDIDATE_COLUMNS: set[str] = {"candidate"}

# Triage-first default — same set as frontend HARD_DEFAULT_COLUMNS. Includes
# the contact/CV/recruitment triple + rate + last_note + rejection_reason so a
# recruiter doing boolean search immediately sees phone, email, CV link, active
# recruitments, rate, latest note and rejection reason without opening each
# candidate. Title/Company opt-in przez "Kolumny" popover (rzadziej potrzebne
# bezpośrednio po searchu).
DEFAULT_CANDIDATES_COLUMNS: dict[str, Any] = {
    "columns": [
        "candidate",
        "contact",
        "status_availability",
        "process",
        "rate",
        "activity",
    ],
}

# Base key for the global default (no suffix). Per-role defaults append
# `:{role.value}` (e.g. `candidates_columns:recruiter`).
_BASE_KEY = "candidates_columns"


def _key_for_role(role: UserRole | None) -> str:
    """Build the AppSetting key for a given role scope.

    `None` = global default (applies to all roles that don't have a specific
    override).
    """
    if role is None:
        return _BASE_KEY
    return f"{_BASE_KEY}:{role.value}"


class CandidatesColumnsConfig(BaseModel):
    columns: List[str] = Field(..., min_length=1)
    # None = save as global default (today's behavior). Otherwise save under
    # the role-specific key so that only users with that role see it by default.
    role: Optional[UserRole] = None

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
            raise ValueError(f"required columns missing: {sorted(missing_required)}")
        return v


@router.get("/candidates-columns")
async def get_candidates_columns(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the candidates-columns default for the current user.

    Resolve chain: role-specific → global → hard-coded fallback.
    Response shape is `{"columns": [...]}` to stay compatible with the
    existing frontend query.
    """
    role_row = await db.scalar(
        select(AppSetting).where(AppSetting.key == _key_for_role(user.role))
    )
    if role_row is not None:
        return {"columns": role_row.value["columns"]}

    global_row = await db.scalar(select(AppSetting).where(AppSetting.key == _BASE_KEY))
    if global_row is not None:
        return {"columns": global_row.value["columns"]}

    return DEFAULT_CANDIDATES_COLUMNS


@router.get("/candidates-columns/all")
async def get_all_candidates_columns(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return every saved default: global + per-role.

    Admin-only. Used by the admin UI to show which roles already have a
    dedicated default configured.
    """
    rows = await db.scalars(
        select(AppSetting).where(AppSetting.key.like(f"{_BASE_KEY}%"))
    )
    by_key: dict[str, dict[str, Any]] = {row.key: row.value for row in rows}

    out: dict[str, Any] = {
        "global": by_key.get(_BASE_KEY),
    }
    for role in UserRole:
        out[role.value] = by_key.get(_key_for_role(role))
    return out


@router.put("/candidates-columns")
async def put_candidates_columns(
    payload: CandidatesColumnsConfig,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Save the candidates-columns default.

    `role=null` saves the global default (applies to roles that don't have a
    dedicated override). Otherwise saves under `candidates_columns:{role}`.
    """
    key = _key_for_role(payload.role)
    # Only store `columns` in AppSetting.value — `role` lives in the key.
    value = {"columns": payload.columns}
    row = await db.scalar(select(AppSetting).where(AppSetting.key == key))
    if row is None:
        row = AppSetting(key=key, value=value, updated_by=admin.id)
        db.add(row)
    else:
        row.value = value
        row.updated_by = admin.id
    await db.commit()
    return {"columns": payload.columns, "role": payload.role}
