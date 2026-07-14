"""Unit tests dla `app.services.marketplace_service`.

Pure-function testy dla `is_significant_job_update` + integration testy dla
poolowo-memberowej logiki używające AsyncSessionLocal (wymaga DB, migracje
zastosowane).
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest
import pytest_asyncio

from app.core.database import AsyncSessionLocal
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.services.marketplace_service import (
    MARKETPLACE_POOL_NAME,
    add_candidate_to_marketplace,
    auto_sync_marketplace_membership,
    ensure_marketplace_pool,
    is_significant_job_update,
    remove_candidate_from_marketplace,
)


# ══════════════════════════════════════════════════════════════════════════
# Pure function tests — is_significant_job_update
# ══════════════════════════════════════════════════════════════════════════


def test_significant_update_must_skills_added():
    old = {"must_skills": [{"name": "Python"}]}
    new = {"must_skills": [{"name": "Python"}, {"name": "AWS"}]}
    assert is_significant_job_update(old, new) is True


def test_significant_update_must_skills_removed():
    old = {"must_skills": [{"name": "Python"}, {"name": "AWS"}]}
    new = {"must_skills": [{"name": "Python"}]}
    assert is_significant_job_update(old, new) is True


def test_significant_update_nice_skills_changed():
    old = {"nice_skills": [{"name": "Docker"}]}
    new = {"nice_skills": [{"name": "Kubernetes"}]}
    assert is_significant_job_update(old, new) is True


def test_significant_update_skills_reordering_ignored():
    # Kolejność nie jest istotna — same skille.
    old = {"must_skills": [{"name": "Python"}, {"name": "AWS"}]}
    new = {"must_skills": [{"name": "AWS"}, {"name": "Python"}]}
    assert is_significant_job_update(old, new) is False


def test_significant_update_skills_case_insensitive():
    old = {"must_skills": [{"name": "python"}]}
    new = {"must_skills": [{"name": "Python"}]}
    assert is_significant_job_update(old, new) is False


def test_significant_update_seniority_changed():
    old = {"seniority": "mid"}
    new = {"seniority": "senior"}
    assert is_significant_job_update(old, new) is True


def test_significant_update_title_changed():
    old = {"title": "Python Developer"}
    new = {"title": "Senior Python Engineer"}
    assert is_significant_job_update(old, new) is True


def test_significant_update_subcategory_changed():
    old = {"subcategory": "Backend"}
    new = {"subcategory": "Full-Stack"}
    assert is_significant_job_update(old, new) is True


def test_significant_update_industry_changed():
    old = {"industry": "fintech"}
    new = {"industry": "healthcare"}
    assert is_significant_job_update(old, new) is True


def test_significant_update_description_only_is_not_significant():
    # Opis, requirements, salary, location nie są w _SIGNIFICANT_FIELDS.
    old = {"title": "Dev", "description": "old description"}
    new = {"title": "Dev", "description": "totally new description"}
    assert is_significant_job_update(old, new) is False


def test_significant_update_empty_new_bucket():
    old = {"must_skills": [{"name": "Python"}]}
    new = {"must_skills": []}
    assert is_significant_job_update(old, new) is True


def test_significant_update_both_empty_no_op():
    old = {"must_skills": [], "title": "x"}
    new = {"must_skills": [], "title": "x"}
    assert is_significant_job_update(old, new) is False


def test_significant_update_none_vs_empty_list_equivalent():
    old = {"must_skills": None}
    new = {"must_skills": []}
    # Normalizacja obu do pustego frozenset.
    assert is_significant_job_update(old, new) is False


def test_significant_update_accepts_seniority_enum_value():
    # Symulacja: setattr(job, 'seniority', Seniority.senior) vs 'senior' string.
    class _FakeEnum:
        value = "senior"

    old = {"seniority": _FakeEnum()}
    new = {"seniority": "senior"}
    assert is_significant_job_update(old, new) is False


# ══════════════════════════════════════════════════════════════════════════
# DB-integration tests (wymagają migracji 0052-0054)
# ══════════════════════════════════════════════════════════════════════════


pytestmark = pytest.mark.asyncio


async def _cleanup_marketplace(db) -> None:
    """Remove the singleton and candidates created by this test module."""
    from sqlalchemy import delete, select

    pool = (
        await db.execute(
            select(TalentPool).where(TalentPool.is_marketplace.is_(True))
        )
    ).scalar_one_or_none()
    if pool is not None:
        await db.execute(
            delete(TalentPoolMembership).where(
                TalentPoolMembership.talent_pool_id == pool.id
            )
        )
        await db.delete(pool)
    await db.execute(
        delete(Candidate).where(Candidate.email.like("mp_test_%@example.com"))
    )
    await db.commit()


async def _seed_candidate(
    db, *, availability: AvailabilityStatus, email_suffix: str
) -> Candidate:
    """Utility — tworzy candidate z danym availability_status."""
    import uuid as _uuid

    suffix = _uuid.uuid4().hex[:6]
    cand = Candidate(
        name="Test",
        lastname=f"Marketplace_{email_suffix}_{suffix}",
        email=f"mp_test_{email_suffix}_{suffix}@example.com",
        status=CandidateStatus.active,
        availability_status=availability,
    )
    db.add(cand)
    await db.commit()
    await db.refresh(cand)
    return cand


@pytest_asyncio.fixture
async def clean_db():
    """Czysta DB przed i po teście (usuwa singletona + members)."""
    async with AsyncSessionLocal() as db:
        await _cleanup_marketplace(db)
        yield db
        await _cleanup_marketplace(db)


async def test_ensure_marketplace_pool_creates_singleton(clean_db):
    pool1 = await ensure_marketplace_pool(clean_db)
    await clean_db.commit()
    assert pool1.is_marketplace is True
    assert pool1.name == MARKETPLACE_POOL_NAME

    # Drugi call zwraca ten sam rekord.
    pool2 = await ensure_marketplace_pool(clean_db)
    assert pool2.id == pool1.id


async def test_auto_sync_adds_actively_looking(clean_db):
    cand = await _seed_candidate(
        clean_db,
        availability=AvailabilityStatus.actively_looking,
        email_suffix="active",
    )

    counters = await auto_sync_marketplace_membership(clean_db)
    await clean_db.commit()

    assert counters.added >= 1

    # Zweryfikuj że rekord się pojawił.
    pool = await ensure_marketplace_pool(clean_db)
    from sqlalchemy import select

    res = await clean_db.execute(
        select(TalentPoolMembership).where(
            TalentPoolMembership.talent_pool_id == pool.id,
            TalentPoolMembership.candidate_id == cand.id,
        )
    )
    m = res.scalar_one_or_none()
    assert m is not None
    assert m.source_event == "auto_availability"
    assert m.marketplace_until is None


async def test_auto_sync_removes_when_status_flipped(clean_db):
    cand = await _seed_candidate(
        clean_db,
        availability=AvailabilityStatus.open_to_offers,
        email_suffix="flip",
    )
    await auto_sync_marketplace_membership(clean_db)
    await clean_db.commit()

    # Flip na not_looking.
    cand.availability_status = AvailabilityStatus.not_looking
    await clean_db.commit()

    counters = await auto_sync_marketplace_membership(clean_db)
    await clean_db.commit()

    assert counters.removed_status_change >= 1

    # Nie ma już w puli.
    pool = await ensure_marketplace_pool(clean_db)
    from sqlalchemy import select

    res = await clean_db.execute(
        select(TalentPoolMembership).where(
            TalentPoolMembership.talent_pool_id == pool.id,
            TalentPoolMembership.candidate_id == cand.id,
        )
    )
    assert res.scalar_one_or_none() is None


async def test_auto_sync_removes_expired_manual(clean_db):
    cand = await _seed_candidate(
        clean_db,
        availability=AvailabilityStatus.not_looking,  # ręcznie dodany mimo
        email_suffix="expired",
    )

    # Wstaw ręczny wrzut z wczoraj.
    yesterday = date.today() - timedelta(days=1)
    await add_candidate_to_marketplace(
        clean_db,
        candidate_id=cand.id,
        added_by=None,
        marketplace_until=yesterday,
    )
    await clean_db.commit()

    counters = await auto_sync_marketplace_membership(clean_db)
    await clean_db.commit()

    assert counters.removed_expired >= 1


async def test_add_candidate_upgrades_auto_to_manual(clean_db):
    cand = await _seed_candidate(
        clean_db,
        availability=AvailabilityStatus.actively_looking,
        email_suffix="upgrade",
    )
    # Auto-sync wrzuca jako auto_availability.
    await auto_sync_marketplace_membership(clean_db)
    await clean_db.commit()

    # Ręczny "Wrzuć na targ" nadpisuje na manual + ustawia marketplace_until.
    future = date.today() + timedelta(days=14)
    m = await add_candidate_to_marketplace(
        clean_db,
        candidate_id=cand.id,
        added_by=None,
        marketplace_until=future,
    )
    await clean_db.commit()
    assert m.source_event == "manual"
    assert m.marketplace_until == future


async def test_remove_candidate_from_marketplace(clean_db):
    cand = await _seed_candidate(
        clean_db,
        availability=AvailabilityStatus.actively_looking,
        email_suffix="rm",
    )
    await auto_sync_marketplace_membership(clean_db)
    await clean_db.commit()

    removed = await remove_candidate_from_marketplace(
        clean_db, candidate_id=cand.id
    )
    await clean_db.commit()
    assert removed is True

    # Drugi remove → False.
    removed2 = await remove_candidate_from_marketplace(
        clean_db, candidate_id=cand.id
    )
    await clean_db.commit()
    assert removed2 is False
