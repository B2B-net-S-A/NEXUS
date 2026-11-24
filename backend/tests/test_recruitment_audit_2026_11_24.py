"""Poprawki z audytu rekrutacji 24.11.2026 (kod 58953b191).

* Zamknięta rekrutacja nie przyjmuje nowych współpracowników (409, jak `/claim`).
* Zamknięcie przez `PATCH status=closed` gasi P0 i prośbę o P0, jak `close_job`.
* „Dodaj championa z historii” nie omija globalnej czarnej listy, a para
  z kilkoma wierszami etapu daje 409, nie 500.
* Wyczyszczenie stawki kandydata / do klienta czyści ją z całej pary — odczyt
  bierze najnowszą niepustą, więc stara wracała.

Osoby w testach są fikcyjne.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.services.stage_client_rate import latest_client_rates
from tests.test_pipeline_v4_claim_and_rules import (
    _cleanup,
    _login,
    _seed_candidate,
    _seed_job,
    _seed_user,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def api_client():
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


async def _two_stage_rows(cand_id: int, job_id: int, **latest_fields) -> None:
    """Para z dwoma wierszami etapu: starszy i nowszy, oba ze stawkami."""
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        db.add_all(
            [
                CandidateStage(
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.screening,
                    moved_at=now - timedelta(days=2),
                    expected_rate_value=Decimal("150"),
                    expected_rate_unit="hourly",
                    expected_rate_currency="PLN",
                    client_rate_value=Decimal("190"),
                    client_rate_unit="hourly",
                    client_rate_currency="PLN",
                ),
                CandidateStage(
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.verified,
                    moved_at=now - timedelta(days=1),
                    **latest_fields,
                ),
            ]
        )
        await db.commit()


# ── 2. Współpracownik zamkniętej rekrutacji ────────────────────────────────


async def test_closed_job_refuses_new_collaborator(api_client):
    owner_id, owner_email, owner_pw = await _seed_user(UserRole.recruiter)
    other_id, _e, _p = await _seed_user(UserRole.recruiter)
    job_id, _ = await _seed_job(owner_id)
    owner_h = await _login(api_client, owner_email, owner_pw)
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            job.status = JobStatus.closed
            await db.commit()
        refused = await api_client.post(
            f"/api/jobs/{job_id}/collaborators",
            headers=owner_h,
            json={"user_id": other_id},
        )
        assert refused.status_code == 409, refused.text
    finally:
        await _cleanup([], job_id)


# ── 3. PATCH status=closed gasi P0 ─────────────────────────────────────────


async def test_patch_close_clears_p0_and_p0_request(api_client):
    admin_id, admin_email, admin_pw = await _seed_user(UserRole.admin)
    job_id, _ = await _seed_job(admin_id)
    admin_h = await _login(api_client, admin_email, admin_pw)
    now = datetime.now(timezone.utc)
    try:
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            job.p0_until = now + timedelta(hours=24)
            job.p0_reason = "Klient czeka"
            job.p0_set_at = now
            job.p0_set_by = admin_id
            job.p0_request_reason = "Pilne"
            job.p0_request_duration = "24h"
            job.p0_requested_at = now
            job.p0_requested_by = admin_id
            await db.commit()
        closed = await api_client.patch(
            f"/api/jobs/{job_id}", headers=admin_h, json={"status": "closed"}
        )
        assert closed.status_code == 200, closed.text
        async with AsyncSessionLocal() as db:
            job = await db.get(Job, job_id)
            assert job.status == JobStatus.closed
            assert job.p0_until is None
            assert job.p0_reason is None
            assert job.p0_set_at is None
            assert job.p0_set_by is None
            assert job.p0_request_reason is None
            assert job.p0_requested_at is None
    finally:
        await _cleanup([], job_id)


# ── 4–5. „Dodaj championa z historii” ─────────────────────────────────────


async def test_add_from_history_refuses_globally_blacklisted(api_client):
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, _ = await _seed_job(dl_id)
    source_id, _ = await _seed_job(dl_id)
    cand_id = await _seed_candidate()
    dl_h = await _login(api_client, dl_email, dl_pw)
    try:
        async with AsyncSessionLocal() as db:
            cand = await db.get(Candidate, cand_id)
            cand.status = CandidateStatus.blacklisted
            await db.commit()
        refused = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            headers=dl_h,
            json={"candidate_id": cand_id, "source_job_id": source_id},
        )
        assert refused.status_code == 409, refused.text
        async with AsyncSessionLocal() as db:
            rows = await db.scalar(
                select(CandidateStage.id).where(
                    CandidateStage.candidate_id == cand_id,
                    CandidateStage.job_id == job_id,
                )
            )
        assert rows is None
    finally:
        await _cleanup([cand_id], job_id)
        await _cleanup([], source_id)


async def test_add_from_history_with_many_stage_rows_is_409(api_client):
    dl_id, dl_email, dl_pw = await _seed_user(UserRole.delivery_lead)
    job_id, _ = await _seed_job(dl_id)
    cand_id = await _seed_candidate()
    dl_h = await _login(api_client, dl_email, dl_pw)
    try:
        await _two_stage_rows(cand_id, job_id)
        resp = await api_client.post(
            f"/api/jobs/{job_id}/candidates",
            headers=dl_h,
            json={"candidate_id": cand_id},
        )
        assert resp.status_code == 409, resp.text
    finally:
        await _cleanup([cand_id], job_id)


# ── 6. Wyczyszczenie stawki czyści całą parę ───────────────────────────────


async def test_clearing_expected_rate_clears_every_stage_row(api_client):
    admin_id, admin_email, admin_pw = await _seed_user(UserRole.admin)
    job_id, _ = await _seed_job(admin_id)
    cand_id = await _seed_candidate()
    admin_h = await _login(api_client, admin_email, admin_pw)
    try:
        await _two_stage_rows(
            cand_id,
            job_id,
            expected_rate_value=Decimal("160"),
            expected_rate_unit="hourly",
            expected_rate_currency="PLN",
        )
        cleared = await api_client.patch(
            f"/api/candidates/{cand_id}/recruitments/{job_id}/expected-rate",
            headers=admin_h,
            json={"rate_value": None},
        )
        assert cleared.status_code == 200, cleared.text
        assert cleared.json()["expected_rate"] is None
        async with AsyncSessionLocal() as db:
            left = (
                await db.scalars(
                    select(CandidateStage.expected_rate_value).where(
                        CandidateStage.candidate_id == cand_id,
                        CandidateStage.job_id == job_id,
                        CandidateStage.expected_rate_value.is_not(None),
                    )
                )
            ).all()
        assert left == []
    finally:
        await _cleanup([cand_id], job_id)


async def test_clearing_client_rate_clears_every_stage_row(api_client):
    admin_id, admin_email, admin_pw = await _seed_user(UserRole.admin)
    job_id, _ = await _seed_job(admin_id)
    cand_id = await _seed_candidate()
    admin_h = await _login(api_client, admin_email, admin_pw)
    try:
        await _two_stage_rows(
            cand_id,
            job_id,
            client_rate_value=Decimal("200"),
            client_rate_unit="hourly",
            client_rate_currency="PLN",
        )
        cleared = await api_client.patch(
            f"/api/candidates/{cand_id}/recruitments/{job_id}/client-rate",
            headers=admin_h,
            json={"rate_value": None},
        )
        assert cleared.status_code == 200, cleared.text
        async with AsyncSessionLocal() as db:
            rates = await latest_client_rates(db, [(cand_id, job_id)])
        assert rates == {}
    finally:
        await _cleanup([cand_id], job_id)
