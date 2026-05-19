"""Schemas for the candidate-pin (short-list) feature.

See `app/models/candidate_pin.py` for the underlying table. The list response
embeds a minimal candidate brief so the frontend can render the pinned chip
bar without N+1 lookups for each candidate.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class CandidatePinBrief(BaseModel):
    """Minimal candidate snippet inside a CandidatePinRead — just what the
    chip bar above the candidates list needs to render (name, avatar
    initials, position) without fetching each pinned candidate separately.
    """

    id: int
    name: Optional[str] = None
    lastname: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None

    model_config = {"from_attributes": True}


class CandidatePinRead(BaseModel):
    """One pin record returned by GET /api/candidates/pins.

    `candidate` is eager-loaded by the endpoint so the chip bar can render
    without a second round-trip. Sorted DESC by pinned_at on the listing
    endpoint (most-recent pin first).
    """

    id: int
    candidate_id: int
    note: Optional[str] = None
    pinned_at: datetime
    candidate: CandidatePinBrief

    model_config = {"from_attributes": True}


class CandidatePinToggleResponse(BaseModel):
    """Response for POST /api/candidates/{id}/pin.

    `pinned=True` ⇒ the candidate is now pinned for the current user
    (either newly created or already existed).
    `pinned=False` ⇒ the toggle removed an existing pin.
    """

    pinned: bool
    pin: Optional[CandidatePinRead] = None


class CandidatePinCreatePayload(BaseModel):
    """Optional note attached when creating a pin via POST.

    Empty payload is valid — the body is optional. When the pin already
    exists, the existing record is kept (idempotent re-POST); the new note
    overwrites the existing one if provided.
    """

    note: Optional[str] = None
