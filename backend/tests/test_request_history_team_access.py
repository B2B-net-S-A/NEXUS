"""Historia requestu dla zespołu rekrutacji (17.09.2026).

``GET /api/jobs/{id}/request-history`` was admin / Delivery Lead / Finance
only, so a recruiter on the team got a 403 rendered as an error on the Historia
tab. Now any operational role reads it — this client's history only and
without fee amounts. Since 23.09.2026 (decyzja Artura: „nie musisz być
przypisany do rekrutacji") that includes a recruiter outside the team, who
gets exactly the member view; the legacy viewer role ``user`` is refused.
Org readers keep the full view (amounts, ``cross_client``).

The retrieval engine (Voyage + SQL fallback) is replaced by a fixed list so the
tests assert the handler's scope and redaction, not the ranking.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.user import User, UserRole
from app.services import request_history as request_history_service
from app.services.request_history import RequestHistoryEntry

URL = "/api/jobs/{job_id}/request-history"


async def _seed_user(role: UserRole) -> tuple[dict[str, str], int]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"rh-team-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"T3st_{tag}!History"),
            name=f"History {role.value} {tag}",
            role=role,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        user_id = user.id
    return {
        "Authorization": f"Bearer {create_access_token(user_id, role.value)}"
    }, user_id


async def _seed_jobs(member_id: int) -> dict:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"RhTeamClient-{tag}")
        other = Client(name=f"RhTeamOther-{tag}")
        db.add_all([client, other])
        await db.flush()
        job = Job(
            title=f"RhTeamJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=member_id,
        )
        db.add(job)
        await db.commit()
        return {"job_id": job.id, "client_id": client.id, "other_client_id": other.id}


def _entry(job_id: int, client_id: int) -> RequestHistoryEntry:
    return RequestHistoryEntry(
        job_id=job_id,
        title=f"Sibling {job_id}",
        train_name=None,
        same_train=False,
        seniority=None,
        status="closed",
        is_in_progress=False,
        outcome="filled",
        close_reason=None,
        similarity=0.9,
        similarity_source="voyage",
        closed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_at=datetime(2025, 12, 1, tzinfo=timezone.utc),
        tth_days=20,
        client_id=client_id,
        client_name="Klient",
        champion_name=None,
        champion_candidate_id=None,
        champions_count=0,
        candidates_count=3,
        fee_rate=4200,
        fee_currency="PLN",
        rate_unit="monthly",
        tac_name=None,
        delivery_lead_name=None,
    )


@pytest.fixture
def engine(monkeypatch):
    """Fixed retrieval result: one same-client sibling, one of another client."""
    calls: list[dict] = []
    world: dict = {}

    async def fake_find_similar_requests(db, **kwargs):
        calls.append(kwargs)
        return [
            _entry(990_000_001, world["client_id"]),
            _entry(990_000_002, world["other_client_id"]),
        ]

    monkeypatch.setattr(
        request_history_service, "find_similar_requests", fake_find_similar_requests
    )
    return calls, world


@pytest.mark.asyncio
async def test_team_member_reads_this_clients_history_without_fees(
    app_client: AsyncClient, engine
):
    calls, world = engine
    headers, member_id = await _seed_user(UserRole.recruiter)
    world.update(await _seed_jobs(member_id))

    resp = await app_client.get(
        URL.format(job_id=world["job_id"]),
        headers=headers,
        params={"cross_client": "true"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [e["client_id"] for e in body["closed"]] == [world["client_id"]]
    (row,) = body["closed"]
    assert row["fee_rate"] is None
    assert row["fee_currency"] is None
    assert row["rate_unit"] is None
    # ``cross_client=true`` from a team member never widens the retrieval.
    assert calls[-1]["cross_client"] is False


@pytest.mark.asyncio
async def test_recruiter_outside_the_team_reads_the_member_view(
    app_client: AsyncClient, engine
):
    calls, world = engine
    _member_headers, member_id = await _seed_user(UserRole.recruiter)
    outsider_headers, _ = await _seed_user(UserRole.recruiter)
    world.update(await _seed_jobs(member_id))

    resp = await app_client.get(
        URL.format(job_id=world["job_id"]),
        headers=outsider_headers,
        params={"cross_client": "true"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert [e["client_id"] for e in body["closed"]] == [world["client_id"]]
    (row,) = body["closed"]
    assert row["fee_rate"] is None
    assert calls[-1]["cross_client"] is False


@pytest.mark.asyncio
async def test_legacy_viewer_gets_403(app_client: AsyncClient, engine):
    calls, world = engine
    _member_headers, member_id = await _seed_user(UserRole.recruiter)
    viewer_headers, _ = await _seed_user(UserRole.user)
    world.update(await _seed_jobs(member_id))

    resp = await app_client.get(
        URL.format(job_id=world["job_id"]), headers=viewer_headers
    )

    assert resp.status_code == 403, resp.text
    assert calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role", [UserRole.admin, UserRole.delivery_lead])
async def test_org_readers_keep_fees_and_cross_client(
    app_client: AsyncClient, engine, role: UserRole
):
    calls, world = engine
    headers, _ = await _seed_user(role)
    _member_headers, member_id = await _seed_user(UserRole.recruiter)
    world.update(await _seed_jobs(member_id))

    resp = await app_client.get(
        URL.format(job_id=world["job_id"]),
        headers=headers,
        params={"cross_client": "true"},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert {e["client_id"] for e in body["closed"]} == {
        world["client_id"],
        world["other_client_id"],
    }
    assert all(e["fee_rate"] == 4200 for e in body["closed"])
    assert all(e["fee_currency"] == "PLN" for e in body["closed"])
    assert calls[-1]["cross_client"] is True
