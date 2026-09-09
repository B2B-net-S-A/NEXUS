"""Hosted PostgreSQL proves one winner across independent worker processes."""

import asyncio
import uuid

from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.app_setting import AppSetting
from scripts import eval_cv_factual_gate as runner


async def test_concurrent_claims_and_later_checkpoint_preserve_one_receipt(tmp_path):
    key = runner.run_key(str(uuid.uuid4().int)[:20] + "-1")
    initial = {"complete": False, "results": []}
    try:
        claims = await asyncio.gather(
            runner.claim_run(key, initial), runner.claim_run(key, initial)
        )
        assert sum(item is None for item in claims) == 1
        assert initial in claims
        final = {"complete": True, "results": [{"outcome": "accepted"}]}
        await runner.checkpoint(tmp_path / "report.json", final, key)
        assert await runner.claim_run(key, initial) == final
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AppSetting).where(AppSetting.key == key))
            await db.commit()
