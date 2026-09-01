"""Hybrid FTS keyword search on GET /api/candidates (migration 0143).

Plain alphanumeric words (>=3 chars) route through a word-PREFIX tsvector match
(fast, no CV detoast); short / special-char fragments keep exact trigram
substring matching. These tests pin the resulting semantics:

  * word-prefix matches (``jav`` -> ``java``, ``java`` -> ``javascript``),
  * mid-word substrings are dropped for the FTS path (``ava`` !-> ``java``),
  * special-char fragments (``c++``, ``.net``) still substring-match,
  * NONE bucket and notes scope still work.

Requires Postgres (tsvector/trigram) — runs against the in-process app_client.
"""

from __future__ import annotations

import uuid
from typing import Optional

import pytest
from httpx import AsyncClient


async def _seed_candidate(
    *, raw_cv: str, tags: Optional[list[str]] = None, note: Optional[str] = None
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.note import Note

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Fts",
            lastname=f"Probe-{uuid.uuid4().hex[:6]}",
            email=f"fts-{uuid.uuid4().hex[:8]}@example.com",
            raw_cv_text=raw_cv,
            tags=tags or [],
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        if note:
            db.add(Note(candidate_id=c.id, content=note))
            await db.commit()
        return c.id


async def _cleanup(candidate_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.note import Note
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            await db.execute(delete(Note).where(Note.candidate_id == cid))
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


async def _search_ids(app_client: AsyncClient, headers: dict, params: dict) -> set[int]:
    params = {"page_size": 100, **params}
    r = await app_client.get("/api/candidates", params=params, headers=headers)
    assert r.status_code == 200, r.text
    return {item["id"] for item in r.json()["items"]}


@pytest.mark.asyncio
async def test_word_prefix_matches_full_and_partial(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A plain word matches the exact token AND a typed prefix of it."""
    cid = await _seed_candidate(raw_cv="experienced selenium automation tester")
    try:
        full = await _search_ids(app_client, app_auth_headers, {"q_all": "selenium"})
        prefix = await _search_ids(app_client, app_auth_headers, {"q_all": "seleni"})
        assert cid in full
        assert cid in prefix, "word-prefix (incremental typing) must still match"
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_prefix_spans_longer_word(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`java` is a word-prefix of `javascript`, so it matches both; `javascript`
    matches only the longer token."""
    js = await _seed_candidate(raw_cv="javascript frontend developer")
    java = await _seed_candidate(raw_cv="java backend engineer spring")
    try:
        by_java = await _search_ids(app_client, app_auth_headers, {"q_all": "java"})
        by_js = await _search_ids(app_client, app_auth_headers, {"q_all": "javascript"})
        assert {js, java} <= by_java, "java prefix matches java AND javascript"
        assert java not in by_js
        assert js in by_js
    finally:
        await _cleanup([js, java])


@pytest.mark.asyncio
async def test_midword_substring_not_matched_by_fts(
    app_client: AsyncClient, app_auth_headers: dict
):
    """The dropped case: a plain word does NOT match mid-word substrings.
    `ava` is inside `kava` but is not a word-prefix, so it must not match."""
    cid = await _seed_candidate(raw_cv="kava ceremony specialist")
    try:
        ids = await _search_ids(app_client, app_auth_headers, {"q_all": "ava"})
        assert cid not in ids
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_special_char_fragment_uses_substring_fallback(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Non-alphanumeric fragments keep exact substring semantics (trigram path)
    — `c++` and `.net` are not tokenizable words but must still match."""
    cpp = await _seed_candidate(raw_cv="senior c++ systems developer")
    dotnet = await _seed_candidate(raw_cv="backend with .net core and asp.net")
    try:
        by_cpp = await _search_ids(app_client, app_auth_headers, {"q_all": "c++"})
        by_net = await _search_ids(app_client, app_auth_headers, {"q_all": ".net"})
        assert cpp in by_cpp
        assert dotnet in by_net
    finally:
        await _cleanup([cpp, dotnet])


@pytest.mark.asyncio
async def test_none_bucket_excludes_fts_word(
    app_client: AsyncClient, app_auth_headers: dict
):
    """q_none with an FTS word excludes matching candidates, keeps the rest."""
    py = await _seed_candidate(raw_cv="python data scientist")
    rb = await _seed_candidate(raw_cv="ruby on rails developer")
    try:
        # Anchor on a shared bucket (q_any is repeated values, OR'd) so both are
        # candidates, then exclude python via the NONE bucket.
        ids = await _search_ids(
            app_client,
            app_auth_headers,
            {"q_any": ["developer", "scientist"], "q_none": "python"},
        )
        assert rb in ids
        assert py not in ids
    finally:
        await _cleanup([py, rb])


@pytest.mark.asyncio
async def test_fts_word_still_matches_in_notes(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Even on the FTS path, the notes branch stays substring — a word present
    only in a candidate note is still found."""
    cid = await _seed_candidate(
        raw_cv="generic unrelated cv body",
        note="great fit for kubernetes platform work",
    )
    try:
        ids = await _search_ids(app_client, app_auth_headers, {"q_all": "kubernetes"})
        assert cid in ids
    finally:
        await _cleanup([cid])


@pytest.mark.asyncio
async def test_multiword_phrase_uses_substring_fallback(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A phrase containing whitespace is not a single token → substring path,
    so an exact multi-word phrase still matches contiguously."""
    cid = await _seed_candidate(raw_cv="lead senior java architect")
    try:
        ids = await _search_ids(app_client, app_auth_headers, {"q_all": "senior java"})
        assert cid in ids
    finally:
        await _cleanup([cid])
