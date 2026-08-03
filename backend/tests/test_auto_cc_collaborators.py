"""Tests for auto_add_cc_collaborators idempotence + priority selection."""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal
from app.models.competence_category import (
    CompetenceCategory,
    UserCompetenceCategory,
)
from app.models.job import Job
from app.models.job_collaborator import JobCollaborator, JobCollaboratorSource
from app.models.user import User, UserRole
from app.core.security import hash_password
from app.services.auto_cc_collaborators import auto_add_cc_collaborators


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def seeded_cc_and_users():
    """Seed 1 CC + 3 users (2 priority=1 sourcers + 1 priority=2 backup)."""
    import uuid

    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        cc = await db.scalar(
            select(CompetenceCategory).where(
                CompetenceCategory.slug == "software_development"
            )
        )
        assert cc is not None, "Seed CC 'software_development' must exist"

        users = []
        for i, priority in enumerate((1, 1, 2), start=1):
            u = User(
                email=f"auto-cc-test-{suffix}-{i}@example.com",
                password_hash=hash_password(f"P@ssw0rd-{i}"),
                name=f"AutoCC Test {i}",
                role=UserRole.sourcer,
                is_active=True,
            )
            db.add(u)
            await db.flush()
            db.add(
                UserCompetenceCategory(
                    user_id=u.id,
                    competence_category_id=cc.id,
                    priority=priority,
                    is_primary=priority == 1,
                )
            )
            users.append(u)
        await db.commit()
        yield {"cc_id": cc.id, "users": [u.id for u in users], "priorities": [1, 1, 2]}

        # Cleanup
        await db.execute(
            UserCompetenceCategory.__table__.delete().where(
                UserCompetenceCategory.user_id.in_([u.id for u in users])
            )
        )
        for u in users:
            await db.delete(u)
        await db.commit()


async def test_auto_add_picks_only_priority_one(seeded_cc_and_users):
    data = seeded_cc_and_users
    async with AsyncSessionLocal() as db:
        # Create a stub job
        import uuid

        from app.models.client import Client

        cli = Client(name=f"AutoCCClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"TestJob-{uuid.uuid4().hex[:8]}",
            status="draft",
            client_id=cli.id,
        )
        db.add(job)
        await db.flush()
        job_id = job.id
        await db.commit()

        added = await auto_add_cc_collaborators(
            db, job_id=job_id, competence_category_id=data["cc_id"]
        )
        # priority=1 users (first two) should be added; backup (priority=2) skipped
        assert data["users"][0] in added
        assert data["users"][1] in added
        assert data["users"][2] not in added

        collabs = (
            (
                await db.execute(
                    select(JobCollaborator).where(JobCollaborator.job_id == job_id)
                )
            )
            .scalars()
            .all()
        )
        actual_ids = {c.user_id for c in collabs}
        assert data["users"][0] in actual_ids
        assert data["users"][1] in actual_ids
        assert data["users"][2] not in actual_ids
        # All should be marked auto_cc
        for c in collabs:
            assert c.source == JobCollaboratorSource.auto_cc

        # Cleanup
        await db.execute(
            JobCollaborator.__table__.delete().where(JobCollaborator.job_id == job_id)
        )
        await db.delete(job)
        await db.commit()


async def test_auto_add_is_idempotent(seeded_cc_and_users):
    """Calling twice with the same args must not create duplicates."""
    data = seeded_cc_and_users
    async with AsyncSessionLocal() as db:
        import uuid

        from app.models.client import Client

        cli = Client(name=f"AutoCCClient-Idem-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"TestJobIdempotent-{uuid.uuid4().hex[:8]}",
            status="draft",
            client_id=cli.id,
        )
        db.add(job)
        await db.flush()
        job_id = job.id
        await db.commit()

        await auto_add_cc_collaborators(
            db, job_id=job_id, competence_category_id=data["cc_id"]
        )
        await auto_add_cc_collaborators(
            db, job_id=job_id, competence_category_id=data["cc_id"]
        )  # second call — should be a no-op

        count = await db.scalar(
            select(func.count(JobCollaborator.id)).where(
                JobCollaborator.job_id == job_id
            )
        )
        # Only priority-1 users (2 of them) should be present, no duplicates
        assert count == 2

        # Cleanup
        await db.execute(
            JobCollaborator.__table__.delete().where(JobCollaborator.job_id == job_id)
        )
        await db.delete(job)
        await db.commit()
