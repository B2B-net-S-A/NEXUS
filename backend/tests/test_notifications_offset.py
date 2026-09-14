"""B51 — dzwonek pokazywał tylko pierwsze ``limit`` powiadomień, bez drogi do
starszych. ``GET /api/notifications`` przyjmuje teraz ``offset``; strony nie
nachodzą na siebie i razem dają komplet.
"""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.notification import Notification, NotificationType
from app.models.user import User


async def _current_user_id(app_client: AsyncClient) -> int:
    email = app_client.headers.get("X-Test-Admin-Email")
    async with AsyncSessionLocal() as db:
        uid = await db.scalar(select(User.id).where(User.email == email))
    assert uid is not None
    return uid


async def _seed(user_id: int, count: int) -> str:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        for i in range(count):
            db.add(
                Notification(
                    user_id=user_id,
                    title=f"offset-{tag}-{i}",
                    message="body",
                    notification_type=NotificationType.candidate_added,
                    is_read=False,
                )
            )
        await db.commit()
    return tag


@pytest.mark.asyncio
async def test_offset_pages_do_not_overlap_and_reach_older_rows(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    uid = await _current_user_id(app_client)
    tag = await _seed(uid, 5)

    async def page(offset: int) -> list[int]:
        resp = await app_client.get(
            "/api/notifications",
            headers=app_auth_headers,
            params={"limit": 2, "offset": offset},
        )
        assert resp.status_code == 200, resp.text
        return [item["id"] for item in resp.json()["items"] if tag in item["title"]]

    # Bez offsetu = stara semantyka (pierwsza strona).
    first = await app_client.get(
        "/api/notifications", headers=app_auth_headers, params={"limit": 2}
    )
    assert first.status_code == 200
    assert len(first.json()["items"]) == 2

    # Wszystkie wiersze tego testu są nowsze niż cokolwiek innego w bazie, więc
    # przy „nieprzeczytane najpierw, najnowsze najpierw" zajmują początek listy.
    seen: list[int] = []
    for offset in (0, 2, 4):
        seen.extend(await page(offset))
    assert len(seen) == 5
    assert len(set(seen)) == 5, "strony nachodzą na siebie"

    # Poza końcem listy — pusta strona, nie błąd.
    async with AsyncSessionLocal() as db:
        total_mine = await db.scalar(
            select(Notification.id).where(Notification.user_id == uid).limit(1)
        )
    assert total_mine is not None
    far = await app_client.get(
        "/api/notifications",
        headers=app_auth_headers,
        params={"limit": 2, "offset": 100_000},
    )
    assert far.status_code == 200
    assert far.json()["items"] == []


@pytest.mark.asyncio
async def test_negative_offset_is_rejected(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    resp = await app_client.get(
        "/api/notifications", headers=app_auth_headers, params={"offset": -1}
    )
    assert resp.status_code == 422
