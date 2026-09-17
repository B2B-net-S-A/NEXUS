"""Obecne zatrudnienie u klienta rekrutacji wyprowadzone z żywej umowy.

Bez ręcznego wiersza ``candidate_conflicts`` typu ``current_employment``:
żywa umowa kandydata u klienta rekrutacji daje ostrzeżenie
``client_current_employment`` (widoczny, przypisywalny), a bulk-add dodaje go
z ostrzeżeniem ``current_employment`` w ``warnings``.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient
from sqlalchemy import select


async def _seed(*, contract_status: str = "active") -> dict:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.contract import Contract, ContractStatus
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"DerivedEmp-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"DerivedEmp-Job-{tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        cand = Candidate(
            name="Derived",
            lastname=f"Emp-{tag}",
            email=f"derived-emp-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            Contract(
                candidate_id=cand.id,
                client_id=client.id,
                start_date=date.today() - timedelta(days=30),
                status=ContractStatus(contract_status),
            )
        )
        await db.commit()
        return {"job_id": job.id, "candidate_id": cand.id, "client_id": client.id}


async def _decision(world: dict):
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.services.pipeline_eligibility import evaluate_candidates_for_job

    async with AsyncSessionLocal() as db:
        job = await db.scalar(select(Job).where(Job.id == world["job_id"]))
        decisions = await evaluate_candidates_for_job(
            db,
            job=job,
            candidate_ids=[world["candidate_id"]],
            now=datetime.now(timezone.utc),
        )
    return decisions[world["candidate_id"]]


async def test_live_contract_without_conflict_row_warns_current_employment():
    from app.services.candidate_job_eligibility import (
        EligibilityReason,
        Severity,
        Visibility,
    )

    world = await _seed()
    decision = await _decision(world)

    assert decision.reason_code is EligibilityReason.client_current_employment
    assert decision.eligible is True
    assert decision.assignment_allowed is True
    assert decision.visibility is Visibility.warn
    assert decision.severity is Severity.warning


async def test_ended_contract_is_not_current_employment():
    from app.services.candidate_job_eligibility import EligibilityReason

    world = await _seed(contract_status="ended")
    decision = await _decision(world)

    assert decision.reason_code is EligibilityReason.eligible


async def test_bulk_add_adds_with_a_current_employment_warning(
    app_client: AsyncClient, app_auth_headers: dict
):
    world = await _seed()

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/proposals/bulk",
        headers=app_auth_headers,
        json={"candidate_ids": [world["candidate_id"]]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["added"] == [world["candidate_id"]]
    assert body["skipped"] == []
    assert body["warnings"] == [
        {
            "candidate_id": world["candidate_id"],
            "reason": "current_employment",
            "reason_label": "Kandydat obecnie pracuje u tego klienta",
        }
    ]


async def test_bulk_add_adds_client_nda_with_a_warning(
    app_client: AsyncClient, app_auth_headers: dict
):
    """17.09.2026: NDA is a warning in bulk-add — added, reason in `warnings`."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_conflict import CandidateConflict, ConflictType

    world = await _seed(contract_status="ended")
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        other = Candidate(
            name="Nda", lastname=f"Bulk-{tag}", email=f"nda-bulk-{tag}@example.com"
        )
        db.add(other)
        await db.flush()
        db.add(
            CandidateConflict(
                candidate_id=other.id,
                client_id=world["client_id"],
                type=ConflictType.nda,
                active=True,
            )
        )
        await db.commit()
        other_id = other.id

    resp = await app_client.post(
        f"/api/jobs/{world['job_id']}/proposals/bulk",
        headers=app_auth_headers,
        json={"candidate_ids": [other_id]},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["added"] == [other_id]
    assert body["skipped"] == []
    assert [w["reason"] for w in body["warnings"]] == ["client_nda"]
