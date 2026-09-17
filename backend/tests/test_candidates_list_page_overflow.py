"""GET /api/candidates — strona poza zakresem zwraca prawdziwą sumę.

`count(*) OVER()` jedzie na wierszach strony, więc pusta strona dawała
`total = 0`: lista pokazywała „0 wyników” bez paginacji do powrotu (audyt
narzędzi rekrutera 17.09.2026, P3). Front na podstawie `total` cofa do
ostatniej strony — musi więc dostać realną liczbę.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed(lastname: str, count: int) -> list[int]:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    ids: list[int] = []
    async with AsyncSessionLocal() as db:
        for i in range(count):
            c = Candidate(
                name=f"Overflow{i}",
                lastname=lastname,
                email=f"overflow-{uuid.uuid4().hex[:10]}@example.com",
            )
            db.add(c)
            await db.flush()
            ids.append(c.id)
        await db.commit()
    return ids


async def _cleanup(ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_page_past_the_end_reports_real_total(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    scope = uuid.uuid4().hex[:10]
    ids = await _seed(scope, 3)
    try:
        in_range = await app_client.get(
            "/api/candidates",
            params={"q": scope, "page": 1, "page_size": 2},
            headers=app_auth_headers,
        )
        assert in_range.status_code == 200, in_range.text
        assert in_range.json()["total"] == 3

        overflow = await app_client.get(
            "/api/candidates",
            params={"q": scope, "page": 9, "page_size": 2},
            headers=app_auth_headers,
        )
        assert overflow.status_code == 200, overflow.text
        body = overflow.json()
        assert body["items"] == []
        assert body["total"] == 3
    finally:
        await _cleanup(ids)


@pytest.mark.asyncio
async def test_empty_result_on_first_page_stays_zero(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
) -> None:
    resp = await app_client.get(
        "/api/candidates",
        params={"q": f"brak-{uuid.uuid4().hex}", "page": 3, "page_size": 20},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 0
