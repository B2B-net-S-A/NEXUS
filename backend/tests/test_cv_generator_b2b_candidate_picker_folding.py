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


async def _seed_phone(phone: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Telefon",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"picker-{uuid.uuid4().hex[:8]}@example.com",
            phone=phone,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


@pytest.mark.asyncio
async def test_phone_digits_find_the_candidate_regardless_of_format(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    """Generator v3: od 6 cyfr picker szuka po telefonie (ostatnie 9 cyfr,
    jak `dedup_service`) — „+48 5xx-xxx-xxx" znajduje zapis bez separatorów."""
    digits = f"5{uuid.uuid4().int % 10**8:08d}"
    candidate = await _seed_phone(f"+48 {digits[:3]}-{digits[3:6]}-{digits[6:]}")
    try:
        assert candidate in await _search(app_client, app_auth_headers, digits)
        assert candidate in await _search(
            app_client, app_auth_headers, f"+48 {digits[:3]} {digits[3:6]} {digits[6:]}"
        )
        assert candidate in await _search(app_client, app_auth_headers, digits[-6:])
        # Mniej niż 6 cyfr nie szuka po telefonie (przypadkowe fragmenty).
        assert candidate not in await _search(app_client, app_auth_headers, digits[-5:])
        response = await app_client.get(
            "/api/cv-generator/candidates",
            params={"q": digits, "limit": 50},
            headers=app_auth_headers,
        )
        [row] = [r for r in response.json() if r["id"] == candidate]
        assert row["phone"].endswith(digits[6:])
    finally:
        await _cleanup([candidate])
