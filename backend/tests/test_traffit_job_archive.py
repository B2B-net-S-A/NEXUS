"""Rekrutacje z Traffita są w NEXUSIE archiwum (decyzja Artura 24.09.2026).

Kontrakt:
* każda rekrutacja z Traffita poza „Prowadzona w NEXUSIE” jest zamknięta
  i „Zakończona”, a `closed_at` zostaje z Traffita (hit ratio go czyta);
* rekrutacje założone w NEXUSIE są nietknięte;
* ponowne otwarcie archiwalnej rekrutacji w NEXUSIE przełącza ją na
  „Prowadzona w NEXUSIE” — inaczej nocny sync zamknąłby ją z powrotem;
* SQL archiwum ma jedno źródło, lustrzane w migracji 0377 i entrypoint.sh.

Baza testowa wspólna i nieczyszczona — asercje tylko na własnych wierszach.
"""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import AsyncSessionLocal
from app.services.traffit_job_archive import (
    ARCHIVE_TRAFFIT_JOBS_SQL,
    archive_traffit_jobs,
)

BACKEND = Path(__file__).resolve().parent.parent


def test_entrypoint_mirrors_the_archive_sql() -> None:
    entrypoint = (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
    assert ARCHIVE_TRAFFIT_JOBS_SQL in entrypoint


def test_migration_runs_the_same_archive_sql() -> None:
    migration = (
        BACKEND / "alembic" / "versions" / "0377_traffit_jobs_archive.py"
    ).read_text(encoding="utf-8")
    assert "from app.services.traffit_job_archive import ARCHIVE_TRAFFIT_JOBS_SQL" in (
        migration
    )
    assert "op.execute(ARCHIVE_TRAFFIT_JOBS_SQL)" in migration


async def _seed_job(
    *, external_source: str, managed: bool = False, status: str = "published"
) -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"Archive-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Archive-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus(status),
            client_id=client.id,
            external_source=external_source,
            external_id=uuid.uuid4().hex if external_source == "traffit" else None,
            managed_in_nexus=managed,
            is_open=True,
            work_state="searching",
        )
        db.add(job)
        await db.commit()
        return job.id


async def _state(job_id: int) -> tuple[str, str, bool, object]:
    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(
                text(
                    "SELECT CAST(status AS text), work_state, is_open, closed_at "
                    "FROM jobs WHERE id = :i"
                ),
                {"i": job_id},
            )
        ).one()
        return row[0], row[1], row[2], row[3]


@pytest.mark.asyncio
async def test_archive_closes_traffit_jobs_and_keeps_nexus_ones() -> None:
    traffit_job = await _seed_job(external_source="traffit")
    traffit_draft = await _seed_job(external_source="traffit", status="draft")
    managed_job = await _seed_job(external_source="traffit", managed=True)
    nexus_job = await _seed_job(external_source="manual")

    async with AsyncSessionLocal() as db:
        await archive_traffit_jobs(db)
        await db.commit()

    for job_id in (traffit_job, traffit_draft):
        status, work_state, is_open, closed_at = await _state(job_id)
        assert status == "closed"
        assert work_state == "finished"
        assert is_open is False
        # Bez stempla „dziś” — inaczej Liga Mistrzów DL liczyłaby archiwum
        # jako rekrutacje zamknięte w bieżącym kwartale.
        assert closed_at is None

    assert (await _state(managed_job))[:3] == ("published", "searching", True)
    assert (await _state(nexus_job))[:3] == ("published", "searching", True)

    # Drugi przebieg nic nie zmienia na tych wierszach.
    async with AsyncSessionLocal() as db:
        await archive_traffit_jobs(db)
        await db.commit()
    assert (await _state(traffit_job))[:2] == ("closed", "finished")


async def _admin_headers(app_client: AsyncClient) -> dict[str, str]:
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    unique = uuid.uuid4().hex[:8]
    email = f"archive-admin-{unique}@example.com"
    password = f"T3st_{unique}!Adm"
    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Archive admin",
                role=UserRole.admin,
                roles=["admin"],
                is_active=True,
            )
        )
        await db.commit()
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.mark.asyncio
async def test_reopening_an_archived_traffit_job_hands_it_to_nexus(
    app_client: AsyncClient,
) -> None:
    job_id = await _seed_job(external_source="traffit")
    async with AsyncSessionLocal() as db:
        await archive_traffit_jobs(db)
        await db.commit()
    headers = await _admin_headers(app_client)

    resp = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "published"}, headers=headers
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        managed = (
            await db.execute(
                text("SELECT managed_in_nexus FROM jobs WHERE id = :i"), {"i": job_id}
            )
        ).scalar_one()
        history = (
            await db.execute(
                text(
                    "SELECT count(*) FROM activities WHERE entity_type = 'job' "
                    "AND entity_id = :i AND action = 'managed_in_nexus_changed'"
                ),
                {"i": job_id},
            )
        ).scalar_one()
        # Nocny sync nie zamyka już tej rekrutacji.
        await archive_traffit_jobs(db)
        await db.commit()
    assert managed is True
    assert history == 1
    status, work_state, _, _ = await _state(job_id)
    assert status == "published"
    assert work_state != "finished"
