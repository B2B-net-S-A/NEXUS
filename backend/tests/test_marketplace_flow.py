"""Integration tests dla `scan_job_for_marketplace_matches`.

Flow end-to-end: kandydat → targ → nowy job → notyfikacje + alert log.
Monkey-patch na `search_candidates_semantic` (Qdrant) i `score_candidate_job`
żeby test nie potrzebował uruchomionego Qdranta ani pełnego pipeline'u
scoringu.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job, JobStatus, RecruitmentType
from app.models.marketplace_alert_log import MarketplaceAlertLog
from app.models.notification import Notification, NotificationType
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.models.user import User, UserRole
from app.services.marketplace_service import (
    add_candidate_to_marketplace,
    scan_job_for_marketplace_matches,
)


pytestmark = pytest.mark.asyncio


# ── Helpers ────────────────────────────────────────────────────────────────


@dataclass
class _FakeLayer:
    points: float = 0.0
    max_points: float = 100.0
    reason: str = ""


@dataclass
class _FakeBreakdown:
    candidate_id: int
    job_id: int
    total: float
    matching_must: list[str]
    gap_must: list[str]
    # Reszta pól wystarczy że istnieje jako atrybut dla loggera.
    semantic: Any = None
    skills: Any = None
    salary: Any = None
    location: Any = None
    availability: Any = None
    champion_fit: Any = None
    matching_nice: list[str] | None = None
    gap_nice: list[str] | None = None
    penalties: list = None

    def __post_init__(self):
        empty = _FakeLayer()
        if self.semantic is None:
            self.semantic = empty
        if self.skills is None:
            self.skills = empty
        if self.salary is None:
            self.salary = empty
        if self.location is None:
            self.location = empty
        if self.availability is None:
            self.availability = empty
        if self.champion_fit is None:
            self.champion_fit = empty
        if self.matching_nice is None:
            self.matching_nice = []
        if self.gap_nice is None:
            self.gap_nice = []
        if self.penalties is None:
            self.penalties = []


async def _cleanup_marketplace_data(db) -> None:
    # A failed flush leaves AsyncSession unusable until rollback; teardown must
    # remain deterministic even when the assertion under test fails.
    await db.rollback()
    test_user_ids = db.info.pop("marketplace_test_user_ids", [])
    test_candidate_ids = db.info.pop("marketplace_test_candidate_ids", [])
    test_job_ids = db.info.pop("marketplace_test_job_ids", [])
    test_client_ids = db.info.pop("marketplace_test_client_ids", [])

    # Usuń wszystkie test-utworzone marketplace artefakty.
    pool = (
        await db.execute(select(TalentPool).where(TalentPool.is_marketplace.is_(True)))
    ).scalar_one_or_none()
    if pool is not None:
        await db.execute(
            delete(TalentPoolMembership).where(
                TalentPoolMembership.talent_pool_id == pool.id
            )
        )
        await db.delete(pool)
    await db.execute(delete(MarketplaceAlertLog))
    await db.execute(
        delete(Notification).where(
            Notification.notification_type == NotificationType.marketplace_match
        )
    )
    if test_job_ids:
        await db.execute(delete(Job).where(Job.id.in_(test_job_ids)))
    if test_client_ids:
        await db.execute(delete(Client).where(Client.id.in_(test_client_ids)))
    if test_candidate_ids:
        await db.execute(delete(Candidate).where(Candidate.id.in_(test_candidate_ids)))
    if test_user_ids:
        await db.execute(delete(User).where(User.id.in_(test_user_ids)))
    await db.commit()


@pytest_asyncio.fixture
async def fresh_db():
    async with AsyncSessionLocal() as db:
        await _cleanup_marketplace_data(db)
        yield db
        # teardown — usuń obiekty testowe (użyjemy unique sufiksów)
        await _cleanup_marketplace_data(db)


async def _seed_user(db, *, name: str, role: UserRole = UserRole.tac) -> User:
    suffix = uuid.uuid4().hex[:8]
    u = User(
        email=f"marketplace_{name}_{suffix}@example.com",
        password_hash=hash_password("test_pass"),
        name=name,
        role=role,
        is_active=True,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    db.info.setdefault("marketplace_test_user_ids", []).append(u.id)
    return u


async def _seed_candidate(
    db, *, owner: User, skills: list[dict] | None = None
) -> Candidate:
    suffix = uuid.uuid4().hex[:8]
    cand = Candidate(
        name="Jan",
        lastname=f"Kowalski_{suffix}",
        email=f"jan_{suffix}@example.com",
        status=CandidateStatus.active,
        availability_status=AvailabilityStatus.actively_looking,
        created_by=owner.id,
        skills=skills or [{"name": "Python"}, {"name": "FastAPI"}],
        years_it_experience=7,
        salary_expectation=15000,
        salary_currency="PLN",
        embedding_id=None,
    )
    db.add(cand)
    await db.commit()
    await db.refresh(cand)
    db.info.setdefault("marketplace_test_candidate_ids", []).append(cand.id)
    return cand


async def _seed_job(
    db, *, recruiter: User, title: str = "Senior Python Engineer"
) -> Job:
    from app.models.client import Client

    cli = Client(name=f"MpClient-{uuid.uuid4().hex[:6]}")
    db.add(cli)
    await db.commit()
    await db.refresh(cli)
    db.info.setdefault("marketplace_test_client_ids", []).append(cli.id)
    job = Job(
        title=title,
        description="Budujemy ATS, szukamy seniora.",
        must_skills=[{"name": "Python"}],
        nice_skills=[{"name": "FastAPI"}],
        status=JobStatus.published,
        recruitment_type=RecruitmentType.body_leasing,
        recruiter_id=recruiter.id,
        created_by=recruiter.id,
        embedding_id="stub-embedding-id",  # by _should_scan_job przeszło
        client_id=cli.id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    db.info.setdefault("marketplace_test_job_ids", []).append(job.id)
    return job


# ── Testy ──────────────────────────────────────────────────────────────────


async def test_full_flow_creates_notifications_for_both_owners(monkeypatch, fresh_db):
    db = fresh_db

    recruiter_cand = await _seed_user(db, name="OwnerCand")
    recruiter_job = await _seed_user(db, name="OwnerJob")

    cand = await _seed_candidate(db, owner=recruiter_cand)
    job = await _seed_job(db, recruiter=recruiter_job)

    await add_candidate_to_marketplace(
        db, candidate_id=cand.id, added_by=recruiter_cand.id
    )
    await db.commit()

    # Stub: Qdrant hit — wysoka podobieństwo dla naszego kandydata.
    async def fake_search_candidates(*args, **kwargs):
        return [{"candidate_id": cand.id, "score": 0.92, "payload": {}}]

    async def fake_score(
        candidate, job_obj, db_, *, semantic_similarity=None, profile=None
    ):
        return _FakeBreakdown(
            candidate_id=candidate.id,
            job_id=job_obj.id,
            total=85.0,
            matching_must=["Python"],
            gap_must=[],
        )

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic",
        fake_search_candidates,
    )
    monkeypatch.setattr("app.services.scoring_service.score_candidate_job", fake_score)

    result = await scan_job_for_marketplace_matches(job.id, db)
    await db.commit()

    assert result.skipped_reason is None
    assert result.matches_found >= 1
    assert result.new_alerts >= 1

    # Alert log: dokładnie jeden wpis dla (cand, job).
    logs = (
        (
            await db.execute(
                select(MarketplaceAlertLog).where(
                    MarketplaceAlertLog.candidate_id == cand.id,
                    MarketplaceAlertLog.job_id == job.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1
    assert float(logs[0].score) >= 70.0
    assert logs[0].notified_candidate_owner_id == recruiter_cand.id
    assert logs[0].notified_job_owner_id == recruiter_job.id

    # Notyfikacje: dwie (cand-owner + job-owner).
    notifs = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.marketplace_match,
                    Notification.related_entity_id == job.id,
                    Notification.related_entity_type == "job",
                    Notification.user_id.in_([recruiter_cand.id, recruiter_job.id]),
                )
            )
        )
        .scalars()
        .all()
    )
    user_ids = {n.user_id for n in notifs}
    assert user_ids == {recruiter_cand.id, recruiter_job.id}


async def test_dedup_second_scan_creates_no_new_alert(monkeypatch, fresh_db):
    db = fresh_db

    recruiter = await _seed_user(db, name="Owner")
    cand = await _seed_candidate(db, owner=recruiter)
    job = await _seed_job(db, recruiter=recruiter)
    await add_candidate_to_marketplace(db, candidate_id=cand.id, added_by=recruiter.id)
    await db.commit()

    async def fake_search_candidates(*args, **kwargs):
        return [{"candidate_id": cand.id, "score": 0.92, "payload": {}}]

    async def fake_score(
        candidate, job_obj, db_, *, semantic_similarity=None, profile=None
    ):
        return _FakeBreakdown(
            candidate_id=candidate.id,
            job_id=job_obj.id,
            total=80.0,
            matching_must=["Python"],
            gap_must=[],
        )

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic",
        fake_search_candidates,
    )
    monkeypatch.setattr("app.services.scoring_service.score_candidate_job", fake_score)

    r1 = await scan_job_for_marketplace_matches(job.id, db)
    await db.commit()
    r2 = await scan_job_for_marketplace_matches(job.id, db)
    await db.commit()

    assert r1.new_alerts == 1
    assert r2.new_alerts == 0  # dedup działa

    # Jeden wpis w logu.
    logs = (
        (
            await db.execute(
                select(MarketplaceAlertLog).where(
                    MarketplaceAlertLog.candidate_id == cand.id,
                    MarketplaceAlertLog.job_id == job.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(logs) == 1


async def test_owner_equal_single_notification(monkeypatch, fresh_db):
    """Gdy candidate.created_by == job.recruiter_id → jedna notyfikacja."""
    db = fresh_db
    owner = await _seed_user(db, name="SoloOwner")
    cand = await _seed_candidate(db, owner=owner)
    job = await _seed_job(db, recruiter=owner)
    await add_candidate_to_marketplace(db, candidate_id=cand.id, added_by=owner.id)
    await db.commit()

    async def fake_search_candidates(*args, **kwargs):
        return [{"candidate_id": cand.id, "score": 0.9, "payload": {}}]

    async def fake_score(
        candidate, job_obj, db_, *, semantic_similarity=None, profile=None
    ):
        return _FakeBreakdown(
            candidate_id=candidate.id,
            job_id=job_obj.id,
            total=85.0,
            matching_must=["Python"],
            gap_must=[],
        )

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic",
        fake_search_candidates,
    )
    monkeypatch.setattr("app.services.scoring_service.score_candidate_job", fake_score)

    await scan_job_for_marketplace_matches(job.id, db)
    await db.commit()

    notifs = (
        (
            await db.execute(
                select(Notification).where(
                    Notification.notification_type
                    == NotificationType.marketplace_match,
                    Notification.related_entity_id == job.id,
                    Notification.user_id == owner.id,
                )
            )
        )
        .scalars()
        .all()
    )
    assert len(notifs) == 1


async def test_score_below_threshold_no_alert(monkeypatch, fresh_db):
    db = fresh_db
    owner = await _seed_user(db, name="LowScore")
    cand = await _seed_candidate(db, owner=owner)
    job = await _seed_job(db, recruiter=owner)
    await add_candidate_to_marketplace(db, candidate_id=cand.id, added_by=owner.id)
    await db.commit()

    async def fake_search_candidates(*args, **kwargs):
        return [{"candidate_id": cand.id, "score": 0.3, "payload": {}}]

    async def fake_score(
        candidate, job_obj, db_, *, semantic_similarity=None, profile=None
    ):
        return _FakeBreakdown(
            candidate_id=candidate.id,
            job_id=job_obj.id,
            total=40.0,  # poniżej 70
            matching_must=[],
            gap_must=["Python"],
        )

    monkeypatch.setattr(
        "app.services.embedding_service.search_candidates_semantic",
        fake_search_candidates,
    )
    monkeypatch.setattr("app.services.scoring_service.score_candidate_job", fake_score)

    result = await scan_job_for_marketplace_matches(job.id, db)
    await db.commit()
    assert result.new_alerts == 0
    assert result.matches_found == 0


async def test_skip_when_job_has_no_skills(monkeypatch, fresh_db):
    from app.models.client import Client

    db = fresh_db
    owner = await _seed_user(db, name="NoSkills")
    cli = Client(name=f"MpClient-NoSkills-{uuid.uuid4().hex[:6]}")
    db.add(cli)
    await db.commit()
    await db.refresh(cli)
    job = Job(
        title="Test",
        description="x",
        must_skills=[],
        nice_skills=[],
        status=JobStatus.published,
        recruiter_id=owner.id,
        created_by=owner.id,
        embedding_id="stub",
        client_id=cli.id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    db.info.setdefault("marketplace_test_client_ids", []).append(cli.id)
    db.info.setdefault("marketplace_test_job_ids", []).append(job.id)

    result = await scan_job_for_marketplace_matches(job.id, db)
    assert result.skipped_reason == "no_skills"


async def test_skip_when_job_closed(fresh_db):
    from app.models.client import Client

    db = fresh_db
    owner = await _seed_user(db, name="ClosedJob")
    cli = Client(name=f"MpClient-Closed-{uuid.uuid4().hex[:6]}")
    db.add(cli)
    await db.commit()
    await db.refresh(cli)
    job = Job(
        title="Closed",
        description="x",
        must_skills=[{"name": "Python"}],
        status=JobStatus.closed,
        recruiter_id=owner.id,
        created_by=owner.id,
        embedding_id="stub",
        client_id=cli.id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    db.info.setdefault("marketplace_test_client_ids", []).append(cli.id)
    db.info.setdefault("marketplace_test_job_ids", []).append(job.id)

    result = await scan_job_for_marketplace_matches(job.id, db)
    assert result.skipped_reason is not None
    assert "status" in result.skipped_reason


async def test_skip_when_empty_pool(fresh_db):
    db = fresh_db
    owner = await _seed_user(db, name="EmptyPool")
    job = await _seed_job(db, recruiter=owner)

    # Pool istnieje ale jest pusty — żaden kandydat z actively_looking.
    result = await scan_job_for_marketplace_matches(job.id, db)
    # Może zwrócić empty_pool lub candidates_scored=0; oba OK.
    assert result.new_alerts == 0
    assert result.matches_found == 0
