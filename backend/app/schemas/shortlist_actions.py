"""Pydantic request models for the Phase 3 action endpoints.

Lives in its own module — without `from __future__ import annotations` —
so Pydantic v2 can evaluate the field types at class-creation time. When the
hosting `recommendations.py` carries the future import, defining BaseModels
there leaves the field annotations as strings and FastAPI parses every
request body as form data (returning 422).
"""

from typing import List

from pydantic import BaseModel, Field


class CandidateShortlistEmailRequest(BaseModel):
    """Inputs for `POST /api/recommendations/send-candidate-shortlist-email`."""

    candidate_id: int = Field(..., description="ID kandydata, do którego idzie shortlist")
    job_ids: List[int] = Field(..., description="Lista ID ofert do zaproponowania")


class ClientProposalRequest(BaseModel):
    """Inputs for `POST /api/recommendations/prepare-client-proposal`."""

    candidate_id: int
    job_id: int
