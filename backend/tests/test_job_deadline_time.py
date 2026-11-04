"""Godzina terminu rekrutacji (0406, 30.09.2026).

Banki (Alior, PKO BP) podają termin z godziną. `jobs.deadline` zostaje datą
(alerty, filtry i sortowanie liczą po dniu), godzina żyje obok:
- lustro migracji w ``entrypoint.sh``, kolumna należy do NEXUSA (sync Traffita
  jej nie pisze);
- godzina bez daty = 422, wyczyszczona data zabiera godzinę.
"""

from __future__ import annotations

import importlib.util
import os
import uuid
from datetime import date, time
from pathlib import Path

import pytest
from fastapi import HTTPException

BACKEND = Path(__file__).resolve().parents[1]
MIGRATION = BACKEND / "alembic" / "versions" / "0406_job_deadline_time.py"
needs_db = pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"), reason="wymaga PostgreSQL"
)


def _migration():
    spec = importlib.util.spec_from_file_location("m0406", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_migration_is_mirrored_and_column_belongs_to_nexus() -> None:
    from app.services.job_column_ownership import NEXUS_OWNED

    module = _migration()
    assert module.down_revision == "0405_proposal_feedback_job_board"
    assert module.ADD_COLUMN in (BACKEND / "entrypoint.sh").read_text()
    assert "deadline_time" in NEXUS_OWNED


def test_time_without_any_date_is_refused() -> None:
    from app.api.jobs import _normalize_deadline_time

    with pytest.raises(HTTPException) as exc:
        _normalize_deadline_time({"deadline_time": time(12, 0)}, None)
    assert exc.value.status_code == 422


def test_time_alone_is_fine_when_the_date_is_already_saved() -> None:
    from app.api.jobs import _normalize_deadline_time

    updates = {"deadline_time": time(12, 0)}
    _normalize_deadline_time(updates, date(2030, 10, 1))
    assert updates == {"deadline_time": time(12, 0)}


def test_clearing_the_date_clears_the_time() -> None:
    from app.api.jobs import _normalize_deadline_time

    updates = {"deadline": None, "deadline_time": time(12, 0)}
    _normalize_deadline_time(updates, date(2030, 10, 1))
    assert updates == {"deadline": None, "deadline_time": None}


@needs_db
@pytest.mark.asyncio
async def test_patch_saves_date_with_time_and_returns_it(
    app_client, app_auth_headers
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"dltime-{uuid.uuid4().hex[:8]}")
        db.add(client)
        await db.flush()
        job = Job(title="Termin z godziną", client_id=client.id, status=JobStatus.draft)
        db.add(job)
        await db.commit()
        job_id = job.id

    saved = await app_client.patch(
        f"/api/jobs/{job_id}",
        json={"deadline": "2030-10-01", "deadline_time": "12:00"},
        headers=app_auth_headers,
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["deadline_time"] == "12:00:00"

    read = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert (read.json()["deadline"], read.json()["deadline_time"]) == (
        "2030-10-01",
        "12:00:00",
    )

    cleared = await app_client.patch(
        f"/api/jobs/{job_id}", json={"deadline": None}, headers=app_auth_headers
    )
    assert cleared.status_code == 200, cleared.text
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert (job.deadline, job.deadline_time) == (None, None)
