"""Candidate Pins API — per-user short-list of candidates (Phase 4).

Endpoints:
    POST   /api/candidates/{id}/pin   → toggle: create-or-delete pin
    GET    /api/candidates/{id}/pin   → "is this candidate pinned?" probe
    DELETE /api/candidates/{id}/pin   → explicit unpin (idempotent)
    GET    /api/candidates/pins       → list all my pinned (DESC by pinned_at)

Mounted under `/api/candidates` from `app/main.py`. The `/pins` listing
endpoint MUST be registered before the `/{candidate_id}` catch-all route in
the candidates router — see also the comment in candidates.py:1349. We
mount this router separately to keep the registration order explicit.

Replaces Traffit's auto-recent "Otwarte karty" sidebar. Pins are intentional
short-listing (per-user, not shared), driven from the candidate drawer.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Path, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

# M2 audit follow-up (PR1b): CandidatePinBrief embeds candidate name,
# lastname and email, and the toggle/state routes accept an arbitrary
# candidate_id - so a viewer/client blocked from /api/candidates/{id} by
# PR1 could still harvest identity by walking IDs through the pin router.
from app.api.candidate_access import CandidatePIIAccess
from app.api.section_access import SOURCING_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_pin import CandidatePin
from app.schemas.candidate_pin import (
    CandidatePinCreatePayload,
    CandidatePinRead,
    CandidatePinToggleResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)

# Cap how many pins a single user may hold. The chip bar is meant for
# active short-listing (typically 3–10 candidates per role); much beyond
# that and the workflow stops being focused. Hard cap keeps the listing
# endpoint cheap and protects against runaway client bugs.
MAX_PINS_PER_USER = 50


@router.get("/pins", response_model=list[CandidatePinRead])
async def list_my_pins(
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> list[CandidatePin]:
    """Return all pinned candidates for the calling user, newest first.

    Eager-loads `candidate` so the chip bar renders without N+1 lookups.
    Capped at `MAX_PINS_PER_USER` rows — the POST endpoint enforces the
    same limit, so under normal usage the listing is bounded.
    """
    stmt = (
        select(CandidatePin)
        .where(CandidatePin.user_id == current_user.id)
        .options(selectinload(CandidatePin.candidate))
        .order_by(CandidatePin.pinned_at.desc())
        .limit(MAX_PINS_PER_USER)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{candidate_id}/pin", response_model=CandidatePinToggleResponse)
async def get_pin_state(
    current_user: CandidatePIIAccess,
    candidate_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> CandidatePinToggleResponse:
    """Check whether the current user has pinned this candidate.

    Returns the pin record when present. The drawer uses this on mount so
    the pin icon shows its correct filled/unfilled state.
    """
    stmt = (
        select(CandidatePin)
        .where(
            CandidatePin.user_id == current_user.id,
            CandidatePin.candidate_id == candidate_id,
        )
        .options(selectinload(CandidatePin.candidate))
    )
    existing = (await db.execute(stmt)).scalar_one_or_none()
    if existing is None:
        return CandidatePinToggleResponse(pinned=False, pin=None)
    return CandidatePinToggleResponse(
        pinned=True, pin=CandidatePinRead.model_validate(existing)
    )


@router.post("/{candidate_id}/pin", response_model=CandidatePinToggleResponse)
async def toggle_pin(
    current_user: CandidatePIIAccess,
    candidate_id: int = Path(..., ge=1),
    payload: Optional[CandidatePinCreatePayload] = None,
    db: AsyncSession = Depends(get_db),
) -> CandidatePinToggleResponse:
    """Toggle the pin for the given candidate.

    - If no pin exists → creates one (optionally with `note`) and returns
      `pinned=True` with the new record.
    - If a pin exists → deletes it and returns `pinned=False`.

    The toggle is intentional: clicking the icon twice removes the pin.
    For an explicit-only-create flow, use a fresh user-flow rather than
    overloading this endpoint with `?create=true`.

    Enforces `MAX_PINS_PER_USER` on the create branch — toggle-off is
    always allowed.
    """
    # Verify the candidate exists before pinning. Cheaper than letting the
    # FK constraint reject the INSERT — we get a clean 404 instead of 500.
    exists_stmt = select(Candidate.id).where(Candidate.id == candidate_id)
    if (await db.execute(exists_stmt)).scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Candidate {candidate_id} not found",
        )

    existing_stmt = select(CandidatePin).where(
        CandidatePin.user_id == current_user.id,
        CandidatePin.candidate_id == candidate_id,
    )
    existing = (await db.execute(existing_stmt)).scalar_one_or_none()

    if existing is not None:
        # Toggle OFF — delete the pin and return pinned=False.
        await db.delete(existing)
        await db.commit()
        return CandidatePinToggleResponse(pinned=False, pin=None)

    # Toggle ON — enforce the per-user cap before INSERT.
    count_stmt = select(CandidatePin.id).where(CandidatePin.user_id == current_user.id)
    pin_count = len((await db.execute(count_stmt)).scalars().all())
    if pin_count >= MAX_PINS_PER_USER:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Pin limit reached ({MAX_PINS_PER_USER}). Unpin some "
                "candidates before adding new ones."
            ),
        )

    note = payload.note if payload else None
    pin = CandidatePin(
        user_id=current_user.id,
        candidate_id=candidate_id,
        note=note,
    )
    db.add(pin)
    await db.commit()
    # Reload with the eager-loaded candidate so the response matches the
    # list endpoint's shape.
    refresh_stmt = (
        select(CandidatePin)
        .where(CandidatePin.id == pin.id)
        .options(selectinload(CandidatePin.candidate))
    )
    reloaded = (await db.execute(refresh_stmt)).scalar_one()
    return CandidatePinToggleResponse(
        pinned=True, pin=CandidatePinRead.model_validate(reloaded)
    )


@router.delete(
    "/{candidate_id}/pin",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,  # FastAPI 0.115 strict — 204 must not have body
)
async def delete_pin(
    current_user: CandidatePIIAccess,
    candidate_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_db),
) -> None:
    """Explicit unpin. Idempotent — deleting a non-existent pin is a no-op
    that still returns 204. Use this when the caller knows it wants to
    remove the pin regardless of current state (e.g. bulk-clear flows)."""
    await db.execute(
        delete(CandidatePin).where(
            CandidatePin.user_id == current_user.id,
            CandidatePin.candidate_id == candidate_id,
        )
    )
    await db.commit()
