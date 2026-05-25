"""Tests for LinkedIn-Recruiter-style candidate filters:

- current_company / past_company (JSONB experience)
- current_title
- worked_at_client_id (historical contract OR current_employment conflict)
- companies/suggest autocomplete endpoint

Uses in-process app fixtures. Same shape as test_candidates_filters.py.
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from httpx import AsyncClient


async def _seed_candidate_with_experience(
    experience: list[dict] | None,
    *,
    location: str | None = "Warszawa",
    linkedin_current_company: str | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Pos",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"pos-{uuid.uuid4().hex[:8]}@example.com",
            location=location,
            experience=experience,
            linkedin_current_company=linkedin_current_company,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_client(name: str | None = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=name or f"Client-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_contract(
    candidate_id: int, client_id: int, *, status: str = "ended"
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.contract import Contract, ContractStatus

    async with AsyncSessionLocal() as db:
        co = Contract(
            candidate_id=candidate_id,
            client_id=client_id,
            start_date=date(2024, 1, 1),
            end_date=date(2024, 12, 31),
            status=ContractStatus(status),
        )
        db.add(co)
        await db.commit()
        await db.refresh(co)
        return co.id


async def _seed_conflict(
    candidate_id: int,
    client_id: int,
    *,
    type_: str = "current_employment",
    active: bool = True,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate_conflict import CandidateConflict, ConflictType

    async with AsyncSessionLocal() as db:
        cf = CandidateConflict(
            candidate_id=candidate_id,
            client_id=client_id,
            type=ConflictType(type_),
            active=active,
        )
        db.add(cf)
        await db.commit()
        await db.refresh(cf)
        return cf.id


async def _cleanup(
    *,
    candidate_ids: list[int] | None = None,
    client_ids: list[int] | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.candidate_conflict import CandidateConflict
    from app.models.client import Client
    from app.models.contract import Contract
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids or []:
            await db.execute(
                delete(Contract).where(Contract.candidate_id == cid)
            )
            await db.execute(
                delete(CandidateConflict).where(CandidateConflict.candidate_id == cid)
            )
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        for cli in client_ids or []:
            await db.execute(delete(Client).where(Client.id == cli))
        await db.commit()


# ── current_company ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_current_company_match(
    app_client: AsyncClient, app_auth_headers: dict
):
    target = await _seed_candidate_with_experience(
        [{"company": "Acme Corp", "role": "Senior Python Dev"}]
    )
    other = await _seed_candidate_with_experience(
        [{"company": "Globex Ltd", "role": "Dev"}]
    )
    try:
        r = await app_client.get(
            "/api/candidates?current_company=acme&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
        assert other not in ids
    finally:
        await _cleanup(candidate_ids=[target, other])


@pytest.mark.asyncio
async def test_filter_current_company_matches_linkedin_only(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Filter must hit candidates whose CURRENT employer comes from the
    Proxycurl-synced `linkedin_current_company` column even when the JSONB
    `experience` is empty — the UI card shows that value, so the filter must
    reach it."""
    target = await _seed_candidate_with_experience(
        None, linkedin_current_company="Acme Corp"
    )
    other = await _seed_candidate_with_experience(
        None, linkedin_current_company="Globex Ltd"
    )
    try:
        r = await app_client.get(
            "/api/candidates?current_company=acme&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
        assert other not in ids
    finally:
        await _cleanup(candidate_ids=[target, other])


@pytest.mark.asyncio
async def test_filter_current_company_excludes_past(
    app_client: AsyncClient, app_auth_headers: dict
):
    past_only = await _seed_candidate_with_experience(
        [
            {"company": "Globex Ltd", "role": "Senior Dev"},
            {"company": "Acme Corp", "role": "Junior Dev"},
        ]
    )
    try:
        r = await app_client.get(
            "/api/candidates?current_company=acme&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert past_only not in ids
    finally:
        await _cleanup(candidate_ids=[past_only])


# ── past_company ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_past_company_match(
    app_client: AsyncClient, app_auth_headers: dict
):
    target = await _seed_candidate_with_experience(
        [
            {"company": "Globex Ltd", "role": "Senior Dev"},
            {"company": "Acme Corp", "role": "Junior Dev"},
        ]
    )
    unrelated = await _seed_candidate_with_experience(
        [{"company": "Initech", "role": "Dev"}]
    )
    try:
        r = await app_client.get(
            "/api/candidates?past_company=acme&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
        assert unrelated not in ids
    finally:
        await _cleanup(candidate_ids=[target, unrelated])


@pytest.mark.asyncio
async def test_filter_past_company_excludes_current(
    app_client: AsyncClient, app_auth_headers: dict
):
    current_only = await _seed_candidate_with_experience(
        [{"company": "Acme Corp", "role": "Senior"}]
    )
    try:
        r = await app_client.get(
            "/api/candidates?past_company=acme&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert current_only not in ids
    finally:
        await _cleanup(candidate_ids=[current_only])


# ── current_title ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_current_title(
    app_client: AsyncClient, app_auth_headers: dict
):
    senior = await _seed_candidate_with_experience(
        [{"company": "X", "role": "Senior Software Engineer"}]
    )
    junior = await _seed_candidate_with_experience(
        [{"company": "Y", "role": "Junior Developer"}]
    )
    try:
        r = await app_client.get(
            "/api/candidates?current_title=senior&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert senior in ids
        assert junior not in ids
    finally:
        await _cleanup(candidate_ids=[senior, junior])


# ── worked_at_client_id ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_filter_worked_at_client_via_contract(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _seed_client("Santander-test")
    target = await _seed_candidate_with_experience(None)
    other = await _seed_candidate_with_experience(None)
    await _seed_contract(target, client_id, status="ended")
    try:
        r = await app_client.get(
            f"/api/candidates?worked_at_client_id={client_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
        assert other not in ids
    finally:
        await _cleanup(candidate_ids=[target, other], client_ids=[client_id])


@pytest.mark.asyncio
async def test_filter_worked_at_client_via_conflict(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_id = await _seed_client("ING-test")
    target = await _seed_candidate_with_experience(None)
    other = await _seed_candidate_with_experience(None)
    await _seed_conflict(target, client_id, active=True)
    try:
        r = await app_client.get(
            f"/api/candidates?worked_at_client_id={client_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
        assert other not in ids
    finally:
        await _cleanup(candidate_ids=[target, other], client_ids=[client_id])


@pytest.mark.asyncio
async def test_filter_worked_at_client_inactive_conflict_still_matches(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Historical semantics — even inactive conflicts count as 'ever worked there'."""
    client_id = await _seed_client("Allegro-test")
    target = await _seed_candidate_with_experience(None)
    await _seed_conflict(target, client_id, active=False)
    try:
        r = await app_client.get(
            f"/api/candidates?worked_at_client_id={client_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
    finally:
        await _cleanup(candidate_ids=[target], client_ids=[client_id])


@pytest.mark.asyncio
async def test_filter_worked_at_client_or_combined(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_a = await _seed_client("A-test")
    client_b = await _seed_client("B-test")
    at_a = await _seed_candidate_with_experience(None)
    at_b = await _seed_candidate_with_experience(None)
    none = await _seed_candidate_with_experience(None)
    await _seed_contract(at_a, client_a)
    await _seed_contract(at_b, client_b)
    try:
        r = await app_client.get(
            f"/api/candidates?worked_at_client_id={client_a}"
            f"&worked_at_client_id={client_b}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert at_a in ids
        assert at_b in ids
        assert none not in ids
    finally:
        await _cleanup(
            candidate_ids=[at_a, at_b, none], client_ids=[client_a, client_b]
        )


# ── Combined filters (AND between different params) ────────────────────────


@pytest.mark.asyncio
async def test_combined_current_company_and_title(
    app_client: AsyncClient, app_auth_headers: dict
):
    match = await _seed_candidate_with_experience(
        [{"company": "Acme", "role": "Senior Engineer"}]
    )
    partial_co = await _seed_candidate_with_experience(
        [{"company": "Acme", "role": "Junior Intern"}]
    )
    partial_title = await _seed_candidate_with_experience(
        [{"company": "Globex", "role": "Senior Dev"}]
    )
    try:
        r = await app_client.get(
            "/api/candidates?current_company=acme&current_title=senior&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert match in ids
        assert partial_co not in ids
        assert partial_title not in ids
    finally:
        await _cleanup(candidate_ids=[match, partial_co, partial_title])


# ── companies/suggest endpoint ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_companies_suggest_basic(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _seed_candidate_with_experience(
        [{"company": "Google Poland", "role": "SWE"}]
    )
    b = await _seed_candidate_with_experience(
        [
            {"company": "Google Poland", "role": "SWE"},
            {"company": "Allegro", "role": "Dev"},
        ]
    )
    c = await _seed_candidate_with_experience(
        [{"company": "Allegro", "role": "PM"}]
    )
    try:
        r = await app_client.get(
            "/api/candidates/companies/suggest?q=goog&limit=10",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        payload = r.json()
        names = [row["name"] for row in payload]
        assert "google poland" in names
        # both a + b have Google → count = 2
        google_row = next(row for row in payload if row["name"] == "google poland")
        assert google_row["count"] >= 2
    finally:
        await _cleanup(candidate_ids=[a, b, c])


@pytest.mark.asyncio
async def test_companies_suggest_empty_query_returns_top_n(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _seed_candidate_with_experience(
        [{"company": "ZZZ Popular", "role": "X"}]
    )
    b = await _seed_candidate_with_experience(
        [{"company": "ZZZ Popular", "role": "Y"}]
    )
    try:
        r = await app_client.get(
            "/api/candidates/companies/suggest?limit=50",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        payload = r.json()
        names = [row["name"] for row in payload]
        assert "zzz popular" in names
    finally:
        await _cleanup(candidate_ids=[a, b])


@pytest.mark.asyncio
async def test_companies_suggest_excludes_empty_experience(
    app_client: AsyncClient, app_auth_headers: dict
):
    empty = await _seed_candidate_with_experience(None)
    try:
        r = await app_client.get(
            "/api/candidates/companies/suggest?q=nonexistent_xyzzy_12345&limit=10",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        assert r.json() == []
    finally:
        await _cleanup(candidate_ids=[empty])
