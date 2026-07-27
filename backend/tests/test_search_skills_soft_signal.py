"""SEARCH-P0-03 — skill chips rank, they never cut.

The structured filter AND-ed a substring ILIKE (over the `skills`+`tags` text)
for every skills_must chip. That column is empty for ~99% of imported
candidates and the substring is imprecise ('Go' matches 'Django'), so a
candidate the SCORER rates highly was cut from the list before ranking. Now
skills_must / skills_any are a soft signal: ``build_structured_filter`` omits
them (no cut) and ``skills_soft_rank`` ranks matchers to the top. Only
``skills_none`` stays a hard exclusion.

Behavioural against a real Postgres: two candidates, one with the skill and one
without; a ``skills_must`` search returns BOTH (proving no cut) with the matcher
first, while a ``skills_none`` search excludes the holder.

The imprecision itself is now fixed too. ``_skill_match`` matches the QUOTED
JSON token (``"Go"``) instead of a bare substring (``%Go%``), because both
columns are JSONB and every value is quoted in the dump. That mattered most for
``skills_none``, the one chip that really cuts: "nie ma Go" used to drop every
Django (and Golang, and MongoDB) developer from the result set with no way for
the recruiter to notice. The Go/Django pair below pins that in both directions.
"""

from __future__ import annotations

import uuid

from sqlalchemy import and_, select, true

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.schemas.candidate_search import CandidateSearchRequest
from app.services.structured_candidate_search import (
    build_structured_filter,
    skills_soft_rank,
)


def test_soft_rank_none_without_chips() -> None:
    assert skills_soft_rank(CandidateSearchRequest()) is None


def test_inclusion_chips_are_not_hard_filters() -> None:
    """skills_must / skills_any must NOT appear in the hard WHERE; skills_none must."""
    inc = build_structured_filter(
        CandidateSearchRequest(skills_must=["Python"], skills_any=["Go"])
    )
    assert inc == [], "skills_must/any still hard-filter (SEARCH-P0-03 regressed)"

    exc = build_structured_filter(CandidateSearchRequest(skills_none=["PHP"]))
    assert len(exc) == 1, "skills_none must remain a hard exclusion"
    assert skills_soft_rank(CandidateSearchRequest(skills_must=["Python"])) is not None


async def _seed_pair() -> tuple[int, int]:
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        has = Candidate(name="Py", lastname=f"Dev-{u}", skills=[{"name": "Python"}])
        without = Candidate(name="Ja", lastname=f"Dev-{u}", skills=[{"name": "Java"}])
        db.add_all([has, without])
        await db.commit()
        return has.id, without.id


async def _run(req: CandidateSearchRequest, scope_ids: list[int]) -> list[int]:
    clauses = build_structured_filter(req)
    where = and_(*clauses) if clauses else true()
    q = select(Candidate.id).where(where, Candidate.id.in_(scope_ids))
    rank = skills_soft_rank(req)
    if rank is not None:
        q = q.order_by(rank.desc(), Candidate.id.asc())
    async with AsyncSessionLocal() as db:
        return [r for r in (await db.execute(q)).scalars().all()]


async def test_must_chip_does_not_cut_and_ranks_matcher_first() -> None:
    has_id, without_id = await _seed_pair()
    result = await _run(
        CandidateSearchRequest(skills_must=["Python"]), [has_id, without_id]
    )
    assert set(result) == {has_id, without_id}, (
        "a non-matching candidate was cut — skills_must still hard-filters"
    )
    assert result[0] == has_id, "the skill matcher must rank first"


async def test_none_chip_still_excludes_holder() -> None:
    has_id, without_id = await _seed_pair()
    result = await _run(
        CandidateSearchRequest(skills_none=["Python"]), [has_id, without_id]
    )
    assert has_id not in result, "skills_none must exclude the Python holder"
    assert without_id in result


async def _seed_go_django() -> tuple[int, int]:
    """One real Go developer, one Django developer who has never touched Go."""
    u = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        go = Candidate(name="Go", lastname=f"Dev-{u}", skills=[{"name": "Go"}])
        django = Candidate(name="Dj", lastname=f"Dev-{u}", skills=[{"name": "Django"}])
        db.add_all([go, django])
        await db.commit()
        return go.id, django.id


async def test_none_chip_does_not_exclude_substring_lookalikes() -> None:
    """'nie ma Go' must not silently drop every Django developer.

    The old bare ``%Go%`` ILIKE over the JSON dump also matched ``Django``, so a
    hard exclusion chip removed candidates who plainly satisfied it. Matching
    the quoted token ``"Go"`` makes the test exact.
    """
    go_id, django_id = await _seed_go_django()
    result = await _run(CandidateSearchRequest(skills_none=["Go"]), [go_id, django_id])
    assert go_id not in result, "skills_none must still exclude the real Go dev"
    assert django_id in result, (
        "Django developer was excluded by 'nie ma Go' — substring match regressed"
    )


async def test_soft_rank_does_not_reward_substring_lookalikes() -> None:
    """The ranking signal must not treat Django as a Go match either."""
    go_id, django_id = await _seed_go_django()
    result = await _run(CandidateSearchRequest(skills_must=["Go"]), [go_id, django_id])
    assert set(result) == {go_id, django_id}, "inclusion chips must never cut"
    assert result[0] == go_id, "the real Go dev must outrank the Django dev"
