"""Firmowe CV („B2B_….docx”) nie jest domyślnym źródłem, gdy jest CV kandydata (02.11.2026).

Zgłoszenie rekruterki: po wgraniu firmowego CV jako głównego następna generacja
czytała je jak oryginał, więc błędy i skróty firmowego CV szły dalej. Pomiar na
kopii produkcji 02.11.2026: 1544 osoby mają taki plik jako bieżące CV, 93 z nich
mają też plik rodzaju „cv”, 426 kopii „Oryginał CV” z 30 dni to firmowy Word.

Kontrakty:

- osoba z CV kandydata dostaje je zamiast firmowego Worda: generator, kopia
  „Oryginał CV” i plik domyślny w karcie;
- osoba z samym firmowym plikiem generuje dalej jak dotąd;
- obok firmowego pliku liczy się tylko rodzaj „cv”: „other” z Traffita bywa
  czymkolwiek, a co piąty taki plik Word to i tak firmowe CV pod inną nazwą;
- PDF z „B2B” w nazwie zostaje CV kandydata: 5 takich źródeł z 30 dni nie miało
  układu szablonu;
- plik wskazany przez rekrutera wygrywa zawsze.

Dane fikcyjne.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.models.candidate_source_identity_review import CandidateSourceIdentityReview
from app.models.candidate_stage_cv import CandidateStageCV
from app.services.client_cv_upload import looks_like_client_cv
from app.services.cv_generator_b2b.standalone_service import (
    list_candidate_cv_sources,
    load_candidate_generation_source,
)
from app.services.cv_source import client_cv_file_clause, get_current_cv
from tests.test_stage_cv_upload import _client_world

FIRM = "B2B_Ewa_Fikcyjna_Analityk.docx"
OWN = "ewa-cv.pdf"
NOW = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)


def _doc(
    candidate_id: int,
    filename: str,
    *,
    primary: bool = False,
    kind: CandidateDocumentKind = CandidateDocumentKind.cv,
    age_days: int = 0,
    **extra,
) -> CandidateDocument:
    return CandidateDocument(
        candidate_id=candidate_id,
        filename=filename,
        file_content=filename.encode(),
        document_kind=kind,
        is_primary=primary,
        uploaded_at=NOW - timedelta(days=age_days),
        **extra,
    )


async def _person(*rows: tuple[str, dict]) -> tuple[int, dict[str, int]]:
    async with AsyncSessionLocal() as db:
        candidate = Candidate(name="Ewa", lastname=f"Fikcyjna-{uuid.uuid4().hex[:8]}")
        db.add(candidate)
        await db.flush()
        docs = [_doc(candidate.id, name, **options) for name, options in rows]
        db.add_all(docs)
        await db.flush()
        ids = {doc.filename: doc.id for doc in docs}
        await db.commit()
        return candidate.id, ids


async def _generator_file(candidate_id: int, document_id: Optional[int] = None) -> str:
    async with AsyncSessionLocal() as db:
        source = await load_candidate_generation_source(
            db, candidate_id=candidate_id, stage_id=None, cv_document_id=document_id
        )
    return source.cv_filename


async def _current_file(candidate_id: int) -> str:
    async with AsyncSessionLocal() as db:
        candidate = await db.get(Candidate, candidate_id)
        current = await get_current_cv(db, candidate)
    return current.filename


async def test_candidate_cv_wins_over_a_primary_client_cv() -> None:
    candidate_id, _ = await _person(
        (FIRM, {"primary": True}),
        (OWN, {"age_days": 400}),
    )
    assert await _generator_file(candidate_id) == OWN
    assert await _current_file(candidate_id) == OWN


async def test_person_with_only_a_client_cv_still_generates() -> None:
    candidate_id, _ = await _person((FIRM, {"primary": True}))
    assert await _generator_file(candidate_id) == FIRM
    assert await _current_file(candidate_id) == FIRM


async def test_unclassified_file_does_not_replace_the_client_cv() -> None:
    candidate_id, _ = await _person(
        (FIRM, {"primary": True}),
        ("skan.pdf", {"kind": CandidateDocumentKind.other}),
    )
    assert await _generator_file(candidate_id) == FIRM
    assert await _current_file(candidate_id) == FIRM


async def test_unusable_candidate_cv_does_not_replace_the_client_cv() -> None:
    outdated_id, _ = await _person(
        (FIRM, {"primary": True}), (OWN, {"outdated_at": NOW})
    )
    deleted_id, _ = await _person(
        (FIRM, {"primary": True}), (OWN, {"source_deleted_at": NOW})
    )
    quarantined_id, ids = await _person((FIRM, {"primary": True}), (OWN, {}))
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateSourceIdentityReview(
                candidate_id=quarantined_id,
                source_kind="document",
                source_id=ids[OWN],
                decision="confirmed_mismatch",
                provenance="test",
                detector_version="test",
                reviewed_at=NOW,
            )
        )
        await db.commit()
    for candidate_id in (outdated_id, deleted_id, quarantined_id):
        assert await _generator_file(candidate_id) == FIRM


async def test_pdf_named_b2b_stays_the_candidate_cv() -> None:
    named = "Ewa_Fikcyjna_B2B.pdf"
    candidate_id, _ = await _person((named, {"primary": True}), (OWN, {}))
    assert await _generator_file(candidate_id) == named


async def test_explicitly_chosen_client_cv_is_honoured() -> None:
    candidate_id, ids = await _person((FIRM, {"primary": True}), (OWN, {}))
    assert await _generator_file(candidate_id, ids[FIRM]) == FIRM


async def test_order_of_candidate_files_stays_the_same() -> None:
    candidate_id, _ = await _person(
        ("glowne.pdf", {"primary": True, "age_days": 30}),
        ("nowsze.pdf", {}),
        (FIRM, {"age_days": 1}),
    )
    assert await _generator_file(candidate_id) == "glowne.pdf"


async def test_source_list_starts_with_the_file_the_generator_reads() -> None:
    candidate_id, _ = await _person(
        (FIRM, {"primary": True}),
        (OWN, {"age_days": 10}),
    )
    async with AsyncSessionLocal() as db:
        rows = await list_candidate_cv_sources(db, candidate_id)
    assert [(row["filename"], row["is_primary"]) for row in rows] == [
        (OWN, False),
        (FIRM, True),
    ]


@pytest.mark.parametrize(
    "filename",
    [
        "B2B_Jan.docx",
        "b2b jan.DOCX",
        "Jan-B2B-v2.docx",
        "Jan_B2B.docx",
        "Jan.B2B.docx",
        "HB2B_Jan.docx",
        "Jan_B2Bx.docx",
        "Jan_B2B.pdf",
        "CV.docx",
    ],
)
async def test_sql_clause_mirrors_the_filename_rule(filename: str) -> None:
    candidate_id, ids = await _person((filename, {}))
    async with AsyncSessionLocal() as db:
        matched = await db.scalar(
            select(client_cv_file_clause()).where(
                CandidateDocument.id == ids[filename],
                CandidateDocument.candidate_id == candidate_id,
            )
        )
    assert matched is looks_like_client_cv(filename)


async def _world_with_files(*rows: tuple[str, dict]) -> tuple[dict, dict[str, int]]:
    world = await _client_world(stage="verified", primary_cv=False)
    async with AsyncSessionLocal() as db:
        docs = [_doc(world["candidate_id"], name, **options) for name, options in rows]
        db.add_all(docs)
        await db.flush()
        ids = {doc.filename: doc.id for doc in docs}
        # Stan sprzed poprawki: kopia „Oryginał CV” trzyma firmowy plik.
        firm = next(doc for doc in docs if doc.filename == FIRM)
        firm.content_sha256 = "f" * 64
        row = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == world["stage_id"]
            )
        )
        row.original_cv_sha256 = "f" * 64
        row.original_cv_filename = FIRM
        await db.commit()
    return world, ids


@pytest.mark.asyncio
async def test_card_defaults_to_candidate_cv_over_a_client_cv_stage_copy(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    world, ids = await _world_with_files(
        (FIRM, {"primary": True}),
        (OWN, {"age_days": 10}),
    )
    res = await app_client.get(
        f"/api/candidates/stages/{world['stage_id']}/cv/ai-sources",
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["original_cv"]["document_id"] == ids[OWN]
    # Firmowy plik zostaje do wyboru i nadal mówi, że to kopia z rekrutacji.
    files = {row["document_id"]: row for row in body["cv_files"]}
    assert files[ids[FIRM]]["stage_original"] is True
    assert body["cv_files"][0]["document_id"] == ids[OWN]


@pytest.mark.asyncio
async def test_card_keeps_the_stage_copy_when_only_client_cv_exists(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    world, ids = await _world_with_files(
        (FIRM, {"primary": True}),
        ("skan.pdf", {"kind": CandidateDocumentKind.other}),
    )
    res = await app_client.get(
        f"/api/candidates/stages/{world['stage_id']}/cv/ai-sources",
        headers=app_auth_headers,
    )
    assert res.status_code == 200, res.text
    assert res.json()["original_cv"]["document_id"] == ids[FIRM]
