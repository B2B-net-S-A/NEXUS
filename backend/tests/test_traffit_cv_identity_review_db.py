"""Pliki CV z importu Traffita przechodzą bramkę tożsamości (Postgres).

Pomiar 09.11.2026: bramka widziała 157 z 84 576 plików CV z Traffita, więc cudze
CV stało jako bieżące i kopiowało się na etapy. Bieg jest wąski, nie wpisuje
faktów i niczego nie wrzuca do kwarantanny. Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.cli import traffit_cv_identity_review as review_run
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_source_identity_review import (
    CandidateSourceIdentityReview,
)
from app.services import candidate_identity_quarantine as quarantine

pytestmark = pytest.mark.asyncio

_FILLER = "Doswiadczenie zawodowe i projekty informatyczne. " * 12


def _surname() -> str:
    return f"Fikcyjna{uuid.uuid4().hex[:8]}"


async def _profile(*, in_text: bool = False, phone: str | None = None) -> int:
    surname = _surname()
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Anna",
            lastname=surname,
            phone=phone,
            raw_cv_text=_FILLER + (f"Anna {surname}" if in_text else "Inna Osoba"),
            cv_extracted_data={},
        )
        db.add(candidate)
        await db.commit()
        return candidate.id


async def _document(
    candidate_id: int, *, source: str = "traffit", filename: str = "cv.pdf"
) -> int:
    async with AsyncSessionLocal() as db:
        document = CandidateDocument(
            candidate_id=candidate_id,
            filename=filename,
            file_content=b"%PDF-1.4 fikcyjne CV",
            document_kind=CandidateDocumentKind.cv,
            external_source=source,
        )
        db.add(document)
        await db.commit()
        return document.id


async def _targets(*, extra: tuple[int, ...] = ()) -> set[int]:
    async with AsyncSessionLocal() as db:
        return {
            target.document_id
            for target in await review_run.select_targets(db, candidate_ids=extra)
        }


async def _review(candidate_id: int, document_id: int) -> CandidateSourceIdentityReview:
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateSourceIdentityReview).where(
                CandidateSourceIdentityReview.candidate_id == candidate_id,
                CandidateSourceIdentityReview.source_kind == "document",
                CandidateSourceIdentityReview.source_id == document_id,
            )
        )
        assert row is not None
        return row


def _only_this_file(
    monkeypatch: pytest.MonkeyPatch, candidate_id: int, document_id: int
) -> None:
    """Inne testy zostawiają w bazie swoje pliki, a bieg bierze wszystkie."""

    monkeypatch.setattr(
        review_run,
        "select_targets",
        AsyncMock(return_value=[review_run.Target(document_id, candidate_id)]),
    )


def _stub_read(monkeypatch: pytest.MonkeyPatch, parsed: dict | None) -> AsyncMock:
    parse = AsyncMock(return_value=parsed)
    monkeypatch.setattr(review_run, "parse_cv_with_claude", parse)
    monkeypatch.setattr(
        review_run, "_document_text", AsyncMock(return_value=_FILLER * 2)
    )
    monkeypatch.setattr(review_run, "SLEEP_BETWEEN_CALLS_S", 0)
    return parse


async def test_scope_is_traffit_file_whose_name_the_cv_text_does_not_have() -> None:
    foreign = await _profile()
    own = await _profile(in_text=True)
    uploaded = await _profile()
    foreign_doc = await _document(foreign)
    own_doc = await _document(own)
    uploaded_doc = await _document(uploaded, source="manual")

    targets = await _targets()

    assert foreign_doc in targets
    assert own_doc not in targets
    assert uploaded_doc not in targets


async def test_listed_profile_joins_the_scope_even_with_its_name_in_the_text() -> None:
    twin = await _profile(in_text=True)
    twin_doc = await _document(twin)

    assert twin_doc in await _targets(extra=(twin,))


async def test_scope_skips_a_reviewed_file() -> None:
    candidate_id = await _profile()
    document_id = await _document(candidate_id)
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        await quarantine.record_detected_identity(
            db,
            candidate=candidate,
            source_kind="document",
            source_id=document_id,
            observed_first_name="Anna",
            observed_last_name=candidate.lastname,
            provenance="cv_parser:document",
        )
        await db.commit()

    assert document_id not in await _targets()


async def test_rehearsal_reads_nothing_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id = await _profile()
    document_id = await _document(candidate_id)
    parse = _stub_read(monkeypatch, {"first_name": "Piotr", "last_name": "Inny"})

    stats = await review_run.run(apply=False, candidate_ids=(candidate_id,))

    parse.assert_not_awaited()
    assert stats["targets"] >= 1
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CandidateSourceIdentityReview.id).where(
                    CandidateSourceIdentityReview.source_id == document_id,
                    CandidateSourceIdentityReview.source_kind == "document",
                )
            )
            is None
        )


async def test_read_naming_someone_else_is_held_and_changes_no_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id = await _profile()
    document_id = await _document(candidate_id)
    _stub_read(
        monkeypatch,
        {"first_name": "Piotr", "last_name": "Malinowski", "skills": ["Python"]},
    )

    _only_this_file(monkeypatch, candidate_id, document_id)

    stats = await review_run.run(apply=True)

    review = await _review(candidate_id, document_id)
    assert stats["doubt"] == 1
    assert candidate_id in stats["doubt_candidate_ids"]
    assert review.decision == "inconclusive"
    assert review.evidence[quarantine.MISMATCH_HELD_EVIDENCE] is True
    assert review.is_quarantined is False
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        assert candidate.raw_cv_text
        assert not candidate.skills


async def test_read_without_a_name_leaves_no_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidate_id = await _profile()
    document_id = await _document(candidate_id)
    _stub_read(monkeypatch, {"first_name": None, "last_name": None})

    _only_this_file(monkeypatch, candidate_id, document_id)

    stats = await review_run.run(apply=True)

    assert stats["no_name_read"] == 1
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(
                select(CandidateSourceIdentityReview.id).where(
                    CandidateSourceIdentityReview.source_id == document_id,
                    CandidateSourceIdentityReview.source_kind == "document",
                )
            )
            is None
        )


async def test_phone_counts_as_shared_only_with_another_profile() -> None:
    number = f"6{uuid.uuid4().int % 10**8:08d}"
    alone = await _profile(phone=f"{number[:3]} {number[3:6]} {number[6:]}")
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, alone)
        assert await quarantine._phone_on_other_profile(db, candidate) is False

    await _profile(phone=f"+48{number}")
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, alone)
        assert await quarantine._phone_on_other_profile(db, candidate) is True


async def test_documents_list_says_which_file_may_be_someone_elses(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    candidate_id = await _profile()
    doubtful = await _document(candidate_id, filename="a.pdf")
    other = await _document(candidate_id, filename="b.pdf")
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        await quarantine.record_detected_identity(
            db,
            candidate=candidate,
            source_kind="document",
            source_id=doubtful,
            observed_first_name="Piotr",
            observed_last_name="Malinowski",
            provenance="cv_parser:traffit_file_review",
            hold_mismatch_for_review=True,
        )
        await db.commit()

    response = await app_client.get(
        f"/api/candidates/{candidate_id}/documents", headers=app_auth_headers
    )

    assert response.status_code == 200, response.text
    flags = {doc["id"]: doc["identity_doubt"] for doc in response.json()}
    assert flags == {doubtful: True, other: False}


async def test_stage_copy_of_a_doubtful_file_warns_by_its_filename() -> None:
    candidate_id = await _profile()
    doubtful = await _document(candidate_id, filename="plik-z-traffita.pdf")
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        await quarantine.record_detected_identity(
            db,
            candidate=candidate,
            source_kind="document",
            source_id=doubtful,
            observed_first_name="Piotr",
            observed_last_name="Malinowski",
            provenance="cv_parser:traffit_file_review",
            hold_mismatch_for_review=True,
        )
        await db.commit()

    def copy(filename: str | None) -> SimpleNamespace:
        return SimpleNamespace(
            candidate_id=candidate_id,
            original_cv_filename=filename,
            original_cv_sha256=None,
        )

    async with AsyncSessionLocal() as db:
        assert await quarantine.stage_copy_identity_doubt(
            db, copy("plik-z-traffita.pdf")
        )
        assert not await quarantine.stage_copy_identity_doubt(db, copy("inny.pdf"))
        assert not await quarantine.stage_copy_identity_doubt(db, copy(None))
