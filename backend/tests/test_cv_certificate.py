"""Certyfikat wgrany jako CV nie zostaje głównym CV (26.11.2026).

Kopia produkcji z 26.11.2026: u 2 z 66 675 osób tekst CV w profilu był
certyfikatem (PRINCE2 wgrany jako „CV”, certyfikat Pega jako główne CV).
Formularz CV klienta i generator nie miały wtedy z czego czytać. Dane
fikcyjne, w kształcie tamtych plików.
"""

from __future__ import annotations

import uuid

import pytest

from app.services.cv_certificate import looks_like_certificate_text

PRINCE2 = (
    "This is to certify\nAnna Fikcyjna\nHas achieved the certification\n"
    "PRINCE2 Project Management Foundation VERSION 7\nEffective from: 27 May 2026\n"
    "Renew by: 27 May 2029\nCertificate Number Candidate Number\nGR000000000AF"
)
PEGA = (
    "Certificate Of Achievement\nAwarded to Jan Przykładowy\nIn Recognition of "
    "Successful Completion of Certified Pega Senior System Architect\n"
    "Awarded on July 24, 2019"
)
ZASWIADCZENIE = (
    "ZAŚWIADCZENIE\nNiniejszym zaświadcza się, że Anna Fikcyjna ukończyła szkolenie "
    "ISTQB Foundation Level w dniach 10–12.03.2025."
)
CV_WITH_CERTIFICATES = (
    "Anna Fikcyjna\nTester oprogramowania\nDoświadczenie zawodowe\n"
    "03.2025 – obecnie Tester / Firma Alfa\nCertyfikaty\n"
    "ISTQB Foundation Level — Certificate Number 12345 (has successfully passed)"
)


@pytest.mark.parametrize("text", [PRINCE2, PEGA, ZASWIADCZENIE])
def test_certificate_text_is_recognised(text: str) -> None:
    assert looks_like_certificate_text(text)


@pytest.mark.parametrize(
    "text",
    [
        CV_WITH_CERTIFICATES,
        "",
        None,
        # Długi tekst to CV, choćby bez nazw sekcji (nagłówki rozstrzelone
        # „W O R K H I S T O R Y” w CV z kopii produkcji).
        PRINCE2 + "\n" + "Projekt dla banku, analiza wymagań. " * 200,
    ],
)
def test_cv_text_is_not_a_certificate(text: str | None) -> None:
    assert not looks_like_certificate_text(text)


async def _seed_person_with_cv_and_certificate() -> tuple[int, int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna",
            lastname=f"Certyfikat-{uuid.uuid4().hex[:6]}",
            email=f"cv-cert-{uuid.uuid4().hex[:8]}@example.com",
            cv_filename="prince2.pdf",
            raw_cv_text="Anna Fikcyjna\nDoświadczenie zawodowe\nTester / Firma Alfa",
        )
        db.add(candidate)
        await db.flush()
        own_cv = CandidateDocument(
            candidate_id=candidate.id,
            filename="cv_anna.pdf",
            document_kind=CandidateDocumentKind.cv,
            is_primary=False,
            content_sha256="a" * 64,
            file_content=b"%PDF-1.4 cv",
        )
        certificate = CandidateDocument(
            candidate_id=candidate.id,
            filename="prince2.pdf",
            document_kind=CandidateDocumentKind.cv,
            is_primary=True,
            content_sha256="b" * 64,
            file_content=b"%PDF-1.4 cert",
        )
        db.add_all([own_cv, certificate])
        await db.commit()
        return candidate.id, own_cv.id, certificate.id


async def test_uploaded_certificate_hands_primary_back_and_keeps_the_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.api import candidates as api
    from app.core.database import AsyncSessionLocal
    from app.models.activity import Activity
    from app.models.candidate import Candidate
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services import cv_text_extractor
    from app.services.candidate_identity_quarantine import ReplacedPrimaryCv
    from sqlalchemy import select

    (
        candidate_id,
        own_cv_id,
        certificate_id,
    ) = await _seed_person_with_cv_and_certificate()
    monkeypatch.setattr(cv_text_extractor, "extract_cv_text", lambda *_a: PRINCE2)

    async def _no_model(*_a, **_k):  # pragma: no cover - wywołanie = błąd testu
        raise AssertionError("certyfikat nie idzie do odczytu modelem")

    monkeypatch.setattr("app.services.cv_parser.parse_cv", _no_model)

    await api._enrich_candidate_from_document_task(
        candidate_id,
        certificate_id,
        "b" * 64,
        replaced_primary=ReplacedPrimaryCv(
            document_id=own_cv_id, cv_filename="cv_anna.pdf"
        ),
        certificate_check=True,
    )

    async with AsyncSessionLocal() as db:
        certificate = await db.get(CandidateDocument, certificate_id)
        own_cv = await db.get(CandidateDocument, own_cv_id)
        candidate = await db.get(Candidate, candidate_id)
        logged = await db.scalar(
            select(Activity.action).where(
                Activity.entity_id == candidate_id,
                Activity.action == "cv_upload_is_certificate",
            )
        )
    assert certificate.document_kind == CandidateDocumentKind.certificate
    assert certificate.is_primary is False
    assert own_cv.is_primary is True
    assert candidate.cv_filename == "cv_anna.pdf"
    assert candidate.raw_cv_text.startswith("Anna Fikcyjna\nDoświadczenie")
    assert logged == "cv_upload_is_certificate"


async def test_chosen_primary_is_not_checked(monkeypatch: pytest.MonkeyPatch) -> None:
    """„Ustaw jako główne” to świadomy wybór rekrutera — plik zostaje CV."""
    from app.api import candidates as api
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
    from app.services import cv_text_extractor

    (
        candidate_id,
        _own_cv_id,
        certificate_id,
    ) = await _seed_person_with_cv_and_certificate()
    monkeypatch.setattr(cv_text_extractor, "extract_cv_text", lambda *_a: PRINCE2)

    async def _parsed(*_a, **_k) -> dict:
        return {}

    monkeypatch.setattr("app.services.cv_parser.parse_cv", _parsed)

    await api._enrich_candidate_from_document_task(
        candidate_id, certificate_id, "b" * 64
    )

    async with AsyncSessionLocal() as db:
        certificate = await db.get(CandidateDocument, certificate_id)
    assert certificate.document_kind == CandidateDocumentKind.cv
