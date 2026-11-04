"""Jednorazowe archiwum rekrutacji sprzed startu NEXUSA (decyzja Artura 25.09.2026).

Kontrakt:
* rekrutacja założona przed 25.09.2026 (Warszawa) — dowolnego źródła — jest
  zamknięta i „Zakończona”, z wpisem ``archived`` w historii, a ``closed_at``
  zostaje nietknięty (hit ratio Ligi DL go czyta);
* rekrutacja założona od 25.09.2026 jest nietknięta;
* korekta jest jednorazowa (znacznik w ``app_settings``) — drugi przebieg nie
  zamyka rekrutacji otwartej z powrotem;
* SQL ma jedno źródło, lustrzane w migracji 0378 i entrypoint.sh.

Baza testowa wspólna i nieczyszczona — asercje tylko na własnych wierszach,
a znacznik jest zdejmowany przed przebiegiem i przywracany po nim.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.job_archive_cutover import (
    ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL,
    MARKER_KEY,
)

BACKEND = Path(__file__).resolve().parent.parent
WARSAW = ZoneInfo("Europe/Warsaw")
BEFORE_CUTOFF = datetime(2026, 9, 24, 23, 59, tzinfo=WARSAW)
AFTER_CUTOFF = datetime(2026, 9, 25, 0, 1, tzinfo=WARSAW)


def test_entrypoint_mirrors_the_cutover_sql() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL in entrypoint


def test_migration_runs_the_same_cutover_sql() -> None:
    migration = (
        BACKEND / "alembic" / "versions" / "0378_archive_jobs_before_nexus_start.py"
    ).read_text(encoding="utf-8")
    assert (
        "from app.services.job_archive_cutover import "
        "ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL"
    ) in migration
    assert "op.execute(ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL)" in migration


def test_marker_key_matches_the_sql() -> None:
    assert f"'{MARKER_KEY}'" in ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL


async def _seed_job(*, created_at: datetime, source: str, status: str) -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Cutover-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Cutover-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus(status),
            client_id=client.id,
            external_source=source,
            external_id=uuid.uuid4().hex if source == "traffit" else None,
            managed_in_nexus=source == "traffit",
            is_open=status == "published",
            work_state="searching",
        )
        db.add(job)
        await db.flush()
        await db.execute(
            text("UPDATE jobs SET created_at = :c WHERE id = :i"),
            {"c": created_at, "i": job.id},
        )
        await db.commit()
        return job.id


_STATE_SQL = text(
    "SELECT CAST(status AS text), work_state, is_open, closed_at, "
    "(SELECT count(*) FROM activities a WHERE a.entity_type = 'job' "
    "AND a.entity_id = j.id AND a.action = 'archived') "
    "FROM jobs j WHERE j.id = :i"
)


async def test_archives_jobs_created_before_cutoff_once() -> None:
    old_manual = await _seed_job(
        created_at=BEFORE_CUTOFF, source="manual", status="published"
    )
    old_draft = await _seed_job(
        created_at=BEFORE_CUTOFF, source="manual", status="draft"
    )
    old_managed_traffit = await _seed_job(
        created_at=BEFORE_CUTOFF, source="traffit", status="published"
    )
    new_manual = await _seed_job(
        created_at=AFTER_CUTOFF, source="manual", status="published"
    )

    # Cały przebieg w jednej transakcji wycofywanej na końcu: korekta łapie
    # KAŻDĄ rekrutację sprzed 25.09, więc zatwierdzona zamknęłaby też cudze
    # wiersze wspólnej bazy testowej (i ruszyła znacznik z migracji 0378).
    async with AsyncSessionLocal() as db:
        try:
            await db.execute(
                text("DELETE FROM app_settings WHERE key = :k"), {"k": MARKER_KEY}
            )
            await db.execute(text(ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL))

            async def state(job_id: int) -> tuple:
                return tuple((await db.execute(_STATE_SQL, {"i": job_id})).one())

            for job_id in (old_manual, old_draft, old_managed_traffit):
                assert await state(job_id) == ("closed", "finished", False, None, 1)
            assert await state(new_manual) == ("published", "searching", True, None, 0)

            # Otwarta z powrotem — drugi przebieg (znacznik już jest) jej nie
            # zamyka i nie dopisuje historii.
            await db.execute(
                text(
                    "UPDATE jobs SET status = 'published', is_open = true, "
                    "work_state = 'searching' WHERE id = :i"
                ),
                {"i": old_manual},
            )
            await db.execute(text(ARCHIVE_JOBS_BEFORE_NEXUS_START_SQL))
            assert await state(old_manual) == ("published", "searching", True, None, 1)
        finally:
            await db.rollback()
