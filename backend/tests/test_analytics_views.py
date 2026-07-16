"""Testy integracyjne kanonicznych views Analytics v1 (plan PR 2).

Wymagają Postgresa z zaaplikowaną migracją 0174 (CI: `alembic upgrade
heads` przed pytestem). Seed przez ORM, asercje przez surowy SQL na views.

Scenariusz fixture: kandydat przechodzi stage'y wielokrotnie (w tym
POWTÓRNE verified przez innego usera i cofnięcie) — dokładnie przypadek,
który psuł legacy funnel (liczył historyczne ruchy zamiast stanu).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.candidate_source_event import CandidateSourceEvent, SourceChannel
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole

T0 = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def seeded_pipeline():
    """Kandydat × job z powtórzonymi stage'ami + 2 eventy źródeł."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user_a = User(
            email=f"an-viewsA-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Verifier A",
            role=UserRole.recruiter,
            is_active=True,
        )
        user_b = User(
            email=f"an-viewsB-{unique}@example.com",
            password_hash=hash_password("x"),
            name="Verifier B",
            role=UserRole.recruiter,
            is_active=True,
        )
        client = Client(name=f"Analytics Test Client {unique}")
        db.add_all([user_a, user_b, client])
        await db.flush()

        job = Job(title=f"Analytics Test Job {unique}", client_id=client.id)
        candidate = Candidate(name="Ana", lastname=f"Lytics-{unique}")
        db.add_all([job, candidate])
        await db.flush()

        # Historia stage'ów: new → verified(A) → cv_sent → verified(B, powtórka)
        # → rejected (stan bieżący).
        stages = [
            (PipelineStage.new, T0, None),
            (PipelineStage.verified, T0 + timedelta(days=1), user_a.id),
            (PipelineStage.cv_sent, T0 + timedelta(days=2), user_a.id),
            (PipelineStage.verified, T0 + timedelta(days=3), user_b.id),
            (PipelineStage.rejected, T0 + timedelta(days=4), user_b.id),
        ]
        for stage, moved_at, moved_by in stages:
            db.add(
                CandidateStage(
                    candidate_id=candidate.id,
                    job_id=job.id,
                    stage=stage,
                    moved_at=moved_at,
                    moved_by=moved_by,
                )
            )

        # Źródła: pierwszy touch = referral, drugi = posting.
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate.id,
                channel=SourceChannel.referral,
                captured_at=T0 - timedelta(days=10),
            )
        )
        db.add(
            CandidateSourceEvent(
                candidate_id=candidate.id,
                channel=SourceChannel.posting,
                captured_at=T0 - timedelta(days=1),
            )
        )
        await db.commit()

        return {
            "candidate_id": candidate.id,
            "job_id": job.id,
            "user_a_id": user_a.id,
            "user_b_id": user_b.id,
        }


@pytest.mark.asyncio
async def test_current_pipeline_returns_latest_stage(seeded_pipeline):
    ids = seeded_pipeline
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT stage, moved_by FROM analytics_current_pipeline "
                    "WHERE candidate_id = :cid AND job_id = :jid"
                ),
                {"cid": ids["candidate_id"], "jid": ids["job_id"]},
            )
        ).one()
    assert row.stage == "rejected", (
        "current pipeline musi być OSTATNIM stage, nie historią ruchów"
    )
    assert row.moved_by == ids["user_b_id"]


@pytest.mark.asyncio
async def test_first_milestones_first_verifier_attribution(seeded_pipeline):
    ids = seeded_pipeline
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                text(
                    "SELECT stage, first_moved_by, first_reached_at "
                    "FROM analytics_first_milestones "
                    "WHERE candidate_id = :cid AND job_id = :jid"
                ),
                {"cid": ids["candidate_id"], "jid": ids["job_id"]},
            )
        ).all()
    by_stage = {r.stage: r for r in rows}

    # verified pojawiło się dwa razy — milestone liczy się RAZ,
    # atrybucja = PIERWSZY verifier (user A), nie ostatni.
    assert "verified" in by_stage
    assert by_stage["verified"].first_moved_by == ids["user_a_id"]
    assert by_stage["verified"].first_reached_at == T0 + timedelta(days=1)

    assert "cv_sent" in by_stage
    # rejected/new nie są milestone'ami
    assert "rejected" not in by_stage
    assert "new" not in by_stage
    # brak hired — kandydat nie doszedł
    assert "hired" not in by_stage


@pytest.mark.asyncio
async def test_first_sources_first_touch(seeded_pipeline):
    ids = seeded_pipeline
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT channel, captured_at "
                    "FROM analytics_candidate_first_sources "
                    "WHERE candidate_id = :cid"
                ),
                {"cid": ids["candidate_id"]},
            )
        ).one()
    assert row.channel == "referral", "first-touch = najwcześniejszy event"
    assert row.captured_at == T0 - timedelta(days=10)


@pytest.mark.asyncio
async def test_views_exist():
    """Wszystkie 3 views istnieją po migracji/entrypoint safety-net."""
    async with AsyncSessionLocal() as db:
        names = (
            await db.execute(
                text(
                    "SELECT table_name FROM information_schema.views "
                    "WHERE table_name LIKE 'analytics_%'"
                )
            )
        ).scalars()
        found = set(names)
    assert {
        "analytics_current_pipeline",
        "analytics_first_milestones",
        "analytics_candidate_first_sources",
    } <= found
