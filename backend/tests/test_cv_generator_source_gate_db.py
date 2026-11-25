"""Generator i automat CV nie biorą pliku nieaktualnego ani z kwarantanny (Postgres).

25.11.2026, decyzja Artura: lista plików generatora (pierwszy plik bierze automat,
front zaznacza go domyślnie) i jawnie wybrany plik idą przez `current_cv_filters_for`.
Kwarantanna zdejmuje z pliku tylko `is_primary`, więc najnowszy plik innej osoby
wygrywał w `current_cv_ordering`. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.services.cv_generator_b2b.standalone_service import (
    StandaloneGenerationError,
    list_candidate_cv_sources,
    load_candidate_generation_source,
)

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 11, 25, tzinfo=timezone.utc)
FOREIGN_FILE = b"%PDF-1.4 fikcyjne CV innej osoby"


async def _profile() -> int:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Ewa", lastname=f"Fikcyjna{uuid.uuid4().hex[:8]}")
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _document(
    candidate_id: int,
    filename: str,
    *,
    content: bytes | None = None,
    age_days: int = 0,
    outdated: bool = False,
) -> int:
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename=filename,
            file_content=content or filename.encode(),
            document_kind=CandidateDocumentKind.cv,
            uploaded_at=NOW - timedelta(days=age_days),
            outdated_at=NOW if outdated else None,
        )
        db.add(document)
        await db.commit()
        return document.id


async def _quarantine(candidate_id: int, document_id: int) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceIdentityReview(
                candidate_id=candidate_id,
                source_kind="document",
                source_id=document_id,
                decision="confirmed_mismatch",
                provenance="cv_parser:document",
                detector_version="test",
                evidence={},
                reviewed_at=NOW,
            )
        )
        await db.commit()


async def _listed(candidate_id: int) -> list[str]:
    async with AsyncSessionLocal() as db:
        return [
            row["filename"] for row in await list_candidate_cv_sources(db, candidate_id)
        ]


async def _chosen(candidate_id: int, document_id: int) -> str:
    async with AsyncSessionLocal() as db:
        source = await load_candidate_generation_source(
            db, candidate_id=candidate_id, stage_id=None, cv_document_id=document_id
        )
        return source.cv_filename


async def test_newest_quarantined_file_and_its_copy_leave_the_list() -> None:
    candidate_id = await _profile()
    await _document(candidate_id, "wlasne.pdf", age_days=10)
    foreign_id = await _document(candidate_id, "cudze.pdf", content=FOREIGN_FILE)
    await _quarantine(candidate_id, foreign_id)
    await _document(candidate_id, "kopia.pdf", content=FOREIGN_FILE, age_days=1)

    assert await _listed(candidate_id) == ["wlasne.pdf"]


async def test_outdated_file_leaves_the_list() -> None:
    candidate_id = await _profile()
    await _document(candidate_id, "stare.pdf", age_days=10)
    await _document(candidate_id, "nieaktualne.pdf", outdated=True)

    assert await _listed(candidate_id) == ["stare.pdf"]


async def test_only_quarantined_file_gives_an_empty_list() -> None:
    """Automat pomija wtedy osobę z powodem `no_cv_document`."""
    candidate_id = await _profile()
    foreign_id = await _document(candidate_id, "cudze.pdf", content=FOREIGN_FILE)
    await _quarantine(candidate_id, foreign_id)

    assert await _listed(candidate_id) == []


@pytest.mark.parametrize("kind", ["quarantined", "outdated"])
async def test_explicit_choice_of_a_gated_file_is_refused(kind: str) -> None:
    candidate_id = await _profile()
    own_id = await _document(candidate_id, "wlasne.pdf", age_days=10)
    gated_id = await _document(
        candidate_id,
        "zablokowane.pdf",
        content=FOREIGN_FILE,
        outdated=kind == "outdated",
    )
    if kind == "quarantined":
        await _quarantine(candidate_id, gated_id)

    with pytest.raises(StandaloneGenerationError, match="Wybrane CV"):
        await _chosen(candidate_id, gated_id)
    assert await _chosen(candidate_id, own_id) == "wlasne.pdf"


async def test_certificate_stays_choosable() -> None:
    """Rodzaju pliku bramka wyboru nie sprawdza (R9-N7-11): wskazanie jest świadome."""
    candidate_id = await _profile()
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename="certyfikat.pdf",
            file_content=b"certyfikat",
            document_kind=CandidateDocumentKind.certificate,
            uploaded_at=NOW,
        )
        db.add(document)
        await db.commit()
        certificate_id = document.id

    assert await _listed(candidate_id) == ["certyfikat.pdf"]
    assert await _chosen(candidate_id, certificate_id) == "certyfikat.pdf"
