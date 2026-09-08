"""Real PostgreSQL coverage for transaction/NULL/concurrency regressions.

Hosted CI supplies PostgreSQL. Provider calls use synthetic responses only.
"""

import asyncio
import os
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, func, update
from starlette.concurrency import run_in_threadpool

from app.models.ai_feature import AIFeatureKey
from app.models.ai_metering import (
    AIOperation,
    AIProviderCall,
    AIGenerationLease,
    AISpendAlert,
)
from app.services.ai_quota import ai_feature, check_and_increment, declared_call
from app.services.claude_client import _record_tokens

pytestmark = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="hosted PostgreSQL required"
)


def message(event_id):
    return SimpleNamespace(
        id=event_id,
        model="claude-haiku-4-5-20251001",
        stop_reason="end_turn",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=10,
            cache_read_input_tokens=20,
            cache_creation_input_tokens=30,
        ),
    )


async def clean_operations(ids):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(AIProviderCall).where(AIProviderCall.operation_id.in_(ids))
        )
        await db.execute(delete(AIOperation).where(AIOperation.id.in_(ids)))
        await db.commit()


async def test_two_system_operations_survive_business_rollback_and_response_retry():
    from app.core.database import AsyncSessionLocal

    ids = []
    try:
        for _ in range(2):
            async with AsyncSessionLocal() as business:
                with pytest.raises(ValueError, match="parser"):
                    async with ai_feature(business, AIFeatureKey.uop_check) as state:
                        ids.append(state.operation_id)
                        response = message(str(uuid4()))
                        await run_in_threadpool(_record_tokens, response)
                        # Simulated persistence retry: same provider message is one charge.
                        await run_in_threadpool(_record_tokens, response)
                        raise ValueError("parser failed after paid response")
                await business.rollback()
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.sum(AIOperation.units)).where(AIOperation.id.in_(ids))
                )
                == 2
            )
            result = (
                await db.execute(
                    select(
                        func.count(),
                        func.sum(AIProviderCall.input_tokens),
                        func.sum(AIProviderCall.output_tokens),
                        func.sum(AIProviderCall.cache_read_tokens),
                    ).where(AIProviderCall.operation_id.in_(ids))
                )
            ).one()
            assert tuple(result) == (2, 200, 20, 40)
    finally:
        await clean_operations(ids)


async def test_background_declaration_persists_without_a_business_session():
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        state = await check_and_increment(db, AIFeatureKey.cv_generator)
    try:
        with declared_call(AIFeatureKey.cv_generator, user_id=None, state=state):
            await run_in_threadpool(_record_tokens, message(str(uuid4())))
        async with AsyncSessionLocal() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(AIProviderCall)
                    .where(AIProviderCall.operation_id == state.operation_id)
                )
                == 1
            )
    finally:
        await clean_operations([state.operation_id])


async def test_concurrent_system_admissions_do_not_share_a_locked_monthly_row():
    from app.core.database import AsyncSessionLocal

    async def admit():
        async with AsyncSessionLocal() as db:
            state = await check_and_increment(db, AIFeatureKey.uop_check)
            # No caller commit; competitors still proceed.
            await asyncio.sleep(0.05)
            return state.operation_id

    ids = await asyncio.wait_for(
        asyncio.gather(*(admit() for _ in range(5))), timeout=10
    )
    try:
        assert len(set(ids)) == 5
    finally:
        await clean_operations(ids)


async def test_generation_lease_excludes_second_worker_and_rejects_expired_writer():
    from app.core.database import AsyncSessionLocal
    from app.services.ai_generation_lease import (
        generation_lease,
        lock_owned_lease,
        GenerationBusy,
    )

    key = "test:" + str(uuid4())
    async with generation_lease(key) as old:
        with pytest.raises(GenerationBusy):
            async with generation_lease(key):
                pytest.fail("second worker reached provider")
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(AIGenerationLease)
                .where(AIGenerationLease.key == key)
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
            await db.commit()
        async with generation_lease(key) as new:
            assert old != new
            async with AsyncSessionLocal() as db:
                with pytest.raises(GenerationBusy):
                    await lock_owned_lease(db, key, old)
                await db.rollback()
                await lock_owned_lease(db, key, new)
                await db.commit()


async def test_alert_outbox_retries_slack_without_duplicating_in_app(monkeypatch):
    from unittest.mock import AsyncMock
    from app.core.database import AsyncSessionLocal
    from app.models.user import User, UserRole
    from app.models.notification import Notification
    from app.tasks.ai_spend_alerts import queue_alert, deliver_alerts

    key = "test:" + str(uuid4())
    post = AsyncMock(side_effect=[False, True])
    monkeypatch.setattr("app.tasks.ai_spend_alerts._post_to_slack", post)
    async with AsyncSessionLocal() as db:
        admin = User(
            name="AI audit test",
            email=key + "@example.test",
            role=UserRole.admin,
            roles=["admin"],
        )
        db.add(admin)
        await db.commit()
        await queue_alert(db, key, "Synthetic AI delivery test")
        await queue_alert(db, key, "Synthetic AI delivery test")
        await db.commit()
        alert = await db.scalar(select(AISpendAlert).where(AISpendAlert.key == key))
        # Other test files do not queue alerts; a fresh shard DB is isolated.
        try:
            await deliver_alerts(db, "https://example.test/synthetic")
            assert alert.in_app_at is not None and alert.slack_sent_at is None
            await deliver_alerts(db, "https://example.test/synthetic")
            await db.refresh(alert)
            assert alert.slack_sent_at is not None and alert.attempts == 2
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Notification)
                    .where(
                        Notification.user_id == admin.id,
                        Notification.related_entity_type == "ai_spend_alert",
                        Notification.related_entity_id == alert.id,
                    )
                )
                == 1
            )
        finally:
            await db.execute(
                delete(Notification).where(
                    Notification.related_entity_type == "ai_spend_alert",
                    Notification.related_entity_id == alert.id,
                )
            )
            await db.delete(alert)
            await db.delete(admin)
            await db.commit()


async def test_legacy_manual_skill_audit_blocks_cv_resurrection():
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.activity import Activity
    from app.models.user import User, UserRole
    from app.services.scoring_service import candidate_skill_names
    from app.services.notes_insights_extractor import apply_insights

    async with AsyncSessionLocal() as db:
        user = User(
            name="Skill audit test",
            email=f"{uuid4()}@example.test",
            role=UserRole.recruiter,
            roles=["recruiter"],
        )
        candidate = Candidate(
            name="Synthetic",
            lastname="Skill provenance",
            skills=["Python"],
            cv_extracted_data={"traffit_technologie": "Python, Java"},
        )
        db.add_all([user, candidate])
        await db.flush()
        activity = Activity(
            entity_type="candidate",
            entity_id=candidate.id,
            action="updated",
            external_source="manual",
            user_id=user.id,
            details={"skills": ["Python"]},
        )
        db.add(activity)
        await db.flush()
        await db.refresh(candidate)
        assert candidate.skills_manually_curated is True
        assert candidate_skill_names(candidate) == {"python"}
        stats = apply_insights(
            candidate, {"skills_evidenced": [{"name": "Java"}]}, fingerprint="test"
        )
        assert stats["locked_skills"] == 1
        await db.rollback()
