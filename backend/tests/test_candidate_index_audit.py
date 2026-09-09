from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services import candidate_index_audit as audit
from app.services.full_candidate_scan import CandidateSnapshot


def test_matching_counts_never_prove_membership_or_freshness():
    from app.api.admin_index_coverage import _gap

    for points in (0, 10, 12, None):
        result = _gap(10, points)
        assert result["missing"] is None and result["indexed"] is None
        assert result["coverage_pct"] is None
        assert result["index_points"] == points


def test_point_validation_and_provenance_are_both_required(monkeypatch):
    monkeypatch.setattr(audit.embeddings, "VECTOR_SIZE", 2)

    def point(vector, payload):
        return audit.describe_point(
            SimpleNamespace(id=1, vector=vector, payload=payload)
        )

    valid = point([1, 0], {"content_hash": "h", "embedding_model": "m"})
    assert audit.classify("h", valid, "m") == "current"
    assert audit.classify("h", None, "m") == "missing"
    assert audit.classify("new", valid, "m") == "stale_or_unverified_content"
    assert audit.classify("h", valid, "new") == "wrong_or_unknown_model"
    for vector in (
        [0, 0],
        [float("nan"), 0],
        ["1", 0],
        [True, 0],
        [1],
        {"named": [1, 0]},
    ):
        assert audit.classify("h", point(vector, {}), "m") == "invalid_vector"
    monkeypatch.setattr(audit.embeddings, "_build_candidate_text", lambda _: "")
    assert audit.text_hash(object()) is None


@pytest.mark.asyncio
async def test_mass_reembedding_writes_verifiable_model_and_content(monkeypatch):
    from scripts import reembed_collections as script
    import hashlib

    candidate = SimpleNamespace(id=1, competence_category="software")
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(all=lambda: [(1,)]),
                SimpleNamespace(
                    scalars=lambda: SimpleNamespace(all=lambda: [candidate])
                ),
            ]
        )
    )
    session = AsyncMock()
    session.__aenter__.return_value = db
    monkeypatch.setattr(script, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(script, "_build_candidate_text", lambda _: "Python")
    monkeypatch.setattr(script, "_voyage_model", lambda: "m")
    monkeypatch.setattr(script, "_voyage_embed_batch", AsyncMock(return_value=[[1, 0]]))
    upsert = AsyncMock(return_value=1)
    monkeypatch.setattr(script, "_bulk_upsert_qdrant", upsert)
    monkeypatch.setattr(script, "_mark_embedded", AsyncMock())
    result = await script._reembed_candidates(
        batch=10, limit=None, commit=True, log_every=100
    )
    assert result == (1, 1, 0)
    payload = upsert.call_args.args[1][0]["payload"]
    assert payload["embedding_model"] == "m"
    assert payload["content_hash"] == hashlib.sha256(b"Python").hexdigest()


@pytest.mark.asyncio
async def test_read_only_audit_covers_all_sql_ids_and_reports_real_orphans(monkeypatch):
    population = [CandidateSnapshot(i, "v") for i in range(1, 5)]
    monkeypatch.setattr(
        audit, "snapshot_candidate_population", AsyncMock(return_value=population)
    )
    points = {
        "1": audit.IndexPoint("1", "h1", "m", True),
        "2": audit.IndexPoint("2", "old", "m", True),
        "99": audit.IndexPoint("99", "orphan", "m", True),
    }
    monkeypatch.setattr(audit, "index_points", AsyncMock(return_value=points))
    monkeypatch.setattr(audit.embeddings, "_voyage_model", lambda: "m")
    seen = []

    async def load(_db, batch):
        seen.extend(item.candidate_id for item in batch)
        return {
            item.candidate_id: SimpleNamespace(id=item.candidate_id) for item in batch
        }

    monkeypatch.setattr(audit, "load_snapshot_batch", load)
    monkeypatch.setattr(audit, "text_hash", lambda candidate: f"h{candidate.id}")
    result = await audit.audit_candidates(object(), batch_size=2)
    assert seen == [1, 2, 3, 4]
    assert result["counts"] == {
        "current": 1,
        "missing": 2,
        "stale_or_unverified_content": 1,
    }
    assert result["orphan_point_ids"] == ["99"]
    assert result["fingerprint"] == audit.fingerprint(result)
    assert result["database_unchanged"]


@pytest.mark.asyncio
async def test_failed_or_tampered_audit_cannot_queue_repairs():
    manifest = {"schema": "candidate-index-audit-v1", "database_unchanged": False}
    manifest["fingerprint"] = audit.fingerprint(manifest)
    with pytest.raises(ValueError, match="incomplete"):
        await audit.enqueue_approved_repair(object(), manifest, manifest["fingerprint"])
    manifest["database_unchanged"] = True
    with pytest.raises(ValueError, match="fingerprint"):
        await audit.enqueue_approved_repair(object(), manifest, manifest["fingerprint"])


@pytest.mark.asyncio
async def test_index_outage_cannot_be_reported_as_missing_everyone(monkeypatch):
    monkeypatch.setattr(
        audit, "snapshot_candidate_population", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        audit, "index_points", AsyncMock(side_effect=RuntimeError("unavailable"))
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        await audit.audit_candidates(object())


@pytest.mark.asyncio
async def test_repair_queues_only_approved_stale_ids_and_never_orphans(monkeypatch):
    from app.services import index_outbox_service as outbox

    monkeypatch.setattr(audit.embeddings, "_voyage_model", lambda: "m")
    monkeypatch.setattr(audit.embeddings, "_collection", lambda: "c")
    monkeypatch.setattr(audit, "text_hash", lambda candidate: f"h{candidate.id}")
    manifest = {
        "schema": "candidate-index-audit-v1",
        "model": "m",
        "collection": "c",
        "database_unchanged": True,
        "orphan_point_ids": ["99"],
        "candidates": [
            {
                "candidate_id": i,
                "candidate_version": "v",
                "content_hash": f"h{i}",
                "state": state,
            }
            for i, state in [
                (1, "current"),
                (2, "missing"),
                (3, "stale_or_unverified_content"),
            ]
        ],
    }
    manifest["fingerprint"] = audit.fingerprint(manifest)
    db = SimpleNamespace(
        execute=AsyncMock(
            side_effect=[
                SimpleNamespace(
                    scalars=lambda: [
                        SimpleNamespace(id=i, updated_at="v") for i in [2, 3]
                    ]
                ),
                SimpleNamespace(all=lambda: [(3, "h3")]),
            ]
        ),
        flush=AsyncMock(),
    )
    enqueue = AsyncMock(return_value=1)
    monkeypatch.setattr(outbox, "record_bulk_reindex", enqueue)
    result = await audit.enqueue_approved_repair(db, manifest, manifest["fingerprint"])
    enqueue.assert_awaited_once_with(db, outbox.CANDIDATE, [2])
    assert result == {
        "queued": 1,
        "already_pending": 1,
        "deleted": 0,
        "orphans_reported_only": 1,
    }

    enqueue.reset_mock()
    db.execute = AsyncMock(
        return_value=SimpleNamespace(
            scalars=lambda: [SimpleNamespace(id=2, updated_at="new")]
        )
    )
    with pytest.raises(ValueError, match="changed"):
        await audit.enqueue_approved_repair(db, manifest, manifest["fingerprint"])
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_index_scroll_uses_all_sparse_id_pages_and_closes_clients(monkeypatch):
    monkeypatch.setattr(audit.embeddings, "VECTOR_SIZE", 2)

    def point(candidate_id):
        return SimpleNamespace(id=candidate_id, vector=[1, 0], payload={})

    client = SimpleNamespace(
        scroll=Mock(side_effect=[([point(3)], 900), ([point(900)], None)]), close=Mock()
    )
    monkeypatch.setattr(audit.embeddings, "_get_qdrant_client", lambda: client)

    async def execute(fn):
        return fn()

    monkeypatch.setattr(audit.embeddings, "_run_qdrant", execute)
    result = await audit.index_points()
    assert set(result) == {"3", "900"}
    assert client.scroll.call_args_list[1].kwargs["offset"] == 900
    assert client.close.call_count == 2
