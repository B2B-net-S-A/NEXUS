"""Zapytania o pary na bardzo dużej tablicy (09.11.2026) — prawdziwy Postgres.

`GET /api/pipeline/kanban/3413` (14 679 kart) dawał 500: lista par w
`(a, b) IN ((…), (…))` rozwija się w Postgresie w zagnieżdżone OR i powyżej
6–8 tys. par kończy się `stack depth limit exceeded`. Pary idą teraz dwiema
tablicami przez `unnest`, więc ich liczba nie zmienia głębokości zapytania.

Dane fikcyjne.
"""

from __future__ import annotations

import pytest

from app.core.database import AsyncSessionLocal
from app.models.cv_generated_document import CvGeneratedDocument
from app.services.move_requirements import company_cv_refs
from app.services.recommendation_cards import stage_rate_pairs
from tests.test_stage_cv_upload import _client_world

_NO_SUCH_JOB = 2_000_000_000


@pytest.mark.asyncio
async def test_board_with_tens_of_thousands_of_pairs_does_not_overflow() -> None:
    pairs = [(candidate, _NO_SUCH_JOB) for candidate in range(1, 15_001)]

    async with AsyncSessionLocal() as db:
        assert await company_cv_refs(db, pairs) == {}


@pytest.mark.asyncio
async def test_stage_rate_pairs_survive_a_huge_board() -> None:
    pairs = [(candidate, _NO_SUCH_JOB) for candidate in range(1, 15_001)]

    async with AsyncSessionLocal() as db:
        assert await stage_rate_pairs(db, pairs) == set()


@pytest.mark.asyncio
async def test_pairs_stay_pairs_across_jobs() -> None:
    """Para to kandydat razem z rekrutacją, nie iloczyn obu list: dokument
    drugiej osoby w pierwszej rekrutacji nie należy do żadnej z pytanych par."""
    first = await _client_world(stage="verified", primary_cv=False)
    second = await _client_world(stage="verified", primary_cv=False)
    pair_first = (first["candidate_id"], first["job_id"])
    pair_second = (second["candidate_id"], second["job_id"])

    async with AsyncSessionLocal() as db:
        document = CvGeneratedDocument(
            candidate_id=pair_first[0],
            job_id=pair_first[1],
            candidate_name="Ewa Fikcyjna",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="cv.docx",
            status="ready",
            render_payload={"name": "Ewa Fikcyjna"},
        )
        crossed_document = CvGeneratedDocument(
            candidate_id=pair_second[0],
            job_id=pair_first[1],
            candidate_name="Ewa Fikcyjna",
            language="pl",
            mode="new",
            content_mode="polished",
            filename="obca-para.docx",
            status="ready",
            render_payload={"name": "Ewa Fikcyjna"},
        )
        db.add_all([document, crossed_document])
        await db.commit()
        document_id = document.id

    async with AsyncSessionLocal() as db:
        refs = await company_cv_refs(db, [pair_first, pair_second])

    assert set(refs) == {pair_first}
    assert refs[pair_first]["generated_document_id"] == document_id
