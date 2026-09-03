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
- anonymize_pii        — DISABLED (M2 audit PR 1): answers 409 until the
                         PR 2 privacy executor lands; the old handler only
                         blanked contact fields (false RODO erasure)

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

from app.api.candidate_access import CandidateWriteAccess, privacy_workflow_unavailable
from app.core.database import get_db
from app.models.candidate import Candidate
from app.services import candidate_audit

from app.api.section_access import SOURCING_SECTION_DEPENDENCIES

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


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


# M2 audit PR 1 (M2-SEC-02 + M2-PRIV-01): the previous `_handle_anonymize_pii`
# blanked only a handful of contact fields (name/email/phone/linkedin) while
# leaving raw CV text, documents, notes, calls, vectors and integration
# payloads untouched — a false sense of RODO erasure — and was callable by ANY
# logged-in user for up to 500 candidates at once. The action is disabled until
# the PR 2 privacy executor (preview → approval → artifact manifest → retry)
# replaces it. Do not re-enable a partial-erasure shortcut here.


# ── Public endpoint ──────────────────────────────────────────────────────────


@router.post("/candidates/bulk", response_model=BulkActionResponse)
async def bulk_action(
    payload: BulkActionRequest,
    current_user: CandidateWriteAccess,
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
    # Escalation-by-body guard (M2-SEC-02): the destructive action is checked
    # BEFORE any candidate row is loaded or touched, so switching `action` in
    # the payload cannot smuggle a pseudonymisation past the role guard.
    if payload.action is BulkAction.anonymize_pii:
        candidate_audit.record_candidate_audit(
            db,
            action=candidate_audit.SENSITIVE_OPERATION_BLOCKED,
            user_id=current_user.id,
            details={
                "operation": "bulk_anonymize_pii",
                "reason": "privacy_workflow_required",
                "requested_count": len(set(payload.candidate_ids)),
            },
        )
        await db.commit()
        raise privacy_workflow_unavailable("masowa pseudonimizacja (anonymize_pii)")

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

    candidate_audit.record_candidate_audit(
        db,
        action=candidate_audit.BULK_ACTION_EXECUTED,
        user_id=current_user.id,
        details={
            "bulk_action": payload.action.value,
            "requested": len(requested),
            "succeeded": succeeded,
            "skipped": skipped,
        },
    )
    await db.commit()

    return BulkActionResponse(
        action=payload.action,
        requested=len(requested),
        succeeded=succeeded,
        skipped=skipped,
        items=items,
    )
