"""Multiposting (0359) — szkielet Pracuj.pl + JustJoinIT za flagami OFF.

Pokrywa:

- flagi OFF: konfiguracja „disabled”, publikacja 409 i brak wiersza,
  pętla workera kończy się przed ``while``, health ``unconfigured``;
- flaga ON bez adresu/klucza = ``misconfigured`` (publikacja nadal 409);
- portal gotowy: niezatwierdzony opis publiczny = 409; zatwierdzony + link =
  wiersz ``publishing``; drugi raz = 409 (i częściowy UNIQUE w bazie);
- worker: adapter bez dokumentacji → ``failed`` z polskim ``last_error``
  i ``attempts`` = 1; claim ``SKIP LOCKED``;
- wycofanie wiersza w kolejce → ``removed``;
- migracja usuwa symulowane wiersze ``SIM-…`` (lustro w entrypoincie).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job_posting import JobPosting, Portal, PostingStatus
from app.services import job_portals
from app.services.job_portals.base import PortalConfig
from tests.test_career_links_api import (
    _approve,
    _create_job_link,
    _login,
    _seed_job,
    _seed_user,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api() -> AsyncClient:
    from app.core.rate_limit import limiter
    from app.main import app

    limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client


BACKEND = Path(__file__).resolve().parents[1]


@pytest.fixture
def pracuj_ready(monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_PRACUJ_ENABLED", True)
    monkeypatch.setattr(settings, "PORTAL_PRACUJ_API_URL", "https://api.example.test")
    monkeypatch.setattr(settings, "PORTAL_PRACUJ_API_KEY", "k" * 16)


async def _owner(api):
    uid, email, password = await _seed_user("portals")
    headers = await _login(api, email, password)
    job_id = await _seed_job(uid)
    return uid, headers, job_id


def _publish_url(job_id: int, portal: str = "pracuj_pl") -> str:
    return f"/api/jobs/{job_id}/portals/{portal}/publish"


async def _postings(job_id: int) -> list[JobPosting]:
    async with AsyncSessionLocal() as db:
        return list(
            (
                await db.scalars(select(JobPosting).where(JobPosting.job_id == job_id))
            ).all()
        )


# ── Flagi OFF (stan produkcji) ───────────────────────────────────────────────


async def test_flags_off_config_publish_and_health(api):
    _uid, headers, job_id = await _owner(api)

    config = await api.get("/api/job-portals/config", headers=headers)
    assert config.status_code == 200, config.text
    body = config.json()
    assert body["any_ready"] is False
    assert {p["portal"]: p["state"] for p in body["portals"]} == {
        "pracuj_pl": "disabled",
        "justjoinit": "disabled",
    }

    resp = await api.post(_publish_url(job_id), headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "portal_not_configured"
    assert await _postings(job_id) == []

    assert job_portals.health_state(0) == "unconfigured"


async def test_worker_loop_returns_before_while_when_off():
    from app.tasks.job_portal_worker import job_portal_worker_loop

    # Zwraca od razu — gdyby weszła w `while True`, test by nie skończył się.
    assert await job_portal_worker_loop() is None


async def test_enabled_without_credentials_is_misconfigured(api, monkeypatch):
    monkeypatch.setattr(settings, "PORTAL_JJIT_ENABLED", True)
    assert PortalConfig.from_settings(Portal.justjoinit).state == "misconfigured"
    assert job_portals.health_state(0) == "misconfigured"
    _uid, headers, job_id = await _owner(api)
    resp = await api.post(_publish_url(job_id, "justjoinit"), headers=headers)
    assert resp.status_code == 409


async def test_unsupported_portal_is_422(api, pracuj_ready):
    _uid, headers, job_id = await _owner(api)
    resp = await api.post(_publish_url(job_id, "linkedin"), headers=headers)
    assert resp.status_code == 422


# ── Portal gotowy ────────────────────────────────────────────────────────────


async def test_unapproved_public_profile_is_409(api, pracuj_ready):
    _uid, headers, job_id = await _owner(api)
    await _create_job_link(api, headers, job_id)
    resp = await api.post(_publish_url(job_id), headers=headers)
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "public_profile_not_approved"
    assert await _postings(job_id) == []


async def test_publish_queues_then_worker_fails_with_polish_reason(api, pracuj_ready):
    from app.services.job_portals.service import process_batch

    _uid, headers, job_id = await _owner(api)
    await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200

    resp = await api.post(_publish_url(job_id), headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "publishing"

    again = await api.post(_publish_url(job_id), headers=headers)
    assert again.status_code == 409
    assert again.json()["detail"]["code"] == "posting_already_live"

    listing = await api.get(f"/api/jobs/{job_id}/portals", headers=headers)
    assert [p["status"] for p in listing.json()] == ["publishing"]

    async with AsyncSessionLocal() as db:
        await process_batch(db, limit=1000)
        await db.commit()
    (posting,) = await _postings(job_id)
    assert posting.status == PostingStatus.failed
    assert posting.attempts == 1
    assert "czeka na dokumentację API" in (posting.last_error or "")
    assert posting.payload_hash and posting.public_profile_hash


async def test_unpublish_of_queued_posting_removes_it(api, pracuj_ready):
    _uid, headers, job_id = await _owner(api)
    await _create_job_link(api, headers, job_id)
    assert (await _approve(api, headers, job_id)).status_code == 200
    assert (await api.post(_publish_url(job_id), headers=headers)).status_code == 200

    resp = await api.post(
        f"/api/jobs/{job_id}/portals/pracuj_pl/unpublish", headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "removed"
    missing = await api.post(
        f"/api/jobs/{job_id}/portals/pracuj_pl/unpublish", headers=headers
    )
    assert missing.status_code == 404


async def test_partial_unique_allows_one_live_posting_per_portal():
    uid, _, _ = await _seed_user("portals-uq")
    job_id = await _seed_job(uid)
    async with AsyncSessionLocal() as db:
        db.add(
            JobPosting(
                job_id=job_id, portal=Portal.pracuj_pl, status=PostingStatus.failed
            )
        )
        db.add(
            JobPosting(
                job_id=job_id, portal=Portal.pracuj_pl, status=PostingStatus.publishing
            )
        )
        await db.commit()
    with pytest.raises(IntegrityError):
        async with AsyncSessionLocal() as db:
            db.add(
                JobPosting(
                    job_id=job_id,
                    portal=Portal.pracuj_pl,
                    status=PostingStatus.published,
                )
            )
            await db.commit()


async def test_claim_skips_rows_locked_by_another_worker():
    from app.services.job_portals.service import claim_batch

    uid, _, _ = await _seed_user("portals-lock")
    job_id = await _seed_job(uid)
    async with AsyncSessionLocal() as db:
        posting = JobPosting(
            job_id=job_id, portal=Portal.justjoinit, status=PostingStatus.publishing
        )
        db.add(posting)
        await db.commit()
        posting_id = posting.id

    async with AsyncSessionLocal() as first, AsyncSessionLocal() as second:
        claimed = [p.id for p in await claim_batch(first, 10_000)]
        assert posting_id in claimed
        other = [p.id for p in await claim_batch(second, 10_000)]
        assert posting_id not in other
        await first.rollback()
        await second.rollback()


# ── Migracja i lustro ────────────────────────────────────────────────────────


async def test_sim_rows_are_removed_by_the_mirror_statement():
    uid, _, _ = await _seed_user("portals-sim")
    job_id = await _seed_job(uid)
    async with AsyncSessionLocal() as db:
        db.add(
            JobPosting(
                job_id=job_id,
                portal=Portal.linkedin,
                status=PostingStatus.published,
                external_id=f"SIM-{uuid.uuid4().hex[:6]}",
            )
        )
        await db.commit()
        await db.execute(
            text("DELETE FROM job_postings WHERE external_id LIKE 'SIM-%'")
        )
        await db.commit()
    assert await _postings(job_id) == []


def test_migration_and_entrypoint_mirror():
    migration = re.sub(
        r"\s+", " ", (BACKEND / "alembic/versions/0359_job_portals.py").read_text()
    )
    entrypoint = re.sub(r"\s+", " ", (BACKEND / "entrypoint.sh").read_text())
    for needle in (
        "ALTER TYPE postingstatus ADD VALUE IF NOT EXISTS 'publishing'",
        "ALTER TYPE postingstatus ADD VALUE IF NOT EXISTS 'failed'",
        "DELETE FROM job_postings WHERE external_id LIKE 'SIM-%'",
        "uq_job_postings_live_per_portal",
        "WHERE status IN ('publishing', 'published')",
        "ADD COLUMN IF NOT EXISTS payload_hash",
        "ADD COLUMN IF NOT EXISTS public_profile_hash",
        "ADD COLUMN IF NOT EXISTS last_synced_at",
    ):
        assert needle in migration, needle
        assert needle in entrypoint, needle
    assert 'down_revision = "0358_order_group_cancel"' in migration
