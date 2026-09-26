"""The reconciler removes the need for writers to remember.

Three Traffit phases change fields that feed the embedding text and record no
reindex intent. Patching those three fixes three; the class of bug is "every
writer must remember", and only something that asks nobody closes it.

Uses the real DB (outbox rows + real entities), like `test_index_outbox.py`.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.index_outbox import IndexOutboxEvent
from app.services import index_drift_reconciler as rec
from app.services import index_outbox_service as outbox


async def _fresh_candidate(db) -> Candidate:
    c = Candidate(
        name="Rec",
        lastname=f"Onciler-{uuid.uuid4().hex[:8]}",
        email=f"rec-{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(c)
    await db.flush()
    return c


async def _record_indexed(db, candidate: Candidate, *, hash_value: str) -> None:
    """Pretend the worker successfully indexed this entity with `hash_value`."""
    db.add(
        IndexOutboxEvent(
            entity_type=outbox.CANDIDATE,
            entity_id=candidate.id,
            entity_revision=1,
            desired_hash=hash_value,
            indexed_hash=hash_value,
            indexed_revision=1,
            operation="upsert",
            status="done",
        )
    )
    await db.flush()


async def _pending_ids(db, candidate_id: int) -> list[int]:
    # `record_bulk_reindex` uses `db.add()` and leaves committing to the caller,
    # so the rows are pending in the session until flushed.
    await db.flush()
    rows = await db.execute(
        text(
            "SELECT id FROM match_index_outbox WHERE entity_type='candidate' "
            "AND entity_id=:cid AND status='pending'"
        ),
        {"cid": candidate_id},
    )
    return [r[0] for r in rows.all()]


@pytest.mark.asyncio
async def test_content_change_without_any_reindex_intent_is_detected():
    """The whole point: nobody told the index anything, and it still notices."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        current = outbox.desired_state(outbox.CANDIDATE, cand).desired_hash
        await _record_indexed(db, cand, hash_value=current)

        # A writer changes a field that feeds the embedding text and — exactly
        # like the three Traffit phases — records nothing.
        cand.ai_summary = "Senior backend engineer, 8 lat w fintechu."
        await db.flush()

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.drifted == 1, "content changed but no reindex was enqueued"
        assert await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_unchanged_entity_is_not_re_enqueued():
    """Otherwise every pass would re-embed the entire base — the reconciler
    would become the most expensive no-op in the system."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        current = outbox.desired_state(outbox.CANDIDATE, cand).desired_hash
        await _record_indexed(db, cand, hash_value=current)

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.drifted == 0
        assert not await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_entity_the_outbox_never_saw_is_skipped_not_enqueued():
    """Those are the initial-population gap (`reembed --only-missing`), not
    drift. Counting them as drift would enqueue tens of thousands of re-embeds
    on the first tick and re-bill the entire import."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)  # no outbox history at all

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.unseen == 1
        assert result.drifted == 0
        assert not await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_unseen_entities_can_be_opted_in():
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)

        result = await rec.reconcile_once(
            db,
            entity_type=outbox.CANDIDATE,
            cursor=cand.id - 1,
            batch=1,
            include_unseen=True,
        )
        assert result.unseen == 1
        assert await _pending_ids(db, cand.id)
        await db.rollback()


@pytest.mark.asyncio
async def test_a_pending_event_does_not_count_as_indexed():
    """A pending or failed row describes an INTENT, not the state of the index.
    Reading it as "already handled" would let a stale vector sit forever while
    the reconciler reported everything in order."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        db.add(
            IndexOutboxEvent(
                entity_type=outbox.CANDIDATE,
                entity_id=cand.id,
                entity_revision=1,
                desired_hash=outbox.desired_state(outbox.CANDIDATE, cand).desired_hash,
                operation="upsert",
                status="pending",
            )
        )
        await db.flush()

        result = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=cand.id - 1, batch=1
        )
        assert result.unseen == 1, "a pending event was mistaken for a done one"
        await db.rollback()


@pytest.mark.asyncio
async def test_cursor_walks_forward_and_reports_the_end_of_the_table():
    async with AsyncSessionLocal() as db:
        first = await _fresh_candidate(db)
        second = await _fresh_candidate(db)

        page = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=first.id - 1, batch=1
        )
        assert page.scanned == 1
        assert page.next_cursor == first.id

        page2 = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=page.next_cursor, batch=1
        )
        assert page2.next_cursor == second.id

        # Past the last row, but inside INTEGER range — candidates.id is int32,
        # so a sentinel like 10**12 fails in the driver rather than in the query.
        end = await rec.reconcile_once(
            db, entity_type=outbox.CANDIDATE, cursor=2**31 - 1, batch=1
        )
        assert end.next_cursor is None and end.scanned == 0
        await db.rollback()


def test_reconciler_ships_enabled_behind_a_provider_gate():
    """Włączony od 18.09.2026 — ale z bramką, która zamyka powód wyłączenia.

    Pierwotne uzasadnienie („nie może startować, zanim powstaną sondy zdrowia
    dostawców: przy ``AI_INDEX_MAX_ATTEMPTS=5`` awaria Voyage'a plus reconciler
    karmiący workera wypala backlog w wiersze ``dead`` za zielonym healthem")
    było słuszne i NIE zniknęło samo. Sondy istnieją (`checks.voyage`,
    `checks.qdrant`), a tik przy niezdrowym dostawcy nic nie zapisuje.

    Cena wyłączenia była zmierzona: 128 z 307 opublikowanych rekrutacji (41,7%)
    bez wektora i 1 932 osierocone punkty kandydatów — a sama pętla była
    zwolniona z heartbeatu, więc jej cisza nie była nawet widoczna.
    """
    from app.core.config import Settings
    from app.services import loop_heartbeat
    from app.tasks import index_drift_reconciler_task as task

    assert Settings.model_fields["AI_INDEX_RECONCILER_ENABLED"].default is True
    # Bramka dostawcy — bez niej ta zmiana byłaby cofnięciem tamtej decyzji.
    assert hasattr(task, "embedding_provider_down")
    # Heartbeat: pętla, która żyje i nic nie robi, ma być widoczna.
    assert "index_drift_reconciler" not in loop_heartbeat.EXEMPT


def test_provider_gate_pauses_only_on_a_real_outage(monkeypatch):
    """``unknown`` to „jeszcze nie wołaliśmy", nie awaria.

    Gdyby `unknown` pauzowało, reconciler po KAŻDYM deployu stałby do pierwszego
    niezwiązanego wywołania modelu — czyli dokładnie wtedy, gdy dryf po imporcie
    jest największy.
    """
    from app.tasks import index_drift_reconciler_task as task

    for label, paused in (
        ("unhealthy", True),
        ("degraded", False),
        ("unknown", False),
        ("healthy", False),
    ):
        monkeypatch.setattr(
            "app.services.ai_health.provider_health_label", lambda _p, r=label: r
        )
        assert task.embedding_provider_down() is paused, label


# ── Audyt 22.09 r2 (INTG-05): opublikowane rekrutacje bez wektora ──────────


async def _fresh_job(db, *, published: bool):
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    client = Client(name=f"INTG-05 {uuid.uuid4().hex[:8]}")
    db.add(client)
    await db.flush()
    job = Job(
        title="Reconciler Job",
        client_id=client.id,
        status=JobStatus.published if published else JobStatus.closed,
    )
    db.add(job)
    await db.flush()
    return job


async def _job_pending(db, job_id: int) -> int:
    await db.flush()
    return (
        await db.execute(
            text(
                "SELECT count(*) FROM match_index_outbox WHERE entity_type='job' "
                "AND entity_id=:j AND status='pending'"
            ),
            {"j": job_id},
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_published_job_the_index_never_saw_is_enqueued_once():
    from app.tasks.index_drift_reconciler_task import _job_is_published

    async with AsyncSessionLocal() as db:
        job = await _fresh_job(db, published=True)
        for _ in range(2):
            await rec.reconcile_once(
                db,
                entity_type=outbox.JOB,
                cursor=job.id - 1,
                batch=1,
                unseen_predicate=_job_is_published,
            )
        # Druga pętla nie dubluje intencji, która wciąż czeka w kolejce.
        assert await _job_pending(db, job.id) == 1
        await db.rollback()


@pytest.mark.asyncio
async def test_closed_job_the_index_never_saw_is_still_skipped():
    from app.tasks.index_drift_reconciler_task import _job_is_published

    async with AsyncSessionLocal() as db:
        job = await _fresh_job(db, published=False)
        result = await rec.reconcile_once(
            db,
            entity_type=outbox.JOB,
            cursor=job.id - 1,
            batch=1,
            unseen_predicate=_job_is_published,
        )
        assert result.unseen == 1
        assert await _job_pending(db, job.id) == 0
        await db.rollback()


def test_the_loop_passes_the_published_predicate_only_for_jobs():
    import inspect

    from app.tasks import index_drift_reconciler_task as task

    src = inspect.getsource(task.index_drift_reconciler_loop)
    assert "_job_is_published if entity_type == outbox.JOB else None" in src


# ── Runda 8 (R8-N11-4): kandydat, którego intencja umarła ──────────────────


async def _add_event(db, candidate_id: int, *, status: str, hash_value: str = "h"):
    db.add(
        IndexOutboxEvent(
            entity_type=outbox.CANDIDATE,
            entity_id=candidate_id,
            entity_revision=1,
            desired_hash=hash_value,
            indexed_hash=hash_value if status == "done" else None,
            indexed_revision=1 if status == "done" else None,
            operation="upsert" if hash_value else "delete",
            status=status,
            attempts=5 if status == "dead" else 0,
        )
    )
    await db.flush()


@pytest.mark.asyncio
async def test_candidate_whose_only_intent_died_is_revived():
    """Qdrant leżał dłużej niż budżet prób: intencja `dead`, żadnego `done`.

    Do rundy 8 reconciler traktował takiego kandydata jak „nigdy nie
    widzianego" i pomijał go — nie dostawał wektora nigdy.
    """
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        await _add_event(db, cand.id, status="dead")
        result = await rec.reconcile_once(
            db,
            entity_type=outbox.CANDIDATE,
            cursor=cand.id - 1,
            batch=1,
            revive_dead_unseen=True,
        )
        assert result.revived == 1
        assert len(await _pending_ids(db, cand.id)) == 1
        # Drugi przebieg nie dubluje intencji w toku.
        await rec.reconcile_once(
            db,
            entity_type=outbox.CANDIDATE,
            cursor=cand.id - 1,
            batch=1,
            revive_dead_unseen=True,
        )
        assert len(await _pending_ids(db, cand.id)) == 1
        await db.rollback()


@pytest.mark.asyncio
async def test_quarantined_candidate_with_an_old_dead_intent_is_not_revived():
    """Kwarantanna zostawia `done` z pustym haszem — nie wolno jej odwrócić."""
    async with AsyncSessionLocal() as db:
        cand = await _fresh_candidate(db)
        await _add_event(db, cand.id, status="dead")
        await _add_event(db, cand.id, status="done", hash_value="")
        result = await rec.reconcile_once(
            db,
            entity_type=outbox.CANDIDATE,
            cursor=cand.id - 1,
            batch=1,
            revive_dead_unseen=True,
        )
        assert result.revived == 0
        assert await _pending_ids(db, cand.id) == []
        await db.rollback()


def test_the_loop_revives_candidates_and_syncs_job_statuses():
    import inspect

    from app.tasks import index_drift_reconciler_task as task

    src = inspect.getsource(task.index_drift_reconciler_loop)
    assert "revive_dead_unseen=entity_type == outbox.CANDIDATE" in src
    assert "sync_job_status=entity_type == outbox.JOB" in src


# ── Runda 8 (R8-N11-2): status oferty w payloadzie Qdranta ─────────────────


@pytest.mark.asyncio
async def test_job_status_drift_in_payload_is_repaired(monkeypatch):
    """Archiwum Traffita/0378 zamyka rekrutacje SQL-em — payload mówił dalej
    „published" i zajmował pulę ofert. Reconciler porównuje i poprawia."""
    from types import SimpleNamespace

    from app.models.job import JobStatus
    from app.services import embedding_service

    rows = [
        SimpleNamespace(id=1, status=JobStatus.closed),
        SimpleNamespace(id=2, status=JobStatus.published),
        SimpleNamespace(id=3, status=JobStatus.published),
    ]
    written: dict = {}

    async def _payload(_ids):
        # Punktu 3 nie ma w Qdrancie.
        return {1: "published", 2: "published"}

    async def _sync(statuses):
        written.update(statuses)
        return len(statuses)

    monkeypatch.setattr(embedding_service, "job_payload_statuses", _payload)
    monkeypatch.setattr(embedding_service, "sync_job_status_payloads", _sync)

    assert await rec._sync_job_statuses(rows) == 1
    assert written == {1: "closed"}


@pytest.mark.asyncio
async def test_job_status_sync_is_silent_when_qdrant_is_unknown(monkeypatch):
    from types import SimpleNamespace

    from app.models.job import JobStatus
    from app.services import embedding_service

    async def _unknown(_ids):
        return None

    async def _never(_statuses):  # pragma: no cover — nie może być wołane
        raise AssertionError("zapis bez odczytu")

    monkeypatch.setattr(embedding_service, "job_payload_statuses", _unknown)
    monkeypatch.setattr(embedding_service, "sync_job_status_payloads", _never)
    rows = [SimpleNamespace(id=1, status=JobStatus.closed)]
    assert await rec._sync_job_statuses(rows) == 0
