"""CC / talent-pool centroids (`cc_centroid_service`) and their sync loop.

Qdrant is never touched: the two sync helpers (`_retrieve_vectors_sync`,
`_upsert_centroid_sync`) and `embedding_service.generate_embedding` are
replaced, while the SQL side runs against the real Postgres. Every row is
created with a unique tag and removed afterwards — the database is shared and
other suites count competence categories.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.competence_category import (
    CandidateCompetenceCategory,
    CompetenceCategory,
)
from app.models.talent_pool import TalentPool, TalentPoolMembership
from app.services import cc_centroid_service as svc
from app.services.cc_classifier import CC_CENTROIDS_COLLECTION
from app.tasks import cc_centroid_sync as sync_task


DIM = svc.VECTOR_SIZE


def _vec(value: float) -> list[float]:
    return [value] * DIM


# ── _mean_vector ─────────────────────────────────────────────────────────────


def test_mean_vector_empty_is_none():
    assert svc._mean_vector([]) is None


def test_mean_vector_is_element_wise_average():
    assert svc._mean_vector([[1.0, 2.0, 3.0], [3.0, 4.0, 5.0]]) == [2.0, 3.0, 4.0]


def test_mean_vector_single_vector_is_identity():
    assert svc._mean_vector([[0.5, -1.0]]) == [0.5, -1.0]


def test_mean_vector_handles_negative_and_three_rows():
    out = svc._mean_vector([[-3.0, 0.0], [0.0, 3.0], [6.0, 3.0]])
    assert out == [1.0, 2.0]


# ── helpers ──────────────────────────────────────────────────────────────────


async def _make_cc(tag: str, *, keywords: list[str] | None = None) -> int:
    async with AsyncSessionLocal() as db:
        cc = CompetenceCategory(
            slug=f"centroid-{tag}",
            name_pl=f"Centroid PL {tag}",
            name_en=f"Centroid EN {tag}",
            description="centroid test fixture",
            keywords=keywords or [],
        )
        db.add(cc)
        await db.commit()
        return cc.id


async def _make_pool(tag: str, *, updated_at: datetime | None = None) -> int:
    async with AsyncSessionLocal() as db:
        pool = TalentPool(
            name=f"Centroid pool {tag}",
            centroid_vector_id="stale",
            centroid_updated_at=updated_at,
        )
        db.add(pool)
        await db.commit()
        return pool.id


async def _make_candidate(tag: str) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Centroid", lastname=f"Cand-{tag}")
        db.add(cand)
        await db.commit()
        return cand.id


async def _drop(*, cc_ids=(), pool_ids=(), candidate_ids=()) -> None:
    async with AsyncSessionLocal() as db:
        if pool_ids:
            await db.execute(
                delete(TalentPoolMembership).where(
                    TalentPoolMembership.talent_pool_id.in_(list(pool_ids))
                )
            )
            await db.execute(
                delete(TalentPool).where(TalentPool.id.in_(list(pool_ids)))
            )
        if cc_ids:
            await db.execute(
                delete(CandidateCompetenceCategory).where(
                    CandidateCompetenceCategory.competence_category_id.in_(list(cc_ids))
                )
            )
            await db.execute(
                delete(CompetenceCategory).where(
                    CompetenceCategory.id.in_(list(cc_ids))
                )
            )
        if candidate_ids:
            await db.execute(
                delete(Candidate).where(Candidate.id.in_(list(candidate_ids)))
            )
        await db.commit()


# ── compute_pool_centroid ────────────────────────────────────────────────────


async def test_pool_without_members_clears_centroid(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    pool_id = await _make_pool(tag)
    retrieve = MagicMock(side_effect=AssertionError("no members → no Qdrant read"))
    monkeypatch.setattr(svc, "_retrieve_vectors_sync", retrieve)
    try:
        async with AsyncSessionLocal() as db:
            ok = await svc.compute_pool_centroid(db, pool_id)
        async with AsyncSessionLocal() as db:
            pool = await db.get(TalentPool, pool_id)
            assert ok is False
            assert pool.centroid_vector_id is None
            assert pool.centroid_updated_at is not None
    finally:
        await _drop(pool_ids=[pool_id])


async def test_missing_pool_returns_false():
    async with AsyncSessionLocal() as db:
        max_id = await db.scalar(
            select(TalentPool.id).order_by(TalentPool.id.desc()).limit(1)
        )
        assert await svc.compute_pool_centroid(db, (max_id or 0) + 10_000) is False


async def test_pool_with_members_upserts_mean(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    pool_id = await _make_pool(tag)
    cand_a, cand_b = await _make_candidate(tag + "a"), await _make_candidate(tag + "b")
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                TalentPoolMembership(talent_pool_id=pool_id, candidate_id=cand_a),
                TalentPoolMembership(talent_pool_id=pool_id, candidate_id=cand_b),
            ]
        )
        await db.commit()

    retrieve = MagicMock(return_value=[_vec(1.0), _vec(3.0)])
    upsert = MagicMock()
    monkeypatch.setattr(svc, "_retrieve_vectors_sync", retrieve)
    monkeypatch.setattr(svc, "_upsert_centroid_sync", upsert)
    try:
        async with AsyncSessionLocal() as db:
            ok = await svc.compute_pool_centroid(db, pool_id)
        assert ok is True
        coll, ids = retrieve.call_args.args
        assert coll == "nexus_candidates" and sorted(ids) == sorted([cand_a, cand_b])
        upsert.assert_called_once_with(
            svc.POOL_CENTROIDS_COLLECTION, pool_id, _vec(2.0)
        )
        async with AsyncSessionLocal() as db:
            pool = await db.get(TalentPool, pool_id)
            assert pool.centroid_vector_id == str(pool_id)
    finally:
        await _drop(pool_ids=[pool_id], candidate_ids=[cand_a, cand_b])


async def test_pool_members_without_embeddings_keep_old_centroid(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    pool_id = await _make_pool(tag)
    cand = await _make_candidate(tag)
    async with AsyncSessionLocal() as db:
        db.add(TalentPoolMembership(talent_pool_id=pool_id, candidate_id=cand))
        await db.commit()
    monkeypatch.setattr(svc, "_retrieve_vectors_sync", MagicMock(return_value=[]))
    upsert = MagicMock()
    monkeypatch.setattr(svc, "_upsert_centroid_sync", upsert)
    try:
        async with AsyncSessionLocal() as db:
            assert await svc.compute_pool_centroid(db, pool_id) is False
        upsert.assert_not_called()
        async with AsyncSessionLocal() as db:
            assert (await db.get(TalentPool, pool_id)).centroid_vector_id == "stale"
    finally:
        await _drop(pool_ids=[pool_id], candidate_ids=[cand])


# ── compute_cc_centroid ──────────────────────────────────────────────────────


async def test_cc_without_members_falls_back_to_keyword_embedding(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    cc_id = await _make_cc(tag, keywords=["kubernetes", "terraform"])
    embed = AsyncMock(return_value=_vec(0.25))
    retrieve = MagicMock(side_effect=AssertionError("no primary members → no read"))
    upsert = MagicMock()
    monkeypatch.setattr("app.services.embedding_service.generate_embedding", embed)
    monkeypatch.setattr(svc, "_retrieve_vectors_sync", retrieve)
    monkeypatch.setattr(svc, "_upsert_centroid_sync", upsert)
    try:
        async with AsyncSessionLocal() as db:
            ok = await svc.compute_cc_centroid(db, cc_id)
        assert ok is True
        text = embed.await_args.args[0]
        for part in (
            f"Centroid PL {tag}",
            f"Centroid EN {tag}",
            "kubernetes",
            "terraform",
        ):
            assert part in text
        upsert.assert_called_once_with(CC_CENTROIDS_COLLECTION, cc_id, _vec(0.25))
        async with AsyncSessionLocal() as db:
            assert (await db.get(CompetenceCategory, cc_id)).embedding_id == str(cc_id)
    finally:
        await _drop(cc_ids=[cc_id])


async def test_cc_with_primary_members_uses_their_mean(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    cc_id = await _make_cc(tag)
    cand = await _make_candidate(tag)
    async with AsyncSessionLocal() as db:
        db.add(
            CandidateCompetenceCategory(
                candidate_id=cand, competence_category_id=cc_id, is_primary=True
            )
        )
        await db.commit()
    embed = AsyncMock(side_effect=AssertionError("members present → no fallback"))
    upsert = MagicMock()
    monkeypatch.setattr("app.services.embedding_service.generate_embedding", embed)
    monkeypatch.setattr(
        svc, "_retrieve_vectors_sync", MagicMock(return_value=[_vec(4.0), _vec(2.0)])
    )
    monkeypatch.setattr(svc, "_upsert_centroid_sync", upsert)
    try:
        async with AsyncSessionLocal() as db:
            assert await svc.compute_cc_centroid(db, cc_id) is True
        upsert.assert_called_once_with(CC_CENTROIDS_COLLECTION, cc_id, _vec(3.0))
    finally:
        await _drop(cc_ids=[cc_id], candidate_ids=[cand])


async def test_cc_bootstrap_failure_returns_false_without_upsert(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    cc_id = await _make_cc(tag)
    upsert = MagicMock()
    monkeypatch.setattr(
        "app.services.embedding_service.generate_embedding",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(svc, "_upsert_centroid_sync", upsert)
    try:
        async with AsyncSessionLocal() as db:
            assert await svc.compute_cc_centroid(db, cc_id) is False
        upsert.assert_not_called()
        async with AsyncSessionLocal() as db:
            assert (await db.get(CompetenceCategory, cc_id)).embedding_id is None
    finally:
        await _drop(cc_ids=[cc_id])


# ── refresh_stale_centroids ──────────────────────────────────────────────────


async def test_refresh_selects_every_cc_and_only_stale_pools(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    cc_id = await _make_cc(tag)
    never = await _make_pool(tag + "n", updated_at=None)
    old = await _make_pool(tag + "o", updated_at=now - timedelta(days=30))
    fresh = await _make_pool(tag + "f", updated_at=now)

    cc_calls: list[int] = []
    pool_calls: list[int] = []

    async def _cc(db, cid):
        cc_calls.append(cid)
        return cid == cc_id

    async def _pool(db, pid):
        pool_calls.append(pid)
        return pid in (never, old)

    monkeypatch.setattr(svc, "compute_cc_centroid", _cc)
    monkeypatch.setattr(svc, "compute_pool_centroid", _pool)
    try:
        async with AsyncSessionLocal() as db:
            stats = await svc.refresh_stale_centroids(db, stale_days=7)
    finally:
        await _drop(cc_ids=[cc_id], pool_ids=[never, old, fresh])

    assert cc_id in cc_calls
    assert never in pool_calls and old in pool_calls
    assert fresh not in pool_calls, "a centroid younger than stale_days is left alone"
    assert stats == {"cc_refreshed": 1, "pools_refreshed": 2}


# ── cc_centroid_sync loop ────────────────────────────────────────────────────


async def test_bootstrap_continues_after_one_cc_fails(monkeypatch):
    tag = uuid.uuid4().hex[:10]
    first, second = await _make_cc(tag + "a"), await _make_cc(tag + "b")
    called: list[int] = []

    async def _compute(db, cid):
        called.append(cid)
        if cid == first:
            raise RuntimeError("qdrant down")
        return True

    monkeypatch.setattr(sync_task, "compute_cc_centroid", _compute)
    try:
        async with AsyncSessionLocal() as db:
            await sync_task._bootstrap_if_needed(db)
    finally:
        await _drop(cc_ids=[first, second])

    assert first in called and second in called


async def test_bootstrap_skips_when_every_cc_has_an_embedding(monkeypatch):
    result = MagicMock()
    result.all.return_value = []
    db = AsyncMock()
    db.execute.return_value = result
    compute = AsyncMock()
    monkeypatch.setattr(sync_task, "compute_cc_centroid", compute)

    await sync_task._bootstrap_if_needed(db)

    compute.assert_not_awaited()


async def test_loop_one_pass_bootstraps_then_refreshes(monkeypatch):
    ensure = MagicMock()
    bootstrap = AsyncMock()
    refresh = AsyncMock(
        side_effect=[RuntimeError("refresh crashed"), {"cc_refreshed": 5}]
    )
    session = AsyncMock()
    monkeypatch.setattr(sync_task, "_ensure_centroid_collections", ensure)
    monkeypatch.setattr(sync_task, "_bootstrap_if_needed", bootstrap)
    monkeypatch.setattr(sync_task, "refresh_stale_centroids", refresh)
    monkeypatch.setattr(sync_task, "AsyncSessionLocal", MagicMock(return_value=session))
    sleep = AsyncMock(side_effect=[None, None, None, asyncio.CancelledError])
    monkeypatch.setattr(sync_task.asyncio, "sleep", sleep)

    await sync_task.cc_centroid_sync_loop()  # CancelledError in sleep → clean return

    ensure.assert_called_once_with()
    bootstrap.assert_awaited_once_with(session.__aenter__.return_value)
    assert refresh.await_count == 2, "a failed refresh does not end the loop"
    refresh.assert_awaited_with(session.__aenter__.return_value, stale_days=7)
    assert [c.args for c in sleep.await_args_list] == [
        (sync_task.BOOTSTRAP_DELAY_SECONDS,),
        (sync_task.REFRESH_INTERVAL_SECONDS,),
        (sync_task.REFRESH_INTERVAL_SECONDS,),
        (sync_task.REFRESH_INTERVAL_SECONDS,),
    ]


async def test_loop_cancelled_during_startup_delay_does_no_work(monkeypatch):
    ensure = MagicMock()
    monkeypatch.setattr(sync_task, "_ensure_centroid_collections", ensure)
    monkeypatch.setattr(
        sync_task.asyncio, "sleep", AsyncMock(side_effect=asyncio.CancelledError)
    )

    await sync_task.cc_centroid_sync_loop()

    ensure.assert_not_called()


async def test_loop_survives_collection_and_bootstrap_failures(monkeypatch):
    monkeypatch.setattr(
        sync_task,
        "_ensure_centroid_collections",
        MagicMock(side_effect=RuntimeError("x")),
    )
    monkeypatch.setattr(
        sync_task, "_bootstrap_if_needed", AsyncMock(side_effect=RuntimeError("y"))
    )
    refresh = AsyncMock(return_value={})
    monkeypatch.setattr(sync_task, "refresh_stale_centroids", refresh)
    monkeypatch.setattr(
        sync_task, "AsyncSessionLocal", MagicMock(return_value=AsyncMock())
    )
    monkeypatch.setattr(
        sync_task.asyncio,
        "sleep",
        AsyncMock(side_effect=[None, None, asyncio.CancelledError]),
    )

    await sync_task.cc_centroid_sync_loop()

    assert refresh.await_count == 1
