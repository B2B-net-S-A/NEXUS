"""UAT M00-B02: wyszukiwanie po telefonie niezależne od zapisu numeru.

`GET /api/candidates?q=` porównywało podciąg ZAPISANEGO tekstu, więc numer
wpisany ze spacjami nie trafiał w numer zapisany ciągiem cyfr (i odwrotnie).
"""

from __future__ import annotations

import random
import uuid

import pytest
from httpx import AsyncClient


def _digits() -> str:
    # 9 cyfr zaczynających się od 0 — nie przypomina prawdziwego numeru.
    return "0" + "".join(random.choice("0123456789") for _ in range(8))


async def _seed(phone: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Telefon",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"phone-{uuid.uuid4().hex[:8]}@example.com",
            phone=phone,
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
        "/api/candidates", params={"q": q, "page_size": 100}, headers=headers
    )
    assert r.status_code == 200, r.text
    return [item["id"] for item in r.json()["items"]]


@pytest.mark.asyncio
async def test_phone_query_matches_regardless_of_separators(
    app_client: AsyncClient, app_auth_headers: dict
):
    compact = _digits()
    spaced = _digits()
    compact_id = await _seed(compact)
    spaced_id = await _seed(f"+48 {spaced[:3]}-{spaced[3:6]} {spaced[6:]}")
    try:
        spaced_query = f"{compact[:3]} {compact[3:6]} {compact[6:]}"
        assert compact_id in await _search(app_client, app_auth_headers, spaced_query)
        assert compact_id in await _search(app_client, app_auth_headers, compact)
        assert compact_id in await _search(
            app_client, app_auth_headers, f"+48{compact}"
        )

        assert spaced_id in await _search(app_client, app_auth_headers, spaced)
        assert spaced_id in await _search(
            app_client, app_auth_headers, f"{spaced[:3]}-{spaced[3:6]}-{spaced[6:]}"
        )
        # Fragment numeru (≥6 cyfr) też trafia.
        assert spaced_id in await _search(
            app_client, app_auth_headers, f"{spaced[3:6]} {spaced[6:]}"
        )
    finally:
        await _cleanup([compact_id, spaced_id])


def test_phone_clause_only_for_phone_shaped_queries():
    from app.api.candidates import _phone_digits_clause

    assert _phone_digits_clause("Python") is None
    assert _phone_digits_clause("123") is None  # za mało cyfr
    assert _phone_digits_clause("Jan 600 700 800") is None
    assert _phone_digits_clause("600 700 800") is not None
    assert _phone_digits_clause("+48 (600) 700-800") is not None
