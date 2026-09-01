"""Tests for GET /api/reports/clients — hit ratio per client + trend + at-risk.

Scenarios covered:
- Happy path (filled/lost jobs → hit_ratio + fill_rate)
- Multi-seat jobs (headcount > 1 → fill_rate counts seats)
- Period filter (closed_at ∈ [now - period, now])
- Exclude reasons (`paused` removed from denominator)
- RBAC (recruiter 403, TAC/admin 200)
- Trend endpoint (N months returned)
- `min_closed` server-side filter
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.cache import cache_invalidate
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.client import Client, ClientStatus
from app.models.job import Job, JobCloseReason, JobStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole


# ── Helpers ────────────────────────────────────────────────────────────────────


async def _seed_user(role: UserRole, label: str = "rep") -> tuple[int, str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"rep-clients-{label}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!ClientsRep"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"Rep {label} {role.value}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id, email, password


async def _seed_client(name_prefix: str = "Acme") -> int:
    async with AsyncSessionLocal() as db:
        c = Client(
            name=f"{name_prefix}-{uuid.uuid4().hex[:6]}",
            status=ClientStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_candidate() -> int:
    async with AsyncSessionLocal() as db:
        cand = Candidate(
            name=f"Jan-{uuid.uuid4().hex[:4]}",
            lastname=f"Test-{uuid.uuid4().hex[:4]}",
            email=f"cand-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        return cand.id


async def _seed_closed_job(
    *,
    client_id: int,
    closed_at: datetime,
    headcount: int = 1,
    close_reason: JobCloseReason | None = None,
) -> int:
    async with AsyncSessionLocal() as db:
        job = Job(
            title=f"Role-{uuid.uuid4().hex[:6]}",
            status=JobStatus.closed,
            headcount=headcount,
            client_id=client_id,
            closed_at=closed_at,
            close_reason=close_reason,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_hired_stage(candidate_id: int, job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage.hired,
        )
        db.add(stage)
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def rep_client() -> AsyncClient:
    from app.core.rate_limit import limiter as _limiter
    from app.main import app

    _limiter.enabled = False
    # Each test starts with a clean client-report cache so cached responses
    # from earlier tests don't bleed assertions across fixtures.
    await cache_invalidate("reports:clients")
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://testserver",
    ) as c:
        yield c


# ── Tests ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_clients_hit_ratio_happy_path(rep_client: AsyncClient):
    """5 closed jobs, 3 filled (≥1 hired stage each) → hit_ratio = 60%."""
    client_id = await _seed_client("HappyCo")
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=3)

    filled_jobs = []
    for _ in range(3):
        jid = await _seed_closed_job(client_id=client_id, closed_at=recent, headcount=1)
        cand = await _seed_candidate()
        await _seed_hired_stage(cand, jid)
        filled_jobs.append(jid)
    for _ in range(2):
        await _seed_closed_job(client_id=client_id, closed_at=recent, headcount=1)

    _, email, password = await _seed_user(UserRole.admin, "happy")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get("/api/reports/clients?period=month", headers=headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    row = next((c for c in data["clients"] if c["client_id"] == client_id), None)
    assert row is not None, "client row not in response"
    assert row["closed_jobs"] == 5
    assert row["filled_jobs"] == 3
    assert row["lost_jobs"] == 2
    assert row["hit_ratio"] == 60.0
    assert row["target_achieved"] is True  # 60% >= 30%


@pytest.mark.asyncio
async def test_clients_fill_rate_handles_multi_seat(rep_client: AsyncClient):
    """Job headcount=3 with 2 hired candidates → fill_rate = 66.7%."""
    client_id = await _seed_client("MultiSeat")
    now = datetime.now(timezone.utc)
    recent = now - timedelta(days=2)

    jid = await _seed_closed_job(client_id=client_id, closed_at=recent, headcount=3)
    for _ in range(2):
        cand = await _seed_candidate()
        await _seed_hired_stage(cand, jid)

    _, email, password = await _seed_user(UserRole.admin, "multiseat")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get("/api/reports/clients?period=month", headers=headers)
    assert resp.status_code == 200, resp.text
    row = next((c for c in resp.json()["clients"] if c["client_id"] == client_id), None)
    assert row is not None
    assert row["closed_jobs"] == 1
    assert row["filled_jobs"] == 1  # 1 job with ≥1 hire
    assert row["placements"] == 2
    assert row["total_vacancies"] == 3
    assert row["fill_rate"] == 66.7
    assert row["hit_ratio"] == 100.0  # job had hires


@pytest.mark.asyncio
async def test_clients_zero_hires(rep_client: AsyncClient):
    """4 closed jobs, 0 hires → hit_ratio 0, all counted as lost."""
    client_id = await _seed_client("ZeroCo")
    recent = datetime.now(timezone.utc) - timedelta(days=10)

    for _ in range(4):
        await _seed_closed_job(client_id=client_id, closed_at=recent, headcount=1)

    _, email, password = await _seed_user(UserRole.admin, "zero")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get("/api/reports/clients?period=month", headers=headers)
    assert resp.status_code == 200, resp.text
    row = next((c for c in resp.json()["clients"] if c["client_id"] == client_id), None)
    assert row is not None
    assert row["closed_jobs"] == 4
    assert row["filled_jobs"] == 0
    assert row["lost_jobs"] == 4
    assert row["hit_ratio"] == 0.0
    assert row["target_achieved"] is False


@pytest.mark.asyncio
async def test_clients_period_filter_excludes_old_jobs(rep_client: AsyncClient):
    """Job closed 400 days ago is excluded from `period=year` (365d)."""
    client_id = await _seed_client("TimeCo")
    now = datetime.now(timezone.utc)

    # 1 recent closed job
    await _seed_closed_job(
        client_id=client_id, closed_at=now - timedelta(days=3), headcount=1
    )
    # 1 ancient closed job
    await _seed_closed_job(
        client_id=client_id, closed_at=now - timedelta(days=400), headcount=1
    )

    _, email, password = await _seed_user(UserRole.admin, "time")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get("/api/reports/clients?period=year", headers=headers)
    assert resp.status_code == 200, resp.text
    row = next((c for c in resp.json()["clients"] if c["client_id"] == client_id), None)
    assert row is not None
    assert row["closed_jobs"] == 1  # only the recent one


@pytest.mark.asyncio
async def test_clients_exclude_reasons_removes_from_denominator(
    rep_client: AsyncClient,
):
    """exclude_reasons=paused removes paused jobs from the denominator."""
    client_id = await _seed_client("ExcludeCo")
    recent = datetime.now(timezone.utc) - timedelta(days=1)

    # 2 paused jobs (should be excluded)
    for _ in range(2):
        await _seed_closed_job(
            client_id=client_id,
            closed_at=recent,
            headcount=1,
            close_reason=JobCloseReason.paused,
        )
    # 1 lost job (budget) — kept
    await _seed_closed_job(
        client_id=client_id,
        closed_at=recent,
        headcount=1,
        close_reason=JobCloseReason.budget,
    )
    # 1 filled job — kept
    jid_filled = await _seed_closed_job(
        client_id=client_id,
        closed_at=recent,
        headcount=1,
        close_reason=JobCloseReason.filled_by_us,
    )
    cand = await _seed_candidate()
    await _seed_hired_stage(cand, jid_filled)

    _, email, password = await _seed_user(UserRole.admin, "exclude")
    headers = await _login(rep_client, email, password)

    # Without exclusion → 4 closed jobs, 1 filled = 25%
    resp_all = await rep_client.get(
        "/api/reports/clients?period=month", headers=headers
    )
    row_all = next(
        (c for c in resp_all.json()["clients"] if c["client_id"] == client_id),
        None,
    )
    assert row_all is not None
    assert row_all["closed_jobs"] == 4
    assert row_all["hit_ratio"] == 25.0

    # With exclusion → 2 jobs (budget + filled), 1 filled = 50%
    resp_excl = await rep_client.get(
        "/api/reports/clients?period=month&exclude_reasons=paused",
        headers=headers,
    )
    row_excl = next(
        (c for c in resp_excl.json()["clients"] if c["client_id"] == client_id),
        None,
    )
    assert row_excl is not None
    assert row_excl["closed_jobs"] == 2
    assert row_excl["hit_ratio"] == 50.0


@pytest.mark.asyncio
async def test_clients_rbac_rejects_recruiter(rep_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.recruiter, "rbac-rec")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get("/api/reports/clients", headers=headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_clients_rbac_allows_head_of_recruitment(rep_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.head_of_recruitment, "rbac-hor")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get("/api/reports/clients?period=year", headers=headers)
    assert resp.status_code == 200
    assert "clients" in resp.json() and "overall" in resp.json()


@pytest.mark.asyncio
async def test_clients_min_closed_filter(rep_client: AsyncClient):
    """Backend filters out clients with < min_closed closed jobs."""
    big = await _seed_client("BigCo")
    small = await _seed_client("SmallCo")
    recent = datetime.now(timezone.utc) - timedelta(days=1)

    # Big: 5 closed
    for _ in range(5):
        await _seed_closed_job(client_id=big, closed_at=recent, headcount=1)
    # Small: 1 closed
    await _seed_closed_job(client_id=small, closed_at=recent, headcount=1)

    _, email, password = await _seed_user(UserRole.admin, "min-closed")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get(
        "/api/reports/clients?period=month&min_closed=3", headers=headers
    )
    assert resp.status_code == 200, resp.text
    ids = {c["client_id"] for c in resp.json()["clients"]}
    assert big in ids
    assert small not in ids


@pytest.mark.asyncio
async def test_client_trend_returns_n_months(rep_client: AsyncClient):
    client_id = await _seed_client("TrendCo")
    recent = datetime.now(timezone.utc) - timedelta(days=5)
    await _seed_closed_job(client_id=client_id, closed_at=recent, headcount=1)

    _, email, password = await _seed_user(UserRole.admin, "trend")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get(
        f"/api/reports/clients/{client_id}/trend?months=6", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["client_id"] == client_id
    assert len(body["trend"]) == 6
    assert all({"month", "closed_jobs", "hit_ratio"}.issubset(m) for m in body["trend"])


@pytest.mark.asyncio
async def test_client_trend_404_for_unknown(rep_client: AsyncClient):
    _, email, password = await _seed_user(UserRole.admin, "trend-404")
    headers = await _login(rep_client, email, password)

    resp = await rep_client.get(
        "/api/reports/clients/99999999/trend?months=3", headers=headers
    )
    assert resp.status_code == 404
