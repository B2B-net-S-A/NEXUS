"""Runda 9 (R9-X1-1, R9-N7-11): bieżące CV z BYTEA na prawdziwej sesji async.

`CandidateDocument.file_content` jest odroczone. CV z formularza kariery albo
maila leży w BYTEA bez `storage_key`, więc odczyt bez `undefer` kończył się
`MissingGreenlet` — 500 przy „Generuj CV", awaria auto-CV i pusta migawka
oryginału etapu. Test przechodzi przez prawdziwego Postgresa (CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services.cv_generator_b2b.standalone_service import (
    load_candidate_generation_source,
)
from app.services.cv_source import get_current_cv


async def _candidate_with_bytea_cv() -> int:
    marker = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Bytea", lastname=f"Cv-{marker}")
        db.add(candidate)
        await db.flush()
        db.add_all(
            [
                CandidateDocument(
                    candidate_id=candidate.id,
                    filename="formularz.pdf",
                    file_content=b"%PDF-1.4 synthetic cv",
                    document_kind=CandidateDocumentKind.other,
                    is_primary=False,
                    uploaded_at=now - timedelta(days=2),
                ),
                # Nowszy certyfikat nie jest CV (R9-N7-11).
                CandidateDocument(
                    candidate_id=candidate.id,
                    filename="certyfikat.pdf",
                    file_content=b"%PDF-1.4 synthetic certificate",
                    document_kind=CandidateDocumentKind.certificate,
                    is_primary=False,
                    uploaded_at=now,
                ),
            ]
        )
        await db.commit()
        return candidate.id


async def test_current_cv_reads_bytea_document_without_missing_greenlet():
    candidate_id = await _candidate_with_bytea_cv()
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        current = await get_current_cv(db, candidate)
    assert current is not None
    assert current.source == "document_bytea"
    assert current.content == b"%PDF-1.4 synthetic cv"
    assert current.filename == "formularz.pdf"


async def test_generation_source_reads_bytea_document_without_missing_greenlet():
    candidate_id = await _candidate_with_bytea_cv()
    async with AsyncSessionLocal() as db:
        source = await load_candidate_generation_source(
            db, candidate_id=candidate_id, stage_id=None
        )
    assert source.cv_bytes == b"%PDF-1.4 synthetic cv"
    assert source.cv_filename == "formularz.pdf"
