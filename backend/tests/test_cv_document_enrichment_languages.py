"""Wgrane CV z sekcją języków musi zasilić profil (UAT M01-B02).

Sesje mają ``autoflush=False``, a pisarz języków przeładowuje kandydata
z ``populate_existing=True``. Przed poprawką przeładowanie kasowało
niezapisane zmiany z ``_apply_cv_enrichment`` (umiejętności, doświadczenie,
``cv_parsed_at``), więc commit zapisywał wyłącznie recenzję tożsamości
i języki — profil zostawał pusty mimo decyzji ``confirmed_match``.
CV bez sekcji języków omijało pisarza i działało, stąd „te same pliki
działają u innych kandydatów”.
"""

from __future__ import annotations

import hashlib
import uuid
from unittest.mock import AsyncMock

import pytest


def _parsed(first: str, last: str, *, with_languages: bool) -> dict:
    parsed = {
        "first_name": first,
        "last_name": last,
        "skills": [{"name": "Python", "level": "senior"}],
        "companies": ["Firma Testowa Alfa"],
        "years_it_experience": 6,
        "_source": "test",
    }
    if with_languages:
        parsed["languages"] = [{"name": "English", "level": "C1"}]
    return parsed


async def _seed(first: str, last: str) -> tuple[int, int, str]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import (
        CandidateDocument,
        CandidateDocumentKind,
    )

    content = f"CV {uuid.uuid4().hex}".encode()
    digest = hashlib.sha256(content).hexdigest()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name=first,
            lastname=last,
            email=f"cv-lang-{uuid.uuid4().hex[:10]}@example.com",
        )
        db.add(candidate)
        await db.flush()
        document = CandidateDocument(
            candidate_id=candidate.id,
            filename="cv-testowe.pdf",
            file_content=content,
            content_type="application/pdf",
            size_bytes=len(content),
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            external_source="manual",
            content_sha256=digest,
        )
        db.add(document)
        await db.commit()
        return candidate.id, document.id, digest


async def _cleanup(candidate_id: int) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument
    from app.models.candidate_language import CandidateLanguage
    from app.models.candidate_source_identity_review import (
        CandidateSourceIdentityReview,
    )

    async with AsyncSessionLocal() as db:
        for model in (
            CandidateSourceIdentityReview,
            CandidateLanguage,
            CandidateDocument,
        ):
            await db.execute(delete(model).where(model.candidate_id == candidate_id))
        await db.execute(delete(Candidate).where(Candidate.id == candidate_id))
        await db.commit()


@pytest.mark.asyncio
@pytest.mark.parametrize("with_languages", [True, False])
async def test_document_enrichment_fills_profile_with_and_without_languages(
    monkeypatch, with_languages: bool
):
    from app.api import candidates as candidates_api
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_source_identity_review import (
        CandidateSourceIdentityReview,
    )
    from sqlalchemy import select

    first, last = "Anna", f"Testowa{uuid.uuid4().hex[:6]}"
    candidate_id, document_id, digest = await _seed(first, last)

    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "Anna Testowa — Python developer",
    )
    monkeypatch.setattr(
        "app.services.cv_parser.parse_cv",
        AsyncMock(return_value=_parsed(first, last, with_languages=with_languages)),
    )
    monkeypatch.setattr(
        "app.services.index_outbox_service.schedule_or_embed_candidate",
        AsyncMock(return_value=True),
    )
    try:
        await candidates_api._enrich_candidate_from_document_task(
            candidate_id, document_id, digest
        )

        async with AsyncSessionLocal() as db:
            review = await db.scalar(
                select(CandidateSourceIdentityReview).where(
                    CandidateSourceIdentityReview.candidate_id == candidate_id
                )
            )
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )

        assert review is not None and review.decision == "confirmed_match"
        assert candidate is not None
        assert candidate.cv_parsed_at is not None
        assert [s["name"] for s in candidate.skills] == ["Python"]
        assert [e["company"] for e in candidate.experience] == ["Firma Testowa Alfa"]
        assert candidate.raw_cv_text
        if with_languages:
            assert candidate.languages and candidate.languages[0]["code"] == "EN"
    finally:
        await _cleanup(candidate_id)
