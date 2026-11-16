"""Paleta ⌘K: dokładne nazwisko przed prefiksem w `GET /api/candidates?sort=relevance`.

Rekruter widzi w palecie kandydatów z `/api/candidates` (nie z
`/api/search/global`, który #3431 już układał). Sortowanie „relevance” liczyło
samo podobieństwo trigramowe do „imię nazwisko e-mail”, więc krótszy stóg
wygrywał: na stagingu 16.11.2026 `q=Kotow` dawało Ewę Kotowską, Kamila Kota
i Pawła Kota przed Andrzejem Kotowem. Kolejność ma być jak w `global_search`:
dokładne nazwisko / imię z nazwiskiem / e-mail, potem prefiks, potem reszta.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

pytestmark = [pytest.mark.integration]


async def _seed(name: str, lastname: str, email: str | None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(name=name, lastname=lastname, email=email)
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


async def _relevance_ids(client: AsyncClient, headers: dict, q: str) -> list[int]:
    resp = await client.get(
        "/api/candidates",
        params={"q": q, "sort": "relevance", "page_size": 20},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return [item["id"] for item in resp.json()["items"]]


@pytest.mark.asyncio
async def test_exact_lastname_ranks_before_prefix_under_relevance(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = uuid.uuid4().hex[:8]
    surname = f"Kotow{tag}"
    # Właściciel nazwiska ma długie imię i adres — dużo trigramów spoza
    # zapytania, więc jego podobieństwo jest NIŻSZE niż u osób z prefiksem.
    owner = await _seed(
        "Bartłomiej-Maksymilian", surname, f"bartlomiej.maksymilian.{tag}@example.com"
    )
    prefix_short = await _seed("Ewa", f"{surname}ska", None)
    prefix_other = await _seed("Jan", f"{surname}icz", None)
    try:
        ids = await _relevance_ids(app_client, app_auth_headers, surname)
        assert {owner, prefix_short, prefix_other} <= set(ids), ids
        assert ids[0] == owner, ids
    finally:
        await _cleanup([owner, prefix_short, prefix_other])


@pytest.mark.asyncio
async def test_first_and_last_name_exact_ranks_first(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    tag = uuid.uuid4().hex[:8]
    surname = f"Kotow{tag}"
    owner = await _seed(
        "Andrzej", surname, f"andrzej.bardzo.dlugi.adres.{tag}@example.com"
    )
    prefix = await _seed("Andrzej", f"{surname}ski", None)
    try:
        ids = await _relevance_ids(app_client, app_auth_headers, f"Andrzej {surname}")
        assert owner in ids, ids
        if prefix in ids:
            assert ids.index(owner) < ids.index(prefix), ids
        assert ids[0] == owner, ids
    finally:
        await _cleanup([owner, prefix])
