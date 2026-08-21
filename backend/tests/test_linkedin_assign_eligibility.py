"""Bramka dopuszczalności na ścieżce „Dodaj z LinkedIn".

`POST /api/candidates/from-linkedin` zapisuje `CandidateStage` dla kandydata,
którego dedup znalazł w bazie — a sprawdzała TYLKO weto hiring managera. Cztery
twarde powody z `pipeline_eligibility` (globalna czarna lista, czarna lista
klienta, NDA, konkurent) nie były sprawdzane w ogóle, więc ta sama osoba, którą
kanban odrzuca z 409 „Konflikt: NDA z klientem", wchodziła do pipeline'u tego
klienta jednym kliknięciem z wtyczki.

Regresja byłaby CICHA: odpowiedź to 200, a wiersz po prostu pojawia się w bazie.
Dlatego test asertuje OBIE strony — brak `CandidateStage` ORAZ obecność powodu
w `assignment_skipped_reason` (wtyczka nie ma jak obsłużyć twardego 409, więc
kontrakt degradacji jest tu tym samym co przy wecie managera).
"""

from __future__ import annotations

import time
from typing import Optional

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_conflict import CandidateConflict, ConflictType
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.linkedin_snapshot import LinkedinSyncStatus
from app.models.recruitment_pipeline import CandidateStage


@pytest.fixture(autouse=True)
def patch_linkedin_sync(monkeypatch):
    """Bez sieci i bez klucza Proxycurl — jak w test_candidates_from_linkedin."""

    async def _fake_sync(db, candidate, *, client=None):  # noqa: ARG001
        class _Result:
            candidate_id = candidate.id
            status = LinkedinSyncStatus.ok
            change_kind = None
            snapshot_id = None
            error = None

        return _Result()

    from app.services import proxycurl as _proxycurl_pkg
    from app.services.proxycurl import sync as _proxycurl_sync

    monkeypatch.setattr(_proxycurl_pkg, "sync_candidate_linkedin", _fake_sync)
    monkeypatch.setattr(_proxycurl_sync, "sync_candidate_linkedin", _fake_sync)
    monkeypatch.setattr(
        "app.api.candidates.sync_candidate_linkedin", _fake_sync, raising=False
    )
    yield


@pytest_asyncio.fixture
async def job_with_client(app_auth_headers) -> tuple[int, int]:  # noqa: ARG001
    """(job_id, client_id) — opublikowana rekrutacja z własnym klientem."""
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"EligClient-{time.time_ns()}")
        db.add(cli)
        await db.flush()
        job = Job(
            title=f"Elig Engineer {time.time_ns()}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        return job.id, cli.id


async def _seed_existing_candidate(slug: str) -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name="Nda",
            lastname=f"Blocked-{time.time_ns()}",
            email=f"elig-{time.time_ns()}@example.com",
            linkedin=f"https://www.linkedin.com/in/{slug}",
        )
        db.add(cand)
        await db.commit()
        return cand.id


async def _stage_for(candidate_id: int, job_id: int) -> Optional[CandidateStage]:
    async with AsyncSessionLocal() as db:
        return await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )


@pytest.mark.asyncio
async def test_nda_conflict_blocks_the_linkedin_assignment(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    job_with_client: tuple[int, int],
) -> None:
    job_id, client_id = job_with_client
    slug = f"nda-blocked-{time.time_ns()}"
    candidate_id = await _seed_existing_candidate(slug)

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateConflict(
                candidate_id=candidate_id,
                client_id=client_id,
                type=ConflictType.nda,
                reason="NDA z klientem",
                active=True,
            )
        )
        await db.commit()

    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={
            "linkedin_url": f"https://www.linkedin.com/in/{slug}/",
            "job_id": job_id,
            "stage": "interview",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "existing"
    assert body["candidate_id"] == candidate_id
    # Przypisania NIE MA…
    assert body["assigned_to_job_id"] is None
    assert await _stage_for(candidate_id, job_id) is None, (
        "kandydat objęty NDA wszedł do pipeline'u klienta z pominięciem bramki"
    )
    # …a rekruter dostaje powód po polsku, nie ciszę.
    reason = body["assignment_skipped_reason"]
    assert reason, "brak powodu — pominięte przypisanie wygląda jak udane"
    assert "NDA" in reason or "nda" in reason.lower()


@pytest.mark.asyncio
async def test_clean_candidate_is_still_assigned(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    job_with_client: tuple[int, int],
) -> None:
    """Kontrola negatywna: bramka nie może blokować zwykłego przypadku."""
    job_id, _client_id = job_with_client
    slug = f"elig-clean-{time.time_ns()}"
    candidate_id = await _seed_existing_candidate(slug)

    resp = await app_client.post(
        "/api/candidates/from-linkedin",
        headers=app_auth_headers,
        json={
            "linkedin_url": f"https://www.linkedin.com/in/{slug}/",
            "job_id": job_id,
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["assignment_skipped_reason"] is None
    assert body["assigned_to_job_id"] == job_id
    assert await _stage_for(candidate_id, job_id) is not None
