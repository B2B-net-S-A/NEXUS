"""Bulk actions on the candidates list (Traffit gap #3).

Single dispatch endpoint POST /api/candidates/bulk that accepts a list
of candidate_ids + an action discriminator and routes to the right
handler. Mirrors Traffit's "akcje masowe" floating bar on the candidate
list view.

Supported actions (Traffit had 8; we ship the 4 that map to existing
NEXUS data without reaching for new tables):

- add_tags             — append given tags to each candidate (JSONB merge)
- assign_talent_pool   — entry point + delegate flag for the existing
                         talent_pools API (UI batches via the floating bar)
- assign_to_job        — entry point + delegate flag for proposals_bulk
- anonymize_pii        — RODO-style erasure: clear PII, mark blacklisted

Skipped / deferred:
- bulk send_email / send_sms — needs an outbound queue + opt-in audit;
  defer until SMS provider integration lands (P3 in the gap roadmap).
- add_task — NEXUS has no Task model yet; a bulk endpoint that creates
  tasks would have to define one. Defer to a dedicated PR if needed.
- share / delete — already in the candidate detail page; bulk delete is
  destructive without recovery so we keep it manual.

All actions return a uniform BulkActionResponse with per-candidate
results so the UI can render "Wykonano dla 18 z 20 — 2 nie istnieją".
"""

from __future__ import annotations

import enum
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus

router = APIRouter()


# ── Request / response shapes ────────────────────────────────────────────────


class BulkAction(str, enum.Enum):
    add_tags = "add_tags"
    assign_talent_pool = "assign_talent_pool"
    assign_to_job = "assign_to_job"
    anonymize_pii = "anonymize_pii"


class BulkActionRequest(BaseModel):
    """Generic dispatch payload. Action-specific fields are carried in
    ``params`` to keep the request schema flat without an explicit per-action
    discriminated union."""

    action: BulkAction
    candidate_ids: List[int] = Field(..., min_length=1, max_length=500)

    # Per-action parameter bag. Validation runs in the handler since each
    # action expects different keys (e.g. add_tags wants `tags: list[str]`,
    # assign_to_job wants `job_id: int`).
    params: dict = Field(default_factory=dict)


class BulkActionItemResult(BaseModel):
    candidate_id: int
    ok: bool
    reason: Optional[str] = None


class BulkActionResponse(BaseModel):
    action: BulkAction
    requested: int
    succeeded: int
    skipped: int
    items: List[BulkActionItemResult]


# ── Handler dispatch ─────────────────────────────────────────────────────────


def _validate_tags(params: dict) -> List[str]:
    tags = params.get("tags") or []
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="params.tags must be a list of strings",
        )
    if len(tags) > 50:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cap of 50 tags per bulk call",
        )
    return [t.strip() for t in tags if t.strip()]


async def _handle_add_tags(
    candidates: List[Candidate], params: dict
) -> List[BulkActionItemResult]:
    tags = _validate_tags(params)

    results: List[BulkActionItemResult] = []
    for candidate in candidates:
        existing = list(candidate.tags or [])
        # Append, dedupe, preserve insertion order.
        merged = existing + [t for t in tags if t not in existing]
        candidate.tags = merged
        results.append(BulkActionItemResult(candidate_id=candidate.id, ok=True))
    return results


async def _handle_anonymize_pii(
    candidates: List[Candidate],
) -> List[BulkActionItemResult]:
    """RODO-style erasure: blank PII while keeping pipeline + skill history.

    Sets ``status = blacklisted`` so the candidate stops surfacing in
    sourcing flows. NEXUS doesn't have an explicit ``archived`` value;
    blacklisted is the closest stable terminal state.

    Note: this is a one-way transform. We don't keep a backup elsewhere.
    Recruiter is expected to confirm via UI dialog before calling.
    """
    results: List[BulkActionItemResult] = []
    for candidate in candidates:
        candidate.name = "[anonymized]"
        candidate.lastname = ""
        candidate.email = None
        candidate.phone = None
        candidate.linkedin = None
        candidate.status = CandidateStatus.blacklisted
        results.append(BulkActionItemResult(candidate_id=candidate.id, ok=True))
    return results


# ── Public endpoint ──────────────────────────────────────────────────────────


@router.post("/candidates/bulk", response_model=BulkActionResponse)
async def bulk_action(
    payload: BulkActionRequest,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BulkActionResponse:
    """Dispatch a bulk action across candidate_ids.

    Loads candidates once, runs the per-row handler, and reports a
    success/skip count. Skipped reasons:
    - candidate not found
    - action-specific guard rejected the row (returned in `reason`)

    Note: assign_talent_pool and assign_to_job are *opened* by this
    endpoint (the UI flips into multi-select mode and shows the right
    pool/job picker) but the actual membership write delegates to:
    - POST /api/talent-pools/{id}/members/bulk
    - POST /api/jobs/{id}/proposals/bulk
    The dispatcher reports OK for every loaded row so the UI can chain
    the next call deterministically.
    """
    # Dedupe + load.
    requested = sorted(set(payload.candidate_ids))
    if len(requested) > 500:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="cap of 500 candidates per bulk call",
        )

    rows = await db.execute(select(Candidate).where(Candidate.id.in_(requested)))
    candidates = list(rows.scalars().all())
    found_ids = {c.id for c in candidates}
    missing = [cid for cid in requested if cid not in found_ids]

    items: List[BulkActionItemResult] = []

    if payload.action is BulkAction.add_tags:
        items = await _handle_add_tags(candidates, payload.params)
    elif payload.action is BulkAction.anonymize_pii:
        items = await _handle_anonymize_pii(candidates)
    elif payload.action in (
        BulkAction.assign_talent_pool,
        BulkAction.assign_to_job,
    ):
        # Delegated — see docstring. We just report admission OK so the UI
        # can chain to the existing bulk endpoint.
        items = [BulkActionItemResult(candidate_id=c.id, ok=True) for c in candidates]

    # Add explicit not-found markers for missing IDs.
    for missing_id in missing:
        items.append(
            BulkActionItemResult(candidate_id=missing_id, ok=False, reason="not_found")
        )

    succeeded = sum(1 for it in items if it.ok)
    skipped = sum(1 for it in items if not it.ok)

    await db.commit()

    return BulkActionResponse(
        action=payload.action,
        requested=len(requested),
        succeeded=succeeded,
        skipped=skipped,
        items=items,
    )
