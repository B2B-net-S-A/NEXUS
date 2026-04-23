"""Tests for Traffit-style advanced search on GET /api/candidates.

Three buckets: q_all (AND), q_any (OR), q_none (NOT). Each phrase matches
case-insensitive ILIKE across searchable fields (see
app.services.advanced_candidate_search._SEARCHABLE_COLUMNS).
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from httpx import AsyncClient


async def _seed_candidate(*, raw_cv: str, tags: Optional[list[str]] = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Adv",
            lastname=f"Search-{uuid.uuid4().hex[:6]}",
            email=f"adv-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text=raw_cv,
            tags=tags or [],
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _cleanup(candidate_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


async def _seed_four() -> dict[str, int]:
    a = await _seed_candidate(raw_cv="python react developer senior")
    b = await _seed_candidate(raw_cv="python django backend engineer")
    c = await _seed_candidate(raw_cv="java spring senior architect")
    d = await _seed_candidate(raw_cv="react native mobile junior intern")
    return {"A": a, "B": b, "C": c, "D": d}


@pytest.mark.asyncio
async def test_q_all_and(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=python&q_all=react&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["C"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_q_any_or(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_any=django&q_any=spring&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["B"] in result_ids
        assert ids["C"] in result_ids
        assert ids["A"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_q_none_not(app_client: AsyncClient, app_auth_headers: dict):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_none=junior&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] in result_ids
        assert ids["C"] in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_combination_all_and_none(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=python&q_none=django&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["C"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_multi_word_phrase(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=react+native&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["D"] in result_ids
        assert ids["A"] not in result_ids  # "python react developer" — no "react native"
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_simple_q_conjoined_with_q_all(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_four()
    try:
        # simple q=python narrows to {A,B}, q_all=react further narrows to {A}
        r = await app_client.get(
            "/api/candidates?q=python&q_all=react&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] not in result_ids
        assert ids["D"] not in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_no_advanced_params_is_backward_compat(
    app_client: AsyncClient, app_auth_headers: dict
):
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?page_size=100", headers=app_auth_headers
        )
        assert r.status_code == 200, r.text
        # Seeded candidates are included (we don't assert total — other fixtures
        # may exist in the DB).
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] in result_ids
        assert ids["C"] in result_ids
        assert ids["D"] in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_like_metacharacters_are_escaped(
    app_client: AsyncClient, app_auth_headers: dict
):
    # A literal "50%" phrase must not be treated as LIKE wildcard.
    a = await _seed_candidate(raw_cv="python react developer 50% remote")
    b = await _seed_candidate(raw_cv="python django backend engineer")
    try:
        r = await app_client.get(
            "/api/candidates?q_all=50%25&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert a in result_ids
        assert b not in result_ids  # doesn't contain literal "50%"
    finally:
        await _cleanup([a, b])


@pytest.mark.asyncio
async def test_dedupe_case_insensitive(
    app_client: AsyncClient, app_auth_headers: dict
):
    # Supplying the same phrase with different casing should not over-constrain.
    ids = await _seed_four()
    try:
        r = await app_client.get(
            "/api/candidates?q_all=python&q_all=PYTHON&q_all=Python&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert ids["A"] in result_ids
        assert ids["B"] in result_ids
    finally:
        await _cleanup(list(ids.values()))


@pytest.mark.asyncio
async def test_tags_field_is_searched(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _seed_candidate(raw_cv="generic cv body", tags=["kubernetes", "aws"])
    b = await _seed_candidate(raw_cv="generic cv body", tags=["gcp"])
    try:
        r = await app_client.get(
            "/api/candidates?q_all=kubernetes&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        result_ids = {item["id"] for item in r.json()["items"]}
        assert a in result_ids
        assert b not in result_ids
    finally:
        await _cleanup([a, b])
