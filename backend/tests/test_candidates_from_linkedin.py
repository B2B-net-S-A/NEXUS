"""Integration tests for ``POST /api/candidates/from-linkedin``.

The endpoint powers the NEXUS Chrome extension — one-click "Dodaj z LinkedIn".

Covers:
- Happy path: new LinkedIn URL → candidate created, background enrichment queued
- Dedup: same URL twice → ``action="existing"`` with same candidate_id
- URL normalization: regional variants + trailing slashes + query params → same dedup
- Validation: invalid URLs → 400
- Job assignment: ``job_id`` → ``CandidateStage`` row inserted at default ``new``
- Preview persistence: name/lastname/location from preview survive on candidate row
- Fallback names: empty preview → name="LinkedIn", lastname=slug
- Background task isolation: Proxycurl failure does NOT break the response
- Stale resync: existing candidate with old sync → background task scheduled

Tests use the in-process ``app_client`` fixture (no live server). Proxycurl is
monkeypatched everywhere so no network and no API key needed.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.job import Job, JobStatus
from app.models.linkedin_snapshot import LinkedinSyncStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def patch_linkedin_sync(monkeypatch):
    """Replace ``sync_candidate_linkedin`` with a recording stub so tests
    run without Proxycurl and we can verify the background task is queued.

    The endpoint imports it as ``app.api.candidates.sync_candidate_linkedin``
    (via local import inside the handler) — we patch at the module level so
    any import path resolves to our stub.
    """
    calls: list[int] = []

    async def _fake_sync(db, candidate, *, client=None):  # noqa: ARG001
        calls.append(candidate.id)

        class _Result:
            candidate_id = candidate.id
            status = LinkedinSyncStatus.ok
            change_kind = None
            snapshot_id = None
            error = None

        return _Result()

    # Patch on the proxycurl module so any import (incl. local-in-function) hits the stub.
    from app.services import proxycurl as _proxycurl_pkg
    from app.services.proxycurl import sync as _proxycurl_sync

    monkeypatch.setattr(_proxycurl_pkg, "sync_candidate_linkedin", _fake_sync)
    monkeypatch.setattr(_proxycurl_sync, "sync_candidate_linkedin", _fake_sync)

    # Also expose the call log on the test via a function attribute.
    monkeypatch.setattr(
        "app.api.candidates.sync_candidate_linkedin", _fake_sync, raising=False
    )
    yield calls


@pytest_asyncio.fixture
async def seeded_job(app_auth_headers) -> int:  # noqa: ARG001 — ensures admin user exists
    """Insert a published Job with no client and return its id."""
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Senior Python Engineer (pytest {time.time_ns()})",
            status=JobStatus.published,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _get_candidate_by_linkedin(slug: str) -> Optional[Candidate]:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Candidate).where(Candidate.linkedin.ilike(f"%{slug}%"))
        )
        return result.scalars().first()


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_creates_new_candidate_for_unseen_url(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    patch_linkedin_sync: list[int],
) -> None:
    slug = f"jan-kowalski-pytest-{time.time_ns()}"
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={
            "linkedin_url": f"https://www.linkedin.com/in/{slug}/",
            "preview": {
                "name": "Jan",
                "lastname": "Kowalski",
                "headline": "Senior Python Developer",
                "location": "Warsaw",
                "current_company": "Acme",
            },
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["action"] == "created"
    assert body["name"] == "Jan Kowalski"
    assert slug in body["linkedin_url"]
    assert body["profile_url_path"] == f"/candidates/{body['candidate_id']}"
    assert body["linkedin_sync_status"] in ("disabled", "ok")

    # Background enrichment was queued
    assert body["candidate_id"] in patch_linkedin_sync

    # Candidate persisted with normalized linkedin
    candidate = await _get_candidate_by_linkedin(slug)
    assert candidate is not None
    assert candidate.linkedin and "linkedin.com/in/" in candidate.linkedin
    assert candidate.name == "Jan"
    assert candidate.lastname == "Kowalski"
    assert candidate.location == "Warsaw"


@pytest.mark.asyncio
async def test_returns_existing_when_linkedin_url_matches(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    slug = f"anna-dedup-pytest-{time.time_ns()}"
    payload = {
        "linkedin_url": f"https://www.linkedin.com/in/{slug}",
        "preview": {"name": "Anna", "lastname": "Nowak"},
    }
    r1 = await app_client.post(
        "/api/candidates/from-linkedin", headers=app_auth_headers, json=payload
    )
    assert r1.status_code == 201, r1.text
    first_id = r1.json()["candidate_id"]

    r2 = await app_client.post(
        "/api/candidates/from-linkedin", headers=app_auth_headers, json=payload
    )
    assert r2.status_code == 200, r2.text
    body = r2.json()
    assert body["action"] == "existing"
    assert body["candidate_id"] == first_id


@pytest.mark.asyncio
async def test_normalizes_url_variants(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    """Regional variants, trailing slashes, query params all collapse to one
    candidate via slug dedup."""
    slug = f"variant-pytest-{time.time_ns()}"
    r1 = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={"linkedin_url": f"linkedin.com/in/{slug}"},
    )
    assert r1.status_code == 201, r1.text
    first_id = r1.json()["candidate_id"]

    for variant in (
        f"https://www.linkedin.com/in/{slug}/",
        f"https://pl.linkedin.com/in/{slug}",
        f"https://www.linkedin.com/in/{slug}/?utm_source=foo&utm=bar",
    ):
        r = await app_client.post(
            "/api/candidates/from-linkedin",
            headers=app_auth_headers,
            json={"linkedin_url": variant},
        )
        assert r.status_code == 200, f"{variant} → {r.text}"
        assert r.json()["candidate_id"] == first_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "",
        "not-a-url",
        "https://google.com",
        "https://www.linkedin.com/company/microsoft",  # company page, not profile
        "https://www.linkedin.com/jobs/view/12345",  # job page
    ],
)
async def test_invalid_linkedin_url_returns_400(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    url: str,
) -> None:
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={"linkedin_url": url} if url else {"linkedin_url": ""},
    )
    # 400 or 422 are both acceptable rejections
    assert resp.status_code in (400, 422), resp.text


@pytest.mark.asyncio
async def test_assigns_to_job_when_job_id_provided(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    seeded_job: int,
) -> None:
    slug = f"assign-pytest-{time.time_ns()}"
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={
            "linkedin_url": f"https://www.linkedin.com/in/{slug}",
            "preview": {"name": "Piotr", "lastname": "Tester"},
            "job_id": seeded_job,
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["assigned_to_job_id"] == seeded_job

    # Verify CandidateStage row inserted at default `new` stage
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CandidateStage).where(
                CandidateStage.candidate_id == body["candidate_id"],
                CandidateStage.job_id == seeded_job,
            )
        )
        stage_row = result.scalars().first()
        assert stage_row is not None
        assert stage_row.stage == PipelineStage.new


@pytest.mark.asyncio
async def test_assign_to_nonexistent_job_returns_404(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    slug = f"missing-job-pytest-{time.time_ns()}"
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={
            "linkedin_url": f"https://www.linkedin.com/in/{slug}",
            "job_id": 999_999_999,
        },
    )
    assert resp.status_code == 404, resp.text

    # Candidate must NOT have been created (transactional rollback)
    candidate = await _get_candidate_by_linkedin(slug)
    assert candidate is None


@pytest.mark.asyncio
async def test_preview_used_for_name_lastname(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    slug = f"preview-names-pytest-{time.time_ns()}"
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={
            "linkedin_url": f"https://www.linkedin.com/in/{slug}",
            "preview": {"name": "Maria", "lastname": "Wiśniewska"},
        },
    )
    assert resp.status_code == 201, resp.text
    candidate = await _get_candidate_by_linkedin(slug)
    assert candidate is not None
    assert candidate.name == "Maria"
    assert candidate.lastname == "Wiśniewska"


@pytest.mark.asyncio
async def test_fallback_name_when_preview_empty(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    """No preview → fallback name='LinkedIn', lastname=slug."""
    slug = f"no-preview-pytest-{time.time_ns()}"
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={"linkedin_url": f"https://www.linkedin.com/in/{slug}"},
    )
    assert resp.status_code == 201, resp.text
    candidate = await _get_candidate_by_linkedin(slug)
    assert candidate is not None
    assert candidate.name == "LinkedIn"
    assert slug in candidate.lastname


@pytest.mark.asyncio
async def test_proxycurl_failure_does_not_block_creation(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    monkeypatch,
) -> None:
    """If the background enrichment raises, the response must still be 201
    (BackgroundTasks runs AFTER the response is returned)."""

    async def _boom(db, candidate, *, client=None):  # noqa: ARG001
        raise RuntimeError("proxycurl down")

    from app.services import proxycurl as _proxycurl_pkg
    from app.services.proxycurl import sync as _proxycurl_sync

    monkeypatch.setattr(_proxycurl_pkg, "sync_candidate_linkedin", _boom)
    monkeypatch.setattr(_proxycurl_sync, "sync_candidate_linkedin", _boom)
    monkeypatch.setattr(
        "app.api.candidates.sync_candidate_linkedin", _boom, raising=False
    )

    slug = f"proxycurl-boom-pytest-{time.time_ns()}"
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={
            "linkedin_url": f"https://www.linkedin.com/in/{slug}",
            "preview": {"name": "Robust", "lastname": "Stub"},
        },
    )
    assert resp.status_code == 201, resp.text


@pytest.mark.asyncio
async def test_existing_stale_triggers_resync(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    patch_linkedin_sync: list[int],
) -> None:
    """Existing candidate with stale ``linkedin_synced_at`` (>7d) → resync queued
    and ``resync_scheduled=True`` in response."""
    slug = f"stale-resync-pytest-{time.time_ns()}"

    # Seed candidate with an old sync timestamp
    async with AsyncSessionLocal() as db:
        candidate = Candidate(
            name="Stale",
            lastname="Sync",
            linkedin=f"https://linkedin.com/in/{slug}",
            linkedin_synced_at=datetime.now(timezone.utc) - timedelta(days=14),
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)
        stale_id = candidate.id

    patch_linkedin_sync.clear()
    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={"linkedin_url": f"https://www.linkedin.com/in/{slug}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "existing"
    assert body["candidate_id"] == stale_id
    assert body["resync_scheduled"] is True
    assert stale_id in patch_linkedin_sync
