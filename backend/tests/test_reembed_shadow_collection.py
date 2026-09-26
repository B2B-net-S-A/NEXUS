"""`reembed_collections` — kolekcja-cień, paczki po znakach, --resume, outbox.

Budowa cienia v3 (docs/embedding-v3-ab-runbook.md) idzie w kontenerze
produkcji, więc trzy rzeczy muszą być pewne bez bazy i bez Qdranta:

* cień NIE dotyka stanu produkcji — ani ``candidates.embedding_id``, ani
  outboxu indeksu (zapis ``indexed_hash`` dla cienia okłamałby reconciler);
* długie teksty v3 nie przekraczają limitu tokenów jednego żądania Voyage;
* przerwany bieg wznawia się bez płacenia drugi raz za gotowe punkty.
"""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import scripts.reembed_collections as reembed
from app.core.config import settings
from app.services import canonical_text as ct


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return _Rows(self._rows)


class _Session:
    def __init__(self, scripted, log):
        self._scripted = scripted
        self._log = log
        self.added = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, statement, *_a, **_kw):
        self._log.append(statement)
        return _Result(self._scripted.pop(0) if self._scripted else [])

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        return None


def _updates(statements):
    return [s for s in statements if getattr(s, "__visit_name__", "") == "update"]


@pytest.fixture
def active_v1(monkeypatch):
    """Aplikacja w stanie produkcji: kolekcja aktywna, tekst v1."""
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V2", False)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", False)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", True)
    monkeypatch.setattr(reembed, "_collection", lambda: "nexus_candidates")
    monkeypatch.setattr(reembed, "_voyage_model", lambda: "voyage-3")


# ── paczki po znakach ────────────────────────────────────────────────────────


def test_char_batches_respect_the_char_ceiling_and_keep_order():
    texts = ["a" * 40, "b" * 40, "c" * 40, "d" * 10]
    assert reembed._char_batches(texts, max_chars=90, max_items=128) == [
        [0, 1],
        [2, 3],
    ]


def test_char_batches_respect_the_item_ceiling():
    texts = ["x"] * 5
    assert reembed._char_batches(texts, max_chars=10_000, max_items=2) == [
        [0, 1],
        [2, 3],
        [4],
    ]


def test_a_text_longer_than_the_ceiling_goes_alone_and_is_not_dropped():
    texts = ["s" * 5, "L" * 500, "s" * 5]
    batches = reembed._char_batches(texts, max_chars=100, max_items=128)
    assert batches == [[0], [1], [2]]
    assert sorted(i for b in batches for i in b) == [0, 1, 2]


def test_long_v3_texts_are_split_before_voyage(monkeypatch):
    """128 tekstów v3 po ~12k znaków to ~1,5 mln znaków w jednym żądaniu."""
    import asyncio

    calls = []

    async def fake_embed(texts, input_type):
        calls.append(sum(len(t) for t in texts))
        return [[0.0] for _ in texts]

    monkeypatch.setattr(reembed, "_voyage_embed_batch", fake_embed)
    texts = ["x" * 12_000] * 30
    out = asyncio.run(reembed._embed_texts(texts, max_chars=120_000, max_items=128))

    assert all(v == [0.0] for v in out)
    assert max(calls) <= 120_000
    assert len(calls) == 3


# ── cień vs aktywna kolekcja ─────────────────────────────────────────────────


def test_default_plan_is_the_active_collection(active_v1):
    plan = reembed._resolve_candidate_plan(
        collection=None, text_schema="active", record_outbox=False
    )
    assert (plan.collection, plan.shadow, plan.schema_stamp) == (
        "nexus_candidates",
        False,
        ct.TEXT_SCHEMA_V1,
    )


@pytest.mark.parametrize(
    "collection,schema",
    [
        ("nexus_candidates_v3", "v3"),
        ("nexus_candidates_v3", "active"),
        # Ta sama nazwa kolekcji, ale inny tekst niż aplikacja — też cień:
        # nadpisanie aktywnej kolekcji tekstem v3 nie może udawać stanu v1.
        (None, "v3"),
    ],
)
def test_other_collection_or_schema_is_a_shadow_build(active_v1, collection, schema):
    plan = reembed._resolve_candidate_plan(
        collection=collection, text_schema=schema, record_outbox=False
    )
    assert plan.shadow is True


def test_record_outbox_is_refused_for_a_shadow_build(active_v1):
    with pytest.raises(ValueError, match="record-outbox"):
        reembed._resolve_candidate_plan(
            collection="nexus_candidates_v3", text_schema="v3", record_outbox=True
        )


def test_record_outbox_is_allowed_after_the_switch(active_v1, monkeypatch):
    """Po przełączeniu env aktywna para to (cień, v3) — wtedy wolno."""
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", True)
    monkeypatch.setattr(reembed, "_collection", lambda: "nexus_candidates_v3")
    plan = reembed._resolve_candidate_plan(
        collection=None, text_schema="active", record_outbox=True
    )
    assert (plan.shadow, plan.record_outbox, plan.schema_stamp) == (
        False,
        True,
        ct.TEXT_SCHEMA_V3,
    )


def _cand(cid: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=cid,
        name="Jan",
        lastname="Kowalski",
        competence_category="data_ai",
        years_it_experience=4,
        skills=["Python"],
        verified_tech=None,
        experience=[{"role": "Data Engineer", "company": "Acme", "desc": "ETL"}],
        preferences=None,
        tags=None,
        ai_summary=None,
        raw_cv_text="Pelne CV kandydata: Spark, Airflow.",
        cv_extracted_data={"_notes_insights": {"skills_evidenced": ["Terraform"]}},
    )


@pytest.mark.asyncio
async def test_shadow_build_writes_v3_to_the_shadow_and_leaves_production_alone(
    active_v1, monkeypatch
):
    statements: list = []
    scripted = [[(1,), (2,)], [_cand(1), _cand(2)]]
    monkeypatch.setattr(
        reembed, "AsyncSessionLocal", lambda: _Session(scripted, statements)
    )
    embed = AsyncMock(return_value=[[0.1], [0.2]])
    monkeypatch.setattr(reembed, "_voyage_embed_batch", embed)
    upsert = AsyncMock(return_value=2)
    monkeypatch.setattr(reembed, "_bulk_upsert_qdrant", upsert)
    record = AsyncMock(return_value=0)
    monkeypatch.setattr(reembed, "_record_outbox_done", record)

    result = await reembed._reembed_candidates(
        commit=True,
        batch=10,
        limit=None,
        log_every=1000,
        collection="nexus_candidates_v3",
        text_schema="v3",
    )

    assert result == (2, 2, 0)
    collection, points = upsert.await_args.args
    assert collection == "nexus_candidates_v3"
    expected_text = ct.build_candidate_text_v3(_cand(1), include_notes=True)
    assert "[NOTES] Terraform" in expected_text
    assert embed.await_args.args[0][0] == expected_text
    assert (
        points[0]["payload"]["content_hash"]
        == hashlib.sha256(expected_text.encode()).hexdigest()
    )
    assert points[0]["payload"]["text_schema"] == ct.TEXT_SCHEMA_V3
    # Produkcja nietknięta: brak UPDATE embedding_id i brak zapisu outboxu.
    assert _updates(statements) == []
    record.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonotes_shadow_hashes_the_text_the_eval_arm_will_rebuild(
    active_v1, monkeypatch
):
    """Ramię evalu liczy świeżość punktu z dyspozytora pod env ramienia —
    hasz w cieniu musi być haszem DOKŁADNIE tego tekstu."""
    scripted = [[(1,)], [_cand(1)]]
    monkeypatch.setattr(reembed, "AsyncSessionLocal", lambda: _Session(scripted, []))
    monkeypatch.setattr(reembed, "_voyage_embed_batch", AsyncMock(return_value=[[0.1]]))
    upsert = AsyncMock(return_value=1)
    monkeypatch.setattr(reembed, "_bulk_upsert_qdrant", upsert)

    await reembed._reembed_candidates(
        commit=True,
        batch=10,
        limit=None,
        log_every=1000,
        collection="nexus_candidates_v3_nonotes",
        text_schema="v3-nonotes",
    )

    from app.services import embedding_service as emb

    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3", True)
    monkeypatch.setattr(settings, "AI_TEXT_SCHEMA_V3_NOTES", False)
    arm_text = emb._build_candidate_text(_cand(1))
    payload = upsert.await_args.args[1][0]["payload"]
    assert payload["content_hash"] == hashlib.sha256(arm_text.encode()).hexdigest()
    assert payload["text_schema"] == ct.TEXT_SCHEMA_V3_NO_NOTES


# ── --resume ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_resume_skips_points_with_the_same_content_and_model(
    active_v1, monkeypatch
):
    monkeypatch.setattr(reembed, "_build_candidate_text", lambda c: f"text {c.id}")
    same = hashlib.sha256(b"text 1").hexdigest()
    monkeypatch.setattr(
        reembed,
        "_qdrant_point_hashes",
        AsyncMock(
            return_value={
                1: (same, "voyage-3"),  # gotowy
                2: (hashlib.sha256(b"old text").hexdigest(), "voyage-3"),  # zmieniony
                3: (hashlib.sha256(b"text 3").hexdigest(), "voyage-3-large"),  # model
            }
        ),
    )
    scripted = [
        [(1,), (2,), (3,), (4,)],
        [SimpleNamespace(id=i, competence_category=None) for i in (1, 2, 3, 4)],
    ]
    monkeypatch.setattr(reembed, "AsyncSessionLocal", lambda: _Session(scripted, []))
    embed = AsyncMock(return_value=[[0.1], [0.2], [0.3]])
    monkeypatch.setattr(reembed, "_voyage_embed_batch", embed)
    upsert = AsyncMock(return_value=3)
    monkeypatch.setattr(reembed, "_bulk_upsert_qdrant", upsert)
    monkeypatch.setattr(reembed, "_mark_embedded", AsyncMock())

    result = await reembed._reembed_candidates(
        commit=True, batch=10, limit=None, log_every=1000, resume=True
    )

    assert result == (4, 4, 0)
    assert embed.await_args.args[0] == ["text 2", "text 3", "text 4"]
    assert [p["id"] for p in upsert.await_args.args[1]] == [2, 3, 4]


@pytest.mark.asyncio
async def test_record_outbox_covers_resumed_and_fresh_points(active_v1, monkeypatch):
    """Po przełączeniu: kandydat z gotowym wektorem też potrzebuje wpisu,
    inaczej reconciler porówna jego hasz v1 z v3 i zapłaci drugi raz."""
    monkeypatch.setattr(reembed, "_build_candidate_text", lambda c: f"text {c.id}")
    monkeypatch.setattr(
        reembed,
        "_qdrant_point_hashes",
        AsyncMock(
            return_value={1: (hashlib.sha256(b"text 1").hexdigest(), "voyage-3")}
        ),
    )
    cands = [
        SimpleNamespace(id=1, competence_category=None),
        SimpleNamespace(id=2, competence_category=None),
    ]
    scripted = [[(1,), (2,)], cands]
    monkeypatch.setattr(reembed, "AsyncSessionLocal", lambda: _Session(scripted, []))
    monkeypatch.setattr(reembed, "_voyage_embed_batch", AsyncMock(return_value=[[0.2]]))
    monkeypatch.setattr(reembed, "_bulk_upsert_qdrant", AsyncMock(return_value=1))
    monkeypatch.setattr(reembed, "_mark_embedded", AsyncMock())
    record = AsyncMock(side_effect=lambda cs: len(cs))
    monkeypatch.setattr(reembed, "_record_outbox_done", record)

    await reembed._reembed_candidates(
        commit=True,
        batch=10,
        limit=None,
        log_every=1000,
        resume=True,
        record_outbox=True,
    )

    recorded = record.await_args.args[0]
    assert sorted(c.id for c in recorded) == [1, 2]


@pytest.mark.asyncio
async def test_failed_upsert_is_not_recorded_in_the_outbox(active_v1, monkeypatch):
    monkeypatch.setattr(reembed, "_build_candidate_text", lambda c: f"text {c.id}")
    scripted = [[(1,)], [SimpleNamespace(id=1, competence_category=None)]]
    monkeypatch.setattr(reembed, "AsyncSessionLocal", lambda: _Session(scripted, []))
    monkeypatch.setattr(reembed, "_voyage_embed_batch", AsyncMock(return_value=[[0.2]]))
    monkeypatch.setattr(
        reembed, "_bulk_upsert_qdrant", AsyncMock(side_effect=RuntimeError("down"))
    )
    record = AsyncMock(return_value=0)
    monkeypatch.setattr(reembed, "_record_outbox_done", record)

    result = await reembed._reembed_candidates(
        commit=True, batch=10, limit=None, log_every=1000, record_outbox=True
    )

    assert result == (1, 0, 1)
    assert record.await_args.args[0] == []


@pytest.mark.asyncio
async def test_outbox_rows_carry_the_hash_the_reconciler_compares(
    active_v1, monkeypatch
):
    from datetime import datetime, timezone

    from app.models.index_outbox import IndexOutboxEvent
    from app.services import index_outbox_service as outbox

    sessions: list[_Session] = []

    def factory():
        s = _Session([], [])
        sessions.append(s)
        return s

    monkeypatch.setattr(reembed, "AsyncSessionLocal", factory)
    monkeypatch.setattr(
        "app.services.embedding_service._voyage_model", lambda: "voyage-3"
    )
    cand = _cand(7)
    cand.updated_at = datetime(2026, 9, 26, tzinfo=timezone.utc)

    assert await reembed._record_outbox_done([cand]) == 1

    (row,) = sessions[0].added
    assert isinstance(row, IndexOutboxEvent)
    assert (row.status, row.operation, row.entity_type, row.entity_id) == (
        "done",
        "upsert",
        outbox.CANDIDATE,
        7,
    )
    assert row.indexed_hash == row.desired_hash
    assert row.indexed_revision == row.entity_revision == outbox._revision(cand)
    # Reconciler porównuje `hashes_match`, nie `!=` — i ma trafić.
    assert outbox.hashes_match(
        outbox.desired_state(outbox.CANDIDATE, cand), row.indexed_hash
    )


@pytest.mark.asyncio
async def test_estimate_builds_texts_but_never_calls_voyage_or_qdrant(
    active_v1, monkeypatch, caplog
):
    scripted = [[(1,), (2,)], [_cand(1), _cand(2)]]
    monkeypatch.setattr(reembed, "AsyncSessionLocal", lambda: _Session(scripted, []))
    embed = AsyncMock()
    upsert = AsyncMock()
    monkeypatch.setattr(reembed, "_voyage_embed_batch", embed)
    monkeypatch.setattr(reembed, "_bulk_upsert_qdrant", upsert)

    with caplog.at_level("INFO", logger="reembed_collections"):
        result = await reembed._reembed_candidates(
            commit=False,
            batch=10,
            limit=None,
            log_every=1000,
            collection="nexus_candidates_v3",
            text_schema="v3",
            estimate=True,
        )

    assert result == (2, 0, 0)
    embed.assert_not_awaited()
    upsert.assert_not_awaited()
    chars = 2 * len(ct.build_candidate_text_v3(_cand(1), include_notes=True))
    assert f"{chars} chars total" in caplog.text


# ── CLI ─────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["--target", "all", "--commit", "--collection", "x"],
        ["--target", "jobs", "--commit", "--text-schema", "v3"],
        ["--target", "all", "--commit", "--resume"],
        ["--target", "candidates", "--commit", "--record-outbox", "--prune-orphans"],
        ["--target", "candidates", "--commit", "--max-batch-chars", "10"],
        ["--target", "candidates", "--commit", "--batch", "500"],
        ["--target", "candidates", "--commit", "--estimate"],
        ["--target", "all", "--dry-run", "--estimate"],
    ],
)
def test_cli_rejects_combinations_outside_the_contract(argv):
    with pytest.raises(SystemExit):
        reembed._parse_args(argv)


def test_cli_accepts_the_runbook_shadow_command():
    args = reembed._parse_args(
        [
            "--target",
            "candidates",
            "--commit",
            "--collection",
            "nexus_candidates_v3",
            "--text-schema",
            "v3",
            "--ensure-collection",
            "--resume",
            "--max-batch-chars",
            "120000",
        ]
    )
    assert (args.collection, args.text_schema, args.resume, args.record_outbox) == (
        "nexus_candidates_v3",
        "v3",
        True,
        False,
    )
