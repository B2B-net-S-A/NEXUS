"""Tests for `GET /api/candidates?employment=at_client|available`.

Regression guard for the bug where the filter relied solely on the `contracts`
/ `candidate_conflicts` tables, which the Traffit import never backfilled — so
"Zatrudnieni u naszego klienta" returned ~1 row instead of the ~700 placed
consultants. The real signal is a recruitment whose LATEST pipeline stage is
`hired` (documented as "Zatrudniony / kontrakt aktywny").

Filter semantics (mirrored by `_at_client_predicate` and `_derive_employment`):

* `at_client`  — active Contract OR active current_employment conflict OR a job
  whose latest stage == `hired`.
* `available`  — the exact complement (`not_(_at_client_predicate())`).

`candidate_stages` is append-only history, so a candidate moved `hired`→`rejected`
is NO LONGER at the client (on_bench), and must fall on the `available` side.

Uses the in-process `app_client` / `app_auth_headers` fixtures from conftest.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


async def _seed_candidate(*, name_suffix: str = "") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Emp",
            lastname=f"Test-{uuid.uuid4().hex[:6]}{name_suffix}",
            email=f"emp-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(
    *, client_name: str | None = None, client_display_name: str | None = None
) -> tuple[int, int, str]:
    """Create a Client + Job. Returns (job_id, client_id, client_name)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    name = client_name or f"EmpClient-{uuid.uuid4().hex[:6]}"
    async with AsyncSessionLocal() as db:
        cli = Client(name=name, display_name=client_display_name)
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Emp-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id, cli.id, (client_display_name or "").strip() or name


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    moved_at: datetime | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=moved_at or datetime.now(timezone.utc),
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


async def _seed_contract(
    candidate_id: int, client_id: int, *, status: str = "active"
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        co = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            start_date=date(2024, 1, 1),
            end_date=date(2025, 12, 31),
            status=ContractStatus(status),
        )
        db.add(co)
        await db.commit()
        await db.refresh(co)
        return co.id


async def _cleanup(
    *,
    candidate_ids: list[int] | None = None,
    job_ids: list[int] | None = None,
    client_ids: list[int] | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.contract import Contract
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids or []:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == cid)
            )
            await db.execute(delete(Contract).where(Contract.candidate_id == cid))
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        for jid in job_ids or []:
            await db.execute(delete(CandidateStage).where(CandidateStage.job_id == jid))
            await db.execute(delete(Job).where(Job.id == jid))
        for cli in client_ids or []:
            await db.execute(delete(Client).where(Client.id == cli))
        await db.commit()


def _find(items: list[dict], cand_id: int) -> dict | None:
    return next((it for it in items if it["id"] == cand_id), None)


@pytest.mark.asyncio
async def test_at_client_includes_currently_hired(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A candidate whose latest stage is `hired` appears in `employment=at_client`
    and carries `employment.state=employed_at_client`, `source=pipeline`, and the
    client name — even with NO Contract row (the Traffit reality)."""
    display_name = f"Employment Client S.A. {uuid.uuid4().hex[:6]}"
    job_id, client_id, client_name = await _seed_job(
        client_name=f"EmpShort-{uuid.uuid4().hex[:6]}",
        client_display_name=f"  {display_name}  ",
    )
    hired = await _seed_candidate(name_suffix="-H")
    await _seed_stage(hired, job_id, "hired")
    try:
        r = await app_client.get(
            "/api/candidates?employment=at_client&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        match = _find(items, hired)
        assert match is not None, "currently-hired candidate must match at_client"
        assert match["employment"]["state"] == "employed_at_client"
        assert match["employment"]["source"] == "pipeline"
        assert match["employment"]["client_name"] == client_name
        assert match["employment"]["client_id"] == client_id
    finally:
        await _cleanup(candidate_ids=[hired], job_ids=[job_id], client_ids=[client_id])


@pytest.mark.asyncio
async def test_at_client_excludes_moved_past_hired(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`hired` then later `rejected` (placement ended) → NOT at_client; the
    candidate is `on_bench` and falls on the `available` side."""
    job_id, client_id, _ = await _seed_job()
    former = await _seed_candidate(name_suffix="-F")
    base = datetime.now(timezone.utc) - timedelta(days=10)
    await _seed_stage(former, job_id, "hired", moved_at=base)
    await _seed_stage(former, job_id, "rejected", moved_at=base + timedelta(days=1))
    try:
        at_client = await app_client.get(
            "/api/candidates?employment=at_client&page_size=100",
            headers=app_auth_headers,
        )
        avail = await app_client.get(
            "/api/candidates?employment=available&page_size=100",
            headers=app_auth_headers,
        )
        assert at_client.status_code == 200, at_client.text
        assert avail.status_code == 200, avail.text
        at_client_ids = [it["id"] for it in at_client.json()["items"]]
        avail_match = _find(avail.json()["items"], former)
        assert former not in at_client_ids, "moved-past-hired must NOT be at_client"
        assert avail_match is not None, "moved-past-hired belongs in available"
        assert avail_match["employment"]["state"] == "on_bench"
    finally:
        await _cleanup(candidate_ids=[former], job_ids=[job_id], client_ids=[client_id])


@pytest.mark.asyncio
async def test_at_client_excludes_never_hired(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A candidate sitting at `new` (never hired) is external → not at_client."""
    job_id, client_id, _ = await _seed_job()
    fresh = await _seed_candidate(name_suffix="-N")
    await _seed_stage(fresh, job_id, "new")
    try:
        r = await app_client.get(
            "/api/candidates?employment=at_client&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [it["id"] for it in r.json()["items"]]
        assert fresh not in ids
    finally:
        await _cleanup(candidate_ids=[fresh], job_ids=[job_id], client_ids=[client_id])


@pytest.mark.asyncio
async def test_available_excludes_currently_hired(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`available` is the exact complement — a currently-hired candidate must NOT
    appear there."""
    job_id, client_id, _ = await _seed_job()
    hired = await _seed_candidate(name_suffix="-AH")
    await _seed_stage(hired, job_id, "hired")
    try:
        r = await app_client.get(
            "/api/candidates?employment=available&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [it["id"] for it in r.json()["items"]]
        assert hired not in ids
    finally:
        await _cleanup(candidate_ids=[hired], job_ids=[job_id], client_ids=[client_id])


@pytest.mark.asyncio
@pytest.mark.parametrize("contract_status", ["active", "ending"])
async def test_at_client_live_contract_still_matches(
    app_client: AsyncClient, app_auth_headers: dict, contract_status: str
):
    """Both live lifecycle statuses match with ``source=contract``."""
    display_name = f"Contract Client S.A. {uuid.uuid4().hex[:6]}"
    job_id, client_id, canonical_name = await _seed_job(
        client_name=f"ContractShort-{uuid.uuid4().hex[:6]}",
        client_display_name=f"  {display_name}  ",
    )
    with_contract = await _seed_candidate(name_suffix="-C")
    await _seed_contract(with_contract, client_id, status=contract_status)
    try:
        r = await app_client.get(
            "/api/candidates?employment=at_client&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        match = _find(r.json()["items"], with_contract)
        assert match is not None
        assert match["employment"]["state"] == "employed_at_client"
        assert match["employment"]["source"] == "contract"
        assert match["employment"]["client_name"] == canonical_name
    finally:
        await _cleanup(
            candidate_ids=[with_contract], job_ids=[job_id], client_ids=[client_id]
        )
