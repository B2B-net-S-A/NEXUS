"""Testy backfill candidate_stage_cvs (migracja 0070 + standalone script).

Strategia: testujemy tę samą SQL logikę co migracja, używając naszej DB
(bez bawienia się Alembic od zera). Sprawdzamy:

* Backfill tworzy rzędy dla stage'ów bez csv.
* Pomija stage'y które już mają csv (idempotent na re-run).
* Kandydat bez CV → csv stworzony z `original_cv_*` NULL i source NULL.
* Batchowanie nie gubi rzędów.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import delete, select, text

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_stage_cv import CandidateStageCV
from app.models.client import Client
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


# Użyjemy tego samego SQL co w migracji 0070, ale zostawimy `LIMIT :n` jako
# parametr żeby testy mogły walidować batching.
_BACKFILL_SQL = """
INSERT INTO candidate_stage_cvs (
    candidate_stage_id, candidate_id, job_id,
    original_cv_filename, original_cv_content, original_cv_language,
    original_snapshot_at, original_snapshot_source,
    branded_status, created_at, updated_at
)
SELECT cs.id, cs.candidate_id, cs.job_id,
       c.cv_filename, c.cv_file_content, c.cv_language,
       CASE WHEN c.cv_file_content IS NOT NULL THEN now() ELSE NULL END,
       CASE WHEN c.cv_file_content IS NOT NULL THEN 'backfill_0070' ELSE NULL END,
       'none', now(), now()
FROM candidate_stages cs
JOIN candidates c ON cs.candidate_id = c.id
LEFT JOIN candidate_stage_cvs csv ON csv.candidate_stage_id = cs.id
WHERE csv.id IS NULL
ORDER BY cs.id
LIMIT :batch_size
"""


async def _seed_stages_no_csv(*, with_cv: int, without_cv: int) -> list[int]:
    """Stwórz N+M stages, pierwsze N z CV, ostatnie M bez. Zwróć ich id."""
    ids: list[int] = []
    async with AsyncSessionLocal() as db:
        unique = uuid.uuid4().hex[:6]
        cli = Client(name=f"Klient BF {unique}")
        db.add(cli)
        await db.flush()
        for i in range(with_cv + without_cv):
            cv_bytes = (
                f"PDF-bytes-{unique}-{i}".encode("utf-8")
                if i < with_cv
                else None
            )
            cand = Candidate(
                name="BF",
                lastname=f"C{unique}-{i}",
                email=f"bf-{unique}-{i}@example.com",
                cv_filename=f"cv-{i}.pdf" if cv_bytes else None,
                cv_file_content=cv_bytes,
                cv_language="pl" if cv_bytes else None,
            )
            db.add(cand)
            await db.flush()
            job = Job(
                title=f"Job BF {unique}-{i}",
                client_id=cli.id,
                description="x",
            )
            db.add(job)
            await db.flush()
            stage = CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.new,
            )
            db.add(stage)
            await db.flush()
            ids.append(stage.id)
        await db.commit()
    return ids


async def _delete_csvs_for_stages(stage_ids: list[int]) -> None:
    """Wyczyść csv'y żeby symulować "pre-feature" stage'y bez snapshot."""
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id.in_(stage_ids)
            )
        )
        await db.commit()


async def _run_backfill(batch_size: int) -> int:
    """Wykonaj backfill loop, zwróć liczbę wstawionych w sumie."""
    inserted_total = 0
    async with AsyncSessionLocal() as db:
        while True:
            res = await db.execute(
                text(_BACKFILL_SQL), {"batch_size": batch_size}
            )
            count = res.rowcount or 0
            inserted_total += count
            await db.commit()
            if count < batch_size:
                break
    return inserted_total


@pytest.mark.asyncio
async def test_backfill_creates_csv_for_each_stage():
    stage_ids = await _seed_stages_no_csv(with_cv=3, without_cv=2)
    # Hook'i serwisu już stworzyły csv przy CREATE — usuwamy je, symulujemy
    # historyczne stages bez snapshotu.
    await _delete_csvs_for_stages(stage_ids)

    inserted = await _run_backfill(batch_size=10)
    assert inserted >= 5  # nasze 5 stages (mogą być inne historyczne stage'y)

    async with AsyncSessionLocal() as db:
        for sid in stage_ids:
            csv = await db.scalar(
                select(CandidateStageCV).where(
                    CandidateStageCV.candidate_stage_id == sid
                )
            )
            assert csv is not None, f"stage {sid} not backfilled"


@pytest.mark.asyncio
async def test_backfill_idempotent_on_rerun():
    """Drugi backfill po pierwszym → 0 nowych wierszy."""
    stage_ids = await _seed_stages_no_csv(with_cv=2, without_cv=1)
    await _delete_csvs_for_stages(stage_ids)
    first = await _run_backfill(batch_size=100)
    second = await _run_backfill(batch_size=100)
    assert first >= 3
    assert second == 0


@pytest.mark.asyncio
async def test_backfill_handles_candidate_without_cv():
    """Kandydat bez CV → csv stworzony, ale `original_*` NULL i source NULL."""
    stage_ids = await _seed_stages_no_csv(with_cv=0, without_cv=1)
    await _delete_csvs_for_stages(stage_ids)
    await _run_backfill(batch_size=10)

    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_ids[0]
            )
        )
        assert csv is not None
        assert csv.original_cv_content is None
        assert csv.original_cv_filename is None
        assert csv.original_snapshot_source is None
        assert csv.branded_status == "none"


@pytest.mark.asyncio
async def test_backfill_with_cv_sets_source_correctly():
    stage_ids = await _seed_stages_no_csv(with_cv=1, without_cv=0)
    await _delete_csvs_for_stages(stage_ids)
    await _run_backfill(batch_size=10)

    async with AsyncSessionLocal() as db:
        csv = await db.scalar(
            select(CandidateStageCV).where(
                CandidateStageCV.candidate_stage_id == stage_ids[0]
            )
        )
        assert csv is not None
        assert csv.original_cv_content is not None
        assert csv.original_cv_filename is not None
        assert csv.original_snapshot_source == "backfill_0070"
        assert csv.original_snapshot_at is not None


@pytest.mark.asyncio
async def test_backfill_batching_inserts_all_rows():
    """6 stages × batch_size=2 → kilka iteracji, ale wszystkie wstawione."""
    stage_ids = await _seed_stages_no_csv(with_cv=4, without_cv=2)
    await _delete_csvs_for_stages(stage_ids)
    inserted = await _run_backfill(batch_size=2)
    assert inserted >= 6

    async with AsyncSessionLocal() as db:
        for sid in stage_ids:
            csv = await db.scalar(
                select(CandidateStageCV).where(
                    CandidateStageCV.candidate_stage_id == sid
                )
            )
            assert csv is not None
