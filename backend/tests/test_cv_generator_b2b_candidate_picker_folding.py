"""UAT B27: picker kandydata w Generatorze B2B bez wrażliwości na polskie znaki.

`GET /api/cv-generator/candidates?q=` porównywał `lower()` po obu stronach,
więc „Probny" nie znajdował „Próbny" (a wyszukiwarka kandydatów już od dawna
tak działa). Fold idzie tą samą mapą co `polish_ilike`; ranking
exact/prefix/substring liczy się na zfoldowanych wartościach.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration]


async def _seed(name: str, lastname: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=name,
            lastname=lastname,
            email=f"picker-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _cleanup(ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


async def _search(app_client: AsyncClient, headers: dict, q: str) -> list[int]:
    r = await app_client.get(
        "/api/cv-generator/candidates", params={"q": q, "limit": 50}, headers=headers
    )
    assert r.status_code == 200, r.text
    return [row["id"] for row in r.json()]


@pytest.mark.asyncio
async def test_query_without_diacritics_finds_name_with_them(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = uuid.uuid4().hex[:6]
    accented = await _seed("Jan", f"Próbny-{tag}")
    plain = await _seed("Jan", f"Probny-{tag}")
    try:
        for q in (f"Probny-{tag}", f"Próbny-{tag}", f"jan probny-{tag}"):
            ids = await _search(app_client, app_auth_headers, q)
            assert accented in ids and plain in ids, (q, ids)
    finally:
        await _cleanup([accented, plain])


@pytest.mark.asyncio
async def test_exact_folded_lastname_ranks_before_substring_hit(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = uuid.uuid4().hex[:6]
    # Substring: „…-<tag>owicz" trafia w LIKE, ale nie jest dokładnym nazwiskiem.
    longer = await _seed("Michał", f"Łódzki-{tag}owicz")
    exact = await _seed("Michał", f"Łódzki-{tag}")
    try:
        ids = await _search(app_client, app_auth_headers, f"lodzki-{tag}")
        assert exact in ids and longer in ids, ids
        assert ids.index(exact) < ids.index(longer), ids
    finally:
        await _cleanup([exact, longer])


@pytest.mark.asyncio
async def test_like_wildcards_in_query_are_literal(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = uuid.uuid4().hex[:6]
    cid = await _seed("Ewa", f"Znak-{tag}")
    try:
        # „%" szuka znaku procenta, nie zwraca całej bazy.
        ids = await _search(app_client, app_auth_headers, f"%-{tag}")
        assert cid not in ids
    finally:
        await _cleanup([cid])
