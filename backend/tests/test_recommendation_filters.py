"""Unit tests for recommendation_filters service.

Pure-function coverage: location match, salary ±tolerance window, competence
category match, and the conflict-decision matrix (blacklist/competitor/nda
hard-drop, current_employment soft-warn).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import AvailabilityStatus, CandidateStatus
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.services import recommendation_filters as rf
from app.core.database import AsyncSessionLocal


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_candidate(**overrides) -> SimpleNamespace:
    base = dict(
        id=42,
        availability_status=AvailabilityStatus.unknown,
        status=CandidateStatus.active,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def make_job(**overrides) -> SimpleNamespace:
    base = dict(
        id=1,
        location=None,
        salary_min=None,
        salary_max=None,
        client_id=None,
        title="Backend Engineer",
        subcategory=None,
        industry=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ── _location_matches ────────────────────────────────────────────────────────


def test_location_matches_substring_either_way():
    j = make_job(location="Warszawa, PL")
    assert rf._location_matches(j, "Warszawa") is True
    assert rf._location_matches(j, "warszawa, pl") is True


def test_location_matches_first_segment_compare():
    j = make_job(location="Kraków, Polska")
    assert rf._location_matches(j, "Kraków, Mazowieckie") is True


def test_location_matches_unknown_passes():
    """Missing data on either side never causes a drop."""
    assert rf._location_matches(make_job(location=None), "Wrocław") is True
    assert rf._location_matches(make_job(location="Lublin"), "") is True


def test_location_matches_rejects_unrelated():
    assert rf._location_matches(make_job(location="Gdańsk"), "Berlin") is False


# ── _salary_in_window ────────────────────────────────────────────────────────


def test_salary_passes_when_user_has_no_bounds():
    assert (
        rf._salary_in_window(
            make_job(salary_min=10000, salary_max=20000), None, None, 0.20
        )
        is True
    )


def test_salary_passes_when_job_has_no_bounds():
    assert rf._salary_in_window(make_job(), 10000, 20000, 0.20) is True


def test_salary_overlap_inside_tolerance():
    j = make_job(salary_min=15000, salary_max=20000)
    # User wants 12000-14000; job pads to [12000, 24000] with 20% tolerance.
    assert rf._salary_in_window(j, 12000, 14000, 0.20) is True


def test_salary_overlap_outside_tolerance_rejected():
    j = make_job(salary_min=15000, salary_max=20000)
    # User wants up to 10000 — below padded job_min (12000).
    assert rf._salary_in_window(j, None, 10000, 0.20) is False


def test_salary_user_min_above_job_max_padded_rejected():
    j = make_job(salary_min=15000, salary_max=20000)
    # Padded job_max = 24000; user min 30000 → no overlap.
    assert rf._salary_in_window(j, 30000, None, 0.20) is False


# ── _competence_category_matches ────────────────────────────────────────────


def test_cc_matches_via_subcategory():
    j = make_job(subcategory="Backend", title="Software Engineer")
    assert rf._competence_category_matches(j, ["Backend"]) is True


def test_cc_matches_via_industry():
    j = make_job(industry="Fintech", title="Engineer")
    assert rf._competence_category_matches(j, ["fintech"]) is True


def test_cc_matches_via_title_fallback():
    j = make_job(title="Senior DevOps Engineer")
    assert rf._competence_category_matches(j, ["devops"]) is True


def test_cc_no_target_passes():
    assert rf._competence_category_matches(make_job(), []) is True
    assert rf._competence_category_matches(make_job(), [""]) is True


def test_cc_unrelated_rejected():
    j = make_job(title="Backend Engineer")
    assert rf._competence_category_matches(j, ["frontend"]) is False


def test_cc_or_combines_multiple_targets():
    """The live call site passes a LIST (`list(filters.competence_category)`),
    so the multi-target OR is the shape that actually ships — and until now no
    test exercised it."""
    j = make_job(title="Backend Engineer")
    assert rf._competence_category_matches(j, ["frontend", "backend"]) is True
    assert rf._competence_category_matches(j, ["frontend", "devops"]) is False


def test_cc_bare_string_is_one_category_not_a_bag_of_letters():
    """Regression guard for the trap that hid the whole file from CI.

    `Sequence[str]` also matches `str`, and iterating a string yields single
    CHARACTERS. Every test above used to pass a bare string, so they asserted
    things like "is 'b' somewhere in 'backend software engineer'" — four of them
    were green for that reason alone, and the one honest negative assertion was
    red. Because that red was read as a production behaviour change, the ENTIRE
    file (28 tests) was --ignore'd in CI and stopped protecting anything.

    The failure mode is what made it survive: not a crash, just a wrong answer
    that looks right.
    """
    j = make_job(title="Backend Engineer")
    assert rf._competence_category_matches(j, "frontend") is False
    assert rf._competence_category_matches(j, "backend") is True
    # 'e' occurs in "backend engineer"; a per-character search would say True.
    assert rf._competence_category_matches(j, "e-commerce") is False


# ── _conflict_decision ───────────────────────────────────────────────────────


def test_conflict_decision_blacklist_drops():
    j = make_job(client_id=10)
    keep, warn = rf._conflict_decision(j, {10: ConflictType.blacklist})
    assert keep is False and warn is None


def test_conflict_decision_competitor_drops():
    j = make_job(client_id=10)
    keep, warn = rf._conflict_decision(j, {10: ConflictType.competitor})
    assert keep is False and warn is None


def test_conflict_decision_nda_drops():
    j = make_job(client_id=10)
    keep, warn = rf._conflict_decision(j, {10: ConflictType.nda})
    assert keep is False and warn is None


def test_conflict_decision_current_employment_soft_warns():
    j = make_job(client_id=10)
    keep, warn = rf._conflict_decision(j, {10: ConflictType.current_employment})
    assert keep is True
    assert warn == "obecnie u tego klienta"


def test_conflict_decision_unrelated_client_passes():
    j = make_job(client_id=99)
    keep, warn = rf._conflict_decision(j, {10: ConflictType.blacklist})
    assert keep is True and warn is None


def test_conflict_decision_no_client_id_passes():
    j = make_job(client_id=None)
    keep, warn = rf._conflict_decision(j, {10: ConflictType.blacklist})
    assert keep is True and warn is None


# ── matches_availability ─────────────────────────────────────────────────────


def test_matches_availability_no_filter_passes():
    c = make_candidate(availability_status=AvailabilityStatus.not_looking)
    assert rf.matches_availability(c, rf.RecommendationFilters()) is True


def test_matches_availability_in_set():
    c = make_candidate(availability_status=AvailabilityStatus.actively_looking)
    flt = rf.RecommendationFilters(
        availability=[
            AvailabilityStatus.actively_looking,
            AvailabilityStatus.open_to_offers,
        ]
    )
    assert rf.matches_availability(c, flt) is True


def test_matches_availability_outside_set():
    c = make_candidate(availability_status=AvailabilityStatus.not_looking)
    flt = rf.RecommendationFilters(availability=[AvailabilityStatus.actively_looking])
    assert rf.matches_availability(c, flt) is False


# ── apply_user_filters (uses real DB session for conflict load) ──────────────


@pytest.mark.asyncio
async def test_apply_user_filters_drops_by_location():
    """No conflicts, two jobs in different cities."""
    async with AsyncSessionLocal() as db:
        candidate = make_candidate(id=999_001)
        jobs = [make_job(id=1, location="Warszawa"), make_job(id=2, location="Berlin")]
        kept, stats = await rf.apply_user_filters(
            candidate,
            jobs,
            rf.RecommendationFilters(location="Warszawa", industry_blocklist=False),
            db,
        )
        assert [k.job.id for k in kept] == [1]
        assert stats.dropped_location == 1
        assert stats.kept == 1


@pytest.mark.asyncio
async def test_apply_user_filters_drops_by_salary():
    async with AsyncSessionLocal() as db:
        candidate = make_candidate(id=999_002)
        jobs = [
            make_job(id=1, salary_min=20000, salary_max=25000),
            make_job(id=2, salary_min=8000, salary_max=10000),
        ]
        kept, stats = await rf.apply_user_filters(
            candidate,
            jobs,
            rf.RecommendationFilters(
                salary_min=18000, salary_max=22000, industry_blocklist=False
            ),
            db,
        )
        # Job 1 overlaps the user range; job 2 lies far below even with tolerance.
        assert [k.job.id for k in kept] == [1]
        assert stats.dropped_salary == 1


async def _cleanup_seed(*, candidate_id: int, client_id: int) -> None:
    """Raw-SQL cleanup that bypasses ORM cascade traversal.

    The dev DB has migration drift on unrelated tables (talent_pool_memberships
    .marketplace_until missing) that breaks ORM-side relationship loading. Raw
    DELETE statements skip those traversals and only touch the rows we created.
    """
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateConflict).where(
                CandidateConflict.candidate_id == candidate_id
            )
        )
        from app.models.candidate import Candidate as _C
        from app.models.client import Client as _Cl

        await db.execute(delete(_C).where(_C.id == candidate_id))
        await db.execute(delete(_Cl).where(_Cl.id == client_id))
        await db.commit()


async def _seed_candidate_client_conflict(
    *,
    conflict_type: ConflictType,
    expires_at: datetime | None = None,
):
    """Insert a candidate + client + conflict and return their ids.

    Uses a fresh session and commits so subsequent reads in the test see the
    seeded rows. Caller is responsible for `_cleanup_seed`.
    """
    from app.models.candidate import Candidate
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        client = Client(name=f"TestClient_{datetime.now(timezone.utc).timestamp()}")
        db.add(client)
        await db.flush()

        cand = Candidate(name="Filter", lastname="Tester")
        db.add(cand)
        await db.flush()

        db.add(
            CandidateConflict(
                candidate_id=cand.id,
                client_id=client.id,
                type=conflict_type,
                active=True,
                expires_at=expires_at,
            )
        )
        await db.commit()
        return cand.id, client.id


@pytest.mark.asyncio
async def test_apply_user_filters_industry_blocklist_via_conflict():
    """blacklist conflict on client → job dropped."""
    from app.models.candidate import Candidate

    cand_id, client_id = await _seed_candidate_client_conflict(
        conflict_type=ConflictType.blacklist
    )
    try:
        async with AsyncSessionLocal() as db:
            cand = await db.get(Candidate, cand_id)
            jobs = [
                make_job(id=1, client_id=client_id),
                make_job(id=2, client_id=client_id + 9999),  # unrelated
            ]
            kept, stats = await rf.apply_user_filters(
                cand,
                jobs,
                rf.RecommendationFilters(industry_blocklist=True),
                db,
            )
            assert [k.job.id for k in kept] == [2]
            assert stats.dropped_blocklist == 1
    finally:
        await _cleanup_seed(candidate_id=cand_id, client_id=client_id)


@pytest.mark.asyncio
async def test_apply_user_filters_current_employment_soft_warn():
    """current_employment conflict → kept WITH warning."""
    from app.models.candidate import Candidate

    cand_id, client_id = await _seed_candidate_client_conflict(
        conflict_type=ConflictType.current_employment
    )
    try:
        async with AsyncSessionLocal() as db:
            cand = await db.get(Candidate, cand_id)
            jobs = [make_job(id=1, client_id=client_id)]
            kept, stats = await rf.apply_user_filters(
                cand,
                jobs,
                rf.RecommendationFilters(industry_blocklist=True),
                db,
            )
            assert len(kept) == 1
            assert kept[0].warning == "obecnie u tego klienta"
            assert stats.soft_warned == 1
            assert stats.dropped_blocklist == 0
    finally:
        await _cleanup_seed(candidate_id=cand_id, client_id=client_id)


@pytest.mark.asyncio
async def test_apply_user_filters_expired_conflict_ignored():
    """Conflict with `expires_at` in the past must NOT block the job."""
    from app.models.candidate import Candidate

    cand_id, client_id = await _seed_candidate_client_conflict(
        conflict_type=ConflictType.blacklist,
        expires_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    try:
        async with AsyncSessionLocal() as db:
            cand = await db.get(Candidate, cand_id)
            jobs = [make_job(id=1, client_id=client_id)]
            kept, _ = await rf.apply_user_filters(
                cand,
                jobs,
                rf.RecommendationFilters(industry_blocklist=True),
                db,
            )
            # Expired conflict ⇒ no block
            assert [k.job.id for k in kept] == [1]
    finally:
        await _cleanup_seed(candidate_id=cand_id, client_id=client_id)
