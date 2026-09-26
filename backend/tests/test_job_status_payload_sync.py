"""Runda 8 (R8-N11-2): zmiana statusu rekrutacji poprawia payload w Qdrancie.

Status trafiał do payloadu punktu oferty wyłącznie przy embedzie, a zmiana
statusu nie zmienia tekstu embeddingu. Rekrutacja otwarta ponownie z payloadem
„closed" znikała z puli `search_jobs_semantic(statuses=…)` (rekomendacje ofert
dla kandydata), a zamknięta z payloadem „published" dalej ją zajmowała.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import update

from app.core.database import AsyncSessionLocal
from app.models.client import Client
from app.models.job import Job

pytestmark = pytest.mark.asyncio


async def _job(app_client: AsyncClient, headers: dict, *, embedded: bool) -> int:
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"R8-N11-2-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        client_id = cli.id
    resp = await app_client.post(
        "/api/jobs",
        json={
            "title": f"r8-n11-2-{uuid.uuid4().hex[:6]}",
            "recruitment_type": "body_leasing",
            "work_mode": "fulltime",
            "client_id": client_id,
        },
        headers=headers,
    )
    assert resp.status_code in (200, 201), resp.text
    job_id = resp.json()["id"]
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(Job)
            .where(Job.id == job_id)
            .values(embedding_id=str(job_id) if embedded else None)
        )
        await db.commit()
    return job_id


@pytest.fixture
def payload_writes(monkeypatch):
    from app.services import embedding_service

    calls: list[dict] = []

    async def _record(statuses):
        calls.append(dict(statuses))
        return len(statuses)

    monkeypatch.setattr(embedding_service, "sync_job_status_payloads", _record)
    return calls


async def test_close_then_publish_rewrites_the_status_payload(
    app_client: AsyncClient, app_auth_headers: dict, payload_writes
) -> None:
    job_id = await _job(app_client, app_auth_headers, embedded=True)

    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "other"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert payload_writes[-1] == {job_id: "closed"}

    resp = await app_client.post(
        f"/api/jobs/{job_id}/publish", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert payload_writes[-1] == {job_id: "published"}


async def test_patch_status_rewrites_the_status_payload(
    app_client: AsyncClient, app_auth_headers: dict, payload_writes
) -> None:
    job_id = await _job(app_client, app_auth_headers, embedded=True)

    resp = await app_client.patch(
        f"/api/jobs/{job_id}", json={"status": "closed"}, headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text
    assert payload_writes[-1] == {job_id: "closed"}


async def test_job_without_a_vector_is_not_touched(
    app_client: AsyncClient, app_auth_headers: dict, payload_writes
) -> None:
    job_id = await _job(app_client, app_auth_headers, embedded=False)

    resp = await app_client.post(
        f"/api/jobs/{job_id}/close",
        json={"reason": "other"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert payload_writes == []


class _FakeQdrant:
    points: set = set()
    set_calls: list = []

    def __init__(self, *_a, **_kw) -> None:
        pass

    def retrieve(self, *, collection_name, ids, **_kw):
        from types import SimpleNamespace

        return [SimpleNamespace(id=i, payload={}) for i in ids if i in self.points]

    def set_payload(self, *, collection_name, payload, points):
        type(self).set_calls.append((payload, sorted(points)))


async def test_sync_writes_only_existing_points_grouped_by_status(monkeypatch):
    import qdrant_client

    from app.services import embedding_service

    _FakeQdrant.points = {1, 2, 4}
    _FakeQdrant.set_calls = []
    monkeypatch.setattr(qdrant_client, "QdrantClient", _FakeQdrant)

    updated = await embedding_service.sync_job_status_payloads(
        {1: "closed", 2: "closed", 3: "published", 4: "published"}
    )

    assert updated == 3
    assert sorted(_FakeQdrant.set_calls, key=str) == sorted(
        [({"status": "closed"}, [1, 2]), ({"status": "published"}, [4])], key=str
    )


async def test_sync_never_raises_when_qdrant_is_down(monkeypatch):
    import qdrant_client

    from app.services import embedding_service

    class _Down:
        def __init__(self, *_a, **_kw) -> None:
            raise ConnectionError("qdrant down")

    monkeypatch.setattr(qdrant_client, "QdrantClient", _Down)
    assert await embedding_service.sync_job_status_payloads({1: "closed"}) == 0
