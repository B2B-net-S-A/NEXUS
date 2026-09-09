from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.models.candidate_conflict import ConflictType
from app.services import search_eligibility_freshness as service


@pytest.mark.asyncio
async def test_full_scope_hash_changes_for_conflict_removal_and_manager_veto(
    monkeypatch,
):
    rows = [(99, ConflictType.nda), (7, ConflictType.blacklist)]
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: rows))
    )
    vetoes = AsyncMock(return_value={})
    monkeypatch.setattr(service, "load_manager_rejections", vetoes)
    job = SimpleNamespace(id=12, client_id=4, hiring_manager_contact_id=8)
    now = datetime(2026, 9, 9, tzinfo=timezone.utc)
    initial = await service.eligibility_fingerprint(db, job=job, now=now)
    rows.reverse()
    assert await service.eligibility_fingerprint(db, job=job, now=now) == initial
    rows.pop()
    removed = await service.eligibility_fingerprint(db, job=job, now=now)
    assert removed != initial
    vetoes.return_value = {12345: object()}
    assert await service.eligibility_fingerprint(db, job=job, now=now) != removed
    vetoes.assert_awaited_with(db, job=job, candidate_ids=None)
    statement = db.execute.call_args.args[0].compile(dialect=postgresql.dialect())
    assert "candidate_conflicts.active IS true" in str(statement)
    assert "candidate_conflicts.expires_at IS NULL OR" in str(statement)
    assert now in statement.params.values()
    assert job.client_id in statement.params.values()
    assert "LIMIT" not in str(statement)


@pytest.mark.asyncio
async def test_empty_candidate_list_still_skips_manager_query():
    from app.services.hiring_manager_verdicts import load_manager_rejections

    db = SimpleNamespace(execute=AsyncMock())
    job = SimpleNamespace(hiring_manager_contact_id=8)
    assert await load_manager_rejections(db, job=job, candidate_ids=[]) == {}
    db.execute.assert_not_awaited()
