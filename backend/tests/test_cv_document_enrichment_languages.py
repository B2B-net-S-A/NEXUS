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


@pytest.mark.asyncio
async def test_document_enrichment_does_not_overwrite_edit_made_during_parse(
    monkeypatch,
):
    """Runda 9 (R9-N8-4): zapis po odczycie modelu idzie na świeżym wierszu.

    Rekruter zablokował umiejętności, kiedy model czytał CV. Zadanie w tle
    pisało ze starej kopii (bez blokady) i nadpisywało jego zmianę.
    """
    from app.api import candidates as candidates_api
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import select

    first, last = "Anna", f"Testowa{uuid.uuid4().hex[:6]}"
    candidate_id, document_id, digest = await _seed(first, last)

    async def _parse_while_recruiter_edits(*_args, **_kwargs):
        async with AsyncSessionLocal() as other:
            row = await other.get(Candidate, candidate_id)
            row.skills = [{"name": "Rust", "level": "expert"}]
            row.cv_extracted_data = {"_manual_override_skills": True}
            await other.commit()
        return _parsed(first, last, with_languages=False)

    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "Anna Testowa — Python developer",
    )
    monkeypatch.setattr("app.services.cv_parser.parse_cv", _parse_while_recruiter_edits)
    monkeypatch.setattr(
        "app.services.index_outbox_service.schedule_or_embed_candidate",
        AsyncMock(return_value=True),
    )
    try:
        await candidates_api._enrich_candidate_from_document_task(
            candidate_id, document_id, digest
        )
        async with AsyncSessionLocal() as db:
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )
        assert [s["name"] for s in candidate.skills] == ["Rust"]
        assert candidate.cv_extracted_data.get("_manual_override_skills") is True
        assert candidate.cv_parsed_at is not None
    finally:
        await _cleanup(candidate_id)


@pytest.mark.asyncio
async def test_new_primary_cv_keeps_manual_years_education_and_summary(
    app_client, app_auth_headers, monkeypatch
):
    """12.10.2026 (decyzja Artura): ręczna poprawka lat doświadczenia,
    wykształcenia i podsumowania zostaje po odczycie nowego głównego CV.

    Odczyt wgranego CV odświeża profil (`CvWritePolicy.REFRESH`), a blokadę
    przy edycji dostawały dotąd tylko umiejętności i historia pracy.
    """
    from app.api import candidates as candidates_api
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import select

    first, last = "Anna", f"Testowa{uuid.uuid4().hex[:6]}"
    candidate_id, document_id, digest = await _seed(first, last)
    edits = {
        "years_it_experience": 11,
        "education": [{"school": "Wpisana ręcznie"}],
        "ai_summary": "Podsumowanie rekrutera.",
    }

    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "Anna Testowa — Python developer",
    )
    monkeypatch.setattr(
        "app.services.cv_parser.parse_cv",
        AsyncMock(
            return_value={
                **_parsed(first, last, with_languages=False),
                "education": [{"school": "Z nowego CV"}],
                "professional_profile": "Profil z nowego CV.",
            }
        ),
    )
    monkeypatch.setattr(
        "app.services.index_outbox_service.schedule_or_embed_candidate",
        AsyncMock(return_value=True),
    )
    try:
        patched = await app_client.patch(
            f"/api/candidates/{candidate_id}", json=edits, headers=app_auth_headers
        )
        assert patched.status_code == 200, patched.text

        await candidates_api._enrich_candidate_from_document_task(
            candidate_id, document_id, digest
        )
        async with AsyncSessionLocal() as db:
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )

        assert candidate.years_it_experience == 11
        assert candidate.education == [{"school": "Wpisana ręcznie"}]
        assert candidate.ai_summary == "Podsumowanie rekrutera."
        for field in edits:
            assert candidate.cv_extracted_data.get(f"_manual_override_{field}") is True
        # Pola bez ręcznej poprawki odświeżają się jak dotąd.
        assert [s["name"] for s in candidate.skills] == ["Python"]
        assert candidate.cv_parsed_at is not None
    finally:
        await _cleanup(candidate_id)


@pytest.mark.asyncio
async def test_resending_the_same_value_does_not_lock_the_field(
    app_client, app_auth_headers
):
    """Blokuje dopiero zmiana wartości — formularz bywa wysyłany w całości."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    candidate_id, _document_id, _digest = await _seed(
        "Anna", f"Testowa{uuid.uuid4().hex[:6]}"
    )
    try:
        async with AsyncSessionLocal() as db:
            row = await db.get(Candidate, candidate_id)
            row.years_it_experience = 4
            await db.commit()

        same = await app_client.patch(
            f"/api/candidates/{candidate_id}",
            json={"years_it_experience": 4, "notice_period": 30},
            headers=app_auth_headers,
        )
        assert same.status_code == 200, same.text
        async with AsyncSessionLocal() as db:
            row = await db.get(Candidate, candidate_id)
        assert not (row.cv_extracted_data or {}).get(
            "_manual_override_years_it_experience"
        )
    finally:
        await _cleanup(candidate_id)


@pytest.mark.asyncio
async def test_wrong_person_cv_uploaded_as_primary_keeps_the_profile(
    app_client, app_auth_headers, monkeypatch
):
    """12.10.2026: nowe CV jest domyślnie głównym, a bramka tożsamości biegnie w tle.

    Upload przejmuje główne CV i `cv_filename` od razu. Gdy plik okaże się CV
    innej osoby, profil ma dalej opisywać właściwą osobę z POPRZEDNIEGO CV,
    a to CV ma wrócić jako główne. Do tej poprawki kwarantanna kasowała tekst
    CV, podsumowanie i wektor i zostawiała kandydata bez głównego CV. Test idzie
    przez prawdziwą trasę, bo to ona podaje, które CV zostało zastąpione.
    """
    from app.api import candidates as candidates_api
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument
    from sqlalchemy import select

    first, last = "Anna", f"Testowa{uuid.uuid4().hex[:6]}"
    candidate_id, document_id, digest = await _seed(first, last)
    parse = AsyncMock(return_value=_parsed(first, last, with_languages=False))
    monkeypatch.setattr(
        "app.services.cv_text_extractor.extract_text",
        lambda *_args, **_kwargs: "CV — Python developer",
    )
    monkeypatch.setattr("app.services.cv_parser.parse_cv", parse)
    monkeypatch.setattr(
        "app.services.index_outbox_service.schedule_or_embed_candidate",
        AsyncMock(return_value=True),
    )
    try:
        # Profil zasilony pierwszym, właściwym CV.
        await candidates_api._enrich_candidate_from_document_task(
            candidate_id, document_id, digest
        )

        parse.return_value = _parsed("Zupelnie", "Inny", with_languages=False)
        uploaded = await app_client.post(
            f"/api/candidates/{candidate_id}/documents",
            headers=app_auth_headers,
            files={
                "file": (
                    "cv-innej-osoby.pdf",
                    f"%PDF-1.4 {uuid.uuid4().hex}".encode(),
                    "application/pdf",
                )
            },
            data={"document_kind": "cv", "is_primary": "true"},
        )
        assert uploaded.status_code == 201, uploaded.text
        new_id = uploaded.json()["id"]

        async with AsyncSessionLocal() as db:
            candidate = await db.scalar(
                select(Candidate).where(Candidate.id == candidate_id)
            )
            primary = {
                row.id: row.is_primary
                for row in (
                    await db.scalars(
                        select(CandidateDocument).where(
                            CandidateDocument.candidate_id == candidate_id
                        )
                    )
                ).all()
            }

        assert primary == {document_id: True, new_id: False}
        assert candidate.cv_filename == "cv-testowe.pdf"
        assert candidate.raw_cv_text
        assert candidate.cv_parsed_at is not None
        assert [s["name"] for s in candidate.skills] == ["Python"]
        assert candidate.cv_extracted_data["_identity_quarantine_source"] == {
            "kind": "document",
            "id": new_id,
        }
    finally:
        await _cleanup(candidate_id)
