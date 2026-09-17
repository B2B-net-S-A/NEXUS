"""Pasek ⌘K i wyszukiwarka globalna: `%` i `_` w zapytaniu są dosłowne.

`GET /api/search/` i `GET /api/search/global` wkładały surowy tekst w
``%{q}%``: `%` zwracał wszystkich, a `_` dopasowywał dowolny znak.
"""

from __future__ import annotations

import uuid

import pytest

from app.api.search import _contains_pattern


def test_pattern_escapes_like_wildcards() -> None:
    assert _contains_pattern("50%_x") == "%50\\%\\_x%"
    assert _contains_pattern("plain") == "%plain%"


async def _seed_pair() -> tuple[str, int, int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus

    nonce = uuid.uuid4().hex[:10]
    async with AsyncSessionLocal() as db:
        literal = Candidate(
            name="Esc",
            lastname=f"Esc_{nonce}",
            email=f"esc-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        wildcard_victim = Candidate(
            name="Esc",
            lastname=f"EscX{nonce}",
            email=f"esc-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([literal, wildcard_victim])
        await db.commit()
        await db.refresh(literal)
        await db.refresh(wildcard_victim)
        return nonce, literal.id, wildcard_victim.id


@pytest.mark.asyncio
async def test_unified_search_treats_underscore_literally(app_client, app_auth_headers):
    nonce, literal_id, victim_id = await _seed_pair()
    resp = await app_client.get(
        "/api/search/",
        params={"q": f"Esc_{nonce}", "entity": "candidates"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {c["id"] for c in resp.json()["results"]["candidates"]}
    assert literal_id in ids
    assert victim_id not in ids, "`_` dopasował dowolny znak — brak escapowania"


@pytest.mark.asyncio
async def test_global_search_treats_underscore_literally(app_client, app_auth_headers):
    nonce, literal_id, victim_id = await _seed_pair()
    resp = await app_client.get(
        "/api/search/global",
        params={"q": f"Esc_{nonce}"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    ids = {c["id"] for c in resp.json()["candidates"]}
    assert literal_id in ids
    assert victim_id not in ids


@pytest.mark.asyncio
async def test_percent_alone_does_not_match_everyone(app_client, app_auth_headers):
    nonce, _literal_id, _victim_id = await _seed_pair()
    resp = await app_client.get(
        "/api/search/global",
        params={"q": f"%{nonce}%"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["candidates"] == [], "surowy `%` w zapytaniu to nie „wszyscy"
