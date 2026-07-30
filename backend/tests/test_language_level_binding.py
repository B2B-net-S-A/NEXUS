"""Real-DB regressions for normalized candidate-language search facts.

Runs against the CI postgres service (``DATABASE_URL``); rows are inserted with
``flush()`` and rolled back, so no cleanup or committed state leaks.
"""

from __future__ import annotations

from typing import Any

import pytest_asyncio
from sqlalchemy import select

# Register every mapper before ``Candidate()`` triggers configuration. The
# ``app.models`` aggregator pulls in the bulk; ``skill`` is imported explicitly
# because ``CortexSkillFact`` has a ``relationship("Skill")`` the aggregator
# doesn't otherwise resolve.
import app.models  # noqa: F401
import app.models.skill  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_language import CandidateLanguage
from app.schemas.candidate_search import (
    CandidateSearchRequest,
    LanguageRequirement,
)
from app.services.candidate_language_writer import normalize_language_payload
from app.services.structured_candidate_search import build_structured_filter


@pytest_asyncio.fixture
async def db():
    """A session whose writes are rolled back at teardown (test isolation)."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.rollback()


async def _seed(db, languages: Any) -> int:
    """Insert one candidate with the given ``languages`` blob; return its id.

    Uses ``flush`` (no commit) so the row is visible inside this transaction
    only and disappears on rollback.
    """
    cand = Candidate(name="LangTest", lastname="Case", languages=languages)
    db.add(cand)
    await db.flush()
    normalized, _invalid = normalize_language_payload(languages)
    for language in normalized:
        db.add(
            CandidateLanguage(
                candidate_id=cand.id,
                language_code=language.language_code,
                language_name=language.language_name,
                cefr_level=language.cefr_level,
                is_native=language.is_native,
                is_level_unknown=language.is_level_unknown,
                provenance="legacy",
                manual_lock=False,
                version=1,
            )
        )
    await db.flush()
    return cand.id


async def _matching_ids(
    db, seeded_ids: list[int], req: CandidateSearchRequest
) -> set[int]:
    clauses = build_structured_filter(req)
    stmt = select(Candidate.id).where(Candidate.id.in_(seeded_ids), *clauses)
    rows = (await db.execute(stmt)).scalars().all()
    return set(rows)


def _req_en_b2() -> CandidateSearchRequest:
    return CandidateSearchRequest(
        languages=[LanguageRequirement(code="EN", min_level="B2")]
    )


async def test_array_shape_binds_code_and_level_per_element(db):
    # A: English at C1 → satisfies EN>=B2.
    a = await _seed(db, [{"lang": "EN", "level": "C1"}])
    # B (the bug case): English present (A2) AND C2 present (on German), but the
    # C2 is NOT English → must NOT satisfy EN>=B2.
    b = await _seed(db, [{"lang": "EN", "level": "A2"}, {"lang": "DE", "level": "C2"}])
    # C: no English at all → no match.
    c = await _seed(db, [{"lang": "PL", "level": "C2"}])

    matched = await _matching_ids(db, [a, b, c], _req_en_b2())

    assert matched == {a}, f"expected only candidate A to match EN>=B2, got {matched}"


async def test_code_alias_and_case_are_folded(db):
    # ``code`` is an accepted alias for ``lang``; both fields are case-folded.
    a = await _seed(db, [{"code": "en", "level": "c1"}])
    # Reverse key order must not matter (object field access, not text order).
    b = await _seed(db, [{"level": "B2", "lang": "EN"}])
    # Below threshold → excluded.
    c = await _seed(db, [{"lang": "EN", "level": "A2"}])

    matched = await _matching_ids(db, [a, b, c], _req_en_b2())

    assert matched == {a, b}, f"expected A and B, got {matched}"


async def test_flat_map_shape_binds_per_element(db):
    # Flat map: the key IS the code, the value its level.
    # A: {"EN": "C1"} → match.
    a = await _seed(db, {"EN": "C1"})
    # B (bug case for the map shape): EN is A2, C2 belongs to DE → no match.
    b = await _seed(db, {"EN": "A2", "DE": "C2"})
    # C: no English → no match.
    c = await _seed(db, {"PL": "native"})

    matched = await _matching_ids(db, [a, b, c], _req_en_b2())

    assert matched == {a}, f"expected only A to match EN>=B2 (map shape), got {matched}"


async def test_empty_and_null_languages_never_match(db):
    a = await _seed(db, [])
    b = await _seed(db, None)

    matched = await _matching_ids(db, [a, b], _req_en_b2())

    assert matched == set(), f"empty/null languages must not match, got {matched}"


async def test_native_matches_but_unknown_does_not(db):
    native = await _seed(db, [{"code": "EN", "name": "English", "level": "native"}])
    unknown = await _seed(db, [{"code": "EN", "name": "English", "level": "advanced"}])

    matched = await _matching_ids(db, [native, unknown], _req_en_b2())

    assert matched == {native}
