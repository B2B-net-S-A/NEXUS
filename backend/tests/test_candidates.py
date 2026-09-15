"""Candidates API smoke tests — in-process client, own seeded data.

Ported from the live-server suite. The list/unauthorised cases are covered by
`test_api_integration.py` (`test_candidates_list_ok`,
`test_candidates_list_requires_auth`) and `test_auth_missing_credentials.py`,
so only the detail, not-found and search cases live here.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal


async def _seed_candidate() -> tuple[int, str, str]:
    from app.models.candidate import Candidate

    tag = uuid.uuid4().hex[:10]
    lastname = f"Smokecand{tag}"
    email = f"cand-smoke-{tag}@example.com"
    async with AsyncSessionLocal() as db:
        cand = Candidate(name="Kandydat", lastname=lastname, email=email)
        db.add(cand)
        await db.commit()
        return cand.id, lastname, email


async def test_get_candidate(app_client: AsyncClient, app_auth_headers: dict):
    cid, lastname, email = await _seed_candidate()
    resp = await app_client.get(f"/api/candidates/{cid}", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["id"] == cid
    assert data["name"] == "Kandydat"
    assert data["lastname"] == lastname
    assert data["email"] == email


async def test_candidate_not_found(app_client: AsyncClient, app_auth_headers: dict):
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        missing = (await db.scalar(select(func.max(Candidate.id))) or 0) + 100_000
    resp = await app_client.get(f"/api/candidates/{missing}", headers=app_auth_headers)
    assert resp.status_code == 404


async def test_search_candidates_by_unique_lastname(
    app_client: AsyncClient, app_auth_headers: dict
):
    cid, lastname, _ = await _seed_candidate()
    resp = await app_client.get(
        "/api/candidates", params={"q": lastname}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["total"] >= 1
    assert cid in {item["id"] for item in data["items"]}
