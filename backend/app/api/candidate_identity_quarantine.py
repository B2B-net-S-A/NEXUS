"""Review and controlled override API for candidate-source identity mismatch."""

# Keep eager annotations: FastAPI resolves the Annotated RBAC aliases at route
# registration time (same constraint as the other candidate routers).

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import (
    CandidateDocumentAccess,
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
from app.services.cv_source import quarantined_copy_sources

from app.api.section_access import SOURCING_SECTION_DEPENDENCIES

router = APIRouter(dependencies=SOURCING_SECTION_DEPENDENCIES)


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
    source_kind: Literal[
        "note", "document", "legacy_cv", "talent_radar_cv", "tr_legacy_cv"
    ]
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


class DocumentQuarantineOut(BaseModel):
    """Stan jednego pliku z listy plików profilu.

    `source_document_id` to plik do zwolnienia: ten sam przy oryginale, oryginał
    przy kopii. `source_removed`: oryginał usunięto z profilu, więc na liście nie
    ma wiersza z przyciskiem i zwolnienie idzie od kopii.
    """

    document_id: int
    state: Literal["quarantined", "copy"]
    source_document_id: int
    source_filename: str
    source_removed: bool
    manual: bool
    reviewed_at: datetime


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
    allow_removed_document: bool = False,
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
        document_stmt = select(CandidateDocument.id).where(
            CandidateDocument.id == source_id,
            CandidateDocument.candidate_id == candidate_id,
        )
        if not allow_removed_document:
            document_stmt = document_stmt.where(
                CandidateDocument.source_deleted_at.is_(None)
            )
        exists_row = await db.scalar(document_stmt)
    elif source_kind == "legacy_cv":
        # A legacy single-CV source is identified by its owning candidate id.
        exists_row = candidate_exists if source_id == candidate_id else None
    else:
        # Talent Radar remains an external source. The durable identity review
        # is the local quarantine artifact and is created only by the importer.
        exists_row = await db.scalar(
            select(CandidateSourceIdentityReview.id).where(
                CandidateSourceIdentityReview.candidate_id == candidate_id,
                CandidateSourceIdentityReview.source_kind.in_(
                    ("talent_radar_cv", "tr_legacy_cv")
                ),
                CandidateSourceIdentityReview.source_id == source_id,
            )
        )
    if exists_row is None:
        raise HTTPException(
            status_code=404, detail="Nie znaleziono tego pliku w profilu."
        )


@router.get(
    "/{candidate_id}/identity-quarantine",
    response_model=list[DocumentQuarantineOut],
)
async def list_candidate_document_quarantine(
    candidate_id: int,
    current_user: CandidateDocumentAccess,
    db: AsyncSession = Depends(get_db),
) -> list[DocumentQuarantineOut]:
    """Pliki profilu w kwarantannie i ich kopie, dla listy plików.

    Osobno od `GET /documents`, bo kopie wymagają czasem pobrania pliku z magazynu,
    a tej listy używają też podgląd i panel rekrutacji.
    """
    if (
        await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
        is None
    ):
        raise HTTPException(status_code=404, detail="Candidate not found")
    rows = (
        await db.execute(
            select(
                CandidateDocument.id,
                CandidateDocument.filename,
                CandidateDocument.source_deleted_at,
                CandidateSourceIdentityReview.provenance,
                CandidateSourceIdentityReview.reviewed_at,
            )
            .join(
                CandidateSourceIdentityReview,
                and_(
                    CandidateSourceIdentityReview.candidate_id
                    == CandidateDocument.candidate_id,
                    CandidateSourceIdentityReview.source_kind == "document",
                    CandidateSourceIdentityReview.source_id == CandidateDocument.id,
                ),
            )
            .where(
                CandidateDocument.candidate_id == candidate_id,
                # Ten sam warunek co `source_is_quarantined_clause`, tu po złączeniu.
                CandidateSourceIdentityReview.decision == "confirmed_mismatch",
                CandidateSourceIdentityReview.override_at.is_(None),
            )
        )
    ).all()
    sources = {row.id: row for row in rows}

    def entry(
        document_id: int, state: Literal["quarantined", "copy"], source_id: int
    ) -> DocumentQuarantineOut:
        source = sources[source_id]
        return DocumentQuarantineOut(
            document_id=document_id,
            state=state,
            source_document_id=source_id,
            source_filename=source.filename,
            source_removed=source.source_deleted_at is not None,
            manual=source.provenance.startswith("manual:"),
            reviewed_at=source.reviewed_at,
        )

    copies = await quarantined_copy_sources(db, candidate_id)
    return [
        *(
            entry(row.id, "quarantined", row.id)
            for row in rows
            if row.source_deleted_at is None
        ),
        *(entry(copy_id, "copy", source_id) for copy_id, source_id in copies.items()),
    ]


@router.get(
    "/{candidate_id}/identity-quarantine/{source_kind}/{source_id}",
    response_model=IdentityReviewOut,
)
async def get_candidate_source_identity_review(
    candidate_id: int,
    source_kind: Literal[
        "note", "document", "legacy_cv", "talent_radar_cv", "tr_legacy_cv"
    ],
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
    source_kind: Literal[
        "note", "document", "legacy_cv", "talent_radar_cv", "tr_legacy_cv"
    ],
    source_id: int,
    payload: IdentityQuarantineOverride,
    current_user: CandidateIdentityQuarantineOverrideAccess,
    db: AsyncSession = Depends(get_db),
) -> IdentityReviewOut:
    # Plik usunięty z profilu dalej trzyma w kwarantannie swoje kopie (#3060).
    await _require_source(
        db,
        candidate_id=candidate_id,
        source_kind=source_kind,
        source_id=source_id,
        allow_removed_document=True,
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
            detail="Zwolnić plik z kwarantanny może administrator albo Head of Recruitment.",
        ) from exc
    except IdentityQuarantineConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ten plik nie jest w kwarantannie. Odśwież listę plików.",
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Podaj powód zwolnienia, od 3 do 500 znaków.",
        ) from exc
    await db.commit()
    await db.refresh(row)
    return _serialize(row)
