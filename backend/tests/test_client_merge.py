"""POST /api/clients/{id}/merge-into/{target} — kanonizacja duplikatów (Faza B).

Merge NIE przepisuje danych: historia zostaje na scalanym wierszu, wiersz znika
z katalogu/lookupów (filtry ``merged_into_client_id IS NULL``), a detail
przekierowuje 307 na kanoniczny rekord. Pierwszy klient ścieżki: e-Zdrowie
37721 → 115.

Pattern: in-process app_client / app_auth_headers (admin).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.client import Client

pytestmark = pytest.mark.asyncio


async def _new_client(**kwargs) -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Client(name=f"Merge Test {suffix}", **kwargs)
        db.add(c)
        await db.flush()
        await db.commit()
        return c.id


async def _cleanup(*client_ids: int) -> None:
    async with AsyncSessionLocal() as db:
        # Najpierw wskazujące (FK RESTRICT na merged_into), potem cele.
        for cid in client_ids:
            await db.execute(Client.__table__.delete().where(Client.id == cid))
        await db.commit()


async def test_merge_archives_source_and_redirects(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    source_id = await _new_client()
    target_id = await _new_client()
    try:
        resp = await app_client.post(
            f"/api/clients/{source_id}/merge-into/{target_id}",
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text

        async with AsyncSessionLocal() as db:
            row = await db.scalar(select(Client).where(Client.id == source_id))
            assert row is not None
            assert row.merged_into_client_id == target_id
            assert row.archived_at is not None
            assert row.archived_by is not None

        # Detail scalonego wiersza przekierowuje na kanoniczny rekord.
        get_resp = await app_client.get(
            f"/api/clients/{source_id}", headers=app_auth_headers
        )
        assert get_resp.status_code == 307
        assert get_resp.headers["location"].endswith(f"/api/clients/{target_id}")

        # Idempotentny replay — to samo żądanie drugi raz przechodzi.
        replay = await app_client.post(
            f"/api/clients/{source_id}/merge-into/{target_id}",
            headers=app_auth_headers,
        )
        assert replay.status_code == 200
    finally:
        await _cleanup(source_id, target_id)


async def test_merge_guards(app_client: AsyncClient, app_auth_headers: dict[str, str]):
    a = await _new_client()
    b = await _new_client()
    c = await _new_client()
    try:
        # Self-merge → 422.
        resp = await app_client.post(
            f"/api/clients/{a}/merge-into/{a}", headers=app_auth_headers
        )
        assert resp.status_code == 422

        # Nieistniejący cel → 404.
        resp = await app_client.post(
            f"/api/clients/{a}/merge-into/999999999", headers=app_auth_headers
        )
        assert resp.status_code == 404

        # b scalony w a; scalanie CZEGOKOLWIEK w b (nie-kanoniczny) → 409.
        resp = await app_client.post(
            f"/api/clients/{b}/merge-into/{a}", headers=app_auth_headers
        )
        assert resp.status_code == 200
        resp = await app_client.post(
            f"/api/clients/{c}/merge-into/{b}", headers=app_auth_headers
        )
        assert resp.status_code == 409

        # Źródło już scalone w a — merge w INNY cel → 409 (bez cichego przepięcia).
        resp = await app_client.post(
            f"/api/clients/{b}/merge-into/{c}", headers=app_auth_headers
        )
        assert resp.status_code == 409
    finally:
        await _cleanup(b, c, a)
