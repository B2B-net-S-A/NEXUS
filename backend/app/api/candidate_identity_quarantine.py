"""Review and controlled override API for candidate-source identity mismatch."""

# Keep eager annotations: FastAPI resolves the Annotated RBAC aliases at route
# registration time (same constraint as the other candidate routers).

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CandidateIdentityQuarantineOverrideAccess,
    CandidatePIIAccess,
    CandidateWriteAccess,
)
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.models.note import Note
from app.services.candidate_identity_quarantine import (
    IdentityQuarantineConflict,
    IdentityQuarantineForbidden,
    SourceKind,
    get_identity_review,
    mark_confirmed_mismatch,
    override_identity_quarantine,
)

router = APIRouter()


class IdentityMismatchMark(BaseModel):
    provenance: Literal[
        "manual_review",
        "integration_verification",
        "document_owner_confirmation",
    ] = "manual_review"


class IdentityQuarantineOverride(BaseModel):
    reason: str = Field(min_length=3, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = " ".join(value.split()).strip()
        if len(normalized) < 3:
            raise ValueError("override reason is required")
        return normalized


class IdentityReviewOut(BaseModel):
    candidate_id: int
    source_kind: Literal["note", "document", "legacy_cv", "talent_radar_cv"]
    source_id: int
    decision: Literal[
        "confirmed_match",
        "confirmed_mismatch",
        "inconclusive",
    ]
    provenance: str
    detector_version: str
    evidence: dict[str, bool]
    reviewed_by_id: int | None = None
    reviewed_at: datetime
    is_quarantined: bool
    override_active: bool
    override_by_id: int | None = None
    override_at: datetime | None = None


def _serialize(row: CandidateSourceIdentityReview) -> IdentityReviewOut:
    # Fingerprints are persisted for deterministic provenance but do not need
    # to cross the API boundary.
    evidence = {
        key: value
        for key, value in (row.evidence or {}).items()
        if isinstance(value, bool)
    }
    return IdentityReviewOut(
        candidate_id=row.candidate_id,
        source_kind=row.source_kind,
        source_id=row.source_id,
        decision=row.decision,
        provenance=row.provenance,
        detector_version=row.detector_version,
        evidence=evidence,
        reviewed_by_id=row.reviewed_by_id,
        reviewed_at=row.reviewed_at,
        is_quarantined=row.is_quarantined,
        override_active=row.override_at is not None,
        override_by_id=row.override_by_id,
        override_at=row.override_at,
    )


async def _require_source(
    db: AsyncSession,
    *,
    candidate_id: int,
    source_kind: SourceKind,
    source_id: int,
) -> None:
    candidate_exists = await db.scalar(
        select(Candidate.id).where(Candidate.id == candidate_id)
    )
    if candidate_exists is None:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if source_kind == "note":
        exists_row = await db.scalar(
            select(Note.id).where(
                Note.id == source_id,
                Note.candidate_id == candidate_id,
                Note.source_deleted_at.is_(None),
            )
        )
    elif source_kind == "document":
        exists_row = await db.scalar(
            select(CandidateDocument.id).where(
                CandidateDocument.id == source_id,
                CandidateDocument.candidate_id == candidate_id,
                CandidateDocument.source_deleted_at.is_(None),
            )
        )
    elif source_kind == "legacy_cv":
        # A legacy single-CV source is identified by its owning candidate id.
        exists_row = candidate_exists if source_id == candidate_id else None
    else:
        # Talent Radar remains an external source. The durable identity review
        # is the local quarantine artifact and is created only by the importer.
        exists_row = await db.scalar(
            select(CandidateSourceIdentityReview.id).where(
                CandidateSourceIdentityReview.candidate_id == candidate_id,
                CandidateSourceIdentityReview.source_kind == "talent_radar_cv",
                CandidateSourceIdentityReview.source_id == source_id,
            )
        )
    if exists_row is None:
        raise HTTPException(status_code=404, detail="Candidate source not found")


@router.get(
    "/{candidate_id}/identity-quarantine/{source_kind}/{source_id}",
    response_model=IdentityReviewOut,
)
async def get_candidate_source_identity_review(
    candidate_id: int,
    source_kind: Literal["note", "document", "legacy_cv", "talent_radar_cv"],
    source_id: int,
    current_user: CandidatePIIAccess,
    db: AsyncSession = Depends(get_db),
) -> IdentityReviewOut:
    await _require_source(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
    )
    row = await get_identity_review(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Identity review not found")
    return _serialize(row)


@router.put(
    "/{candidate_id}/identity-quarantine/{source_kind}/{source_id}",
    response_model=IdentityReviewOut,
)
async def quarantine_candidate_source_identity(
    candidate_id: int,
    # Talent Radar reviews are created automatically before projection. They
    # cannot be retroactively marked through this endpoint because the legacy
    # importer has no per-field ownership manifest for safely undoing an
    # already accepted merge. Its existing automatic mismatch can still be
    # inspected and explicitly released by management via the override route.
    source_kind: Literal["note", "document", "legacy_cv"],
    source_id: int,
    payload: IdentityMismatchMark,
    current_user: CandidateWriteAccess,
    db: AsyncSession = Depends(get_db),
) -> IdentityReviewOut:
    await _require_source(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
    )
    row = await mark_confirmed_mismatch(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        actor_id=current_user.id,
        provenance=payload.provenance,
    )
    await db.commit()
    await db.refresh(row)
    return _serialize(row)


@router.post(
    "/{candidate_id}/identity-quarantine/{source_kind}/{source_id}/override",
    response_model=IdentityReviewOut,
)
async def override_candidate_source_identity_quarantine(
    candidate_id: int,
    source_kind: Literal["note", "document", "legacy_cv", "talent_radar_cv"],
    source_id: int,
    payload: IdentityQuarantineOverride,
    current_user: CandidateIdentityQuarantineOverrideAccess,
    db: AsyncSession = Depends(get_db),
) -> IdentityReviewOut:
    await _require_source(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
    )
    try:
        row = await override_identity_quarantine(
            db,
            candidate_id=candidate_id,
            source_kind=source_kind,
            source_id=source_id,
            actor=current_user,
            reason=payload.reason,
        )
    except IdentityQuarantineForbidden as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Identity quarantine override requires admin or head_of_recruitment",
        ) from exc
    except (IdentityQuarantineConflict, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await db.commit()
    await db.refresh(row)
    return _serialize(row)
