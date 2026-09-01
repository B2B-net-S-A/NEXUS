"""Regression: editing a job with a `deadline` must not 503.

Root cause (fixed in `app/core/database._json_serializer`): `update_job`
writes the raw update dict into `Activity.details` (JSONB). When the payload
carries a `deadline`, Pydantic hands the handler a `datetime.date` object —
which the stdlib JSON serializer cannot encode (`TypeError: Object of type
date is not JSON serializable`). The flush blew up and the request died with a
non-CORS 503 that the frontend surfaced as "Błąd podczas zapisywania".

Two layers of coverage:
  1. Unit — the engine serializer itself encodes a `date` (fast, no DB).
  2. Integration — POST a job then PATCH it with a `deadline`, exercising the
     real `Activity.details` write path that regressed.
"""

from __future__ import annotations

import json
import uuid
from datetime import date

import pytest
import pytest_asyncio
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal, _json_serializer
from app.models.client import Client


def test_json_serializer_encodes_date() -> None:
    """A `date` inside a JSONB payload serializes to an ISO string."""
    payload = {"deadline": date(2023, 4, 12), "status": "closed", "headcount": 1}
    encoded = json.loads(_json_serializer(payload))
    assert encoded["deadline"] == "2023-04-12"
    assert encoded["status"] == "closed"


def test_default_json_dumps_would_have_failed() -> None:
    """Documents the original failure mode the serializer guards against."""
    with pytest.raises(TypeError):
        json.dumps({"deadline": date(2023, 4, 12)})


@pytest_asyncio.fixture
async def seeded_client_id() -> int:
    suffix = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"DeadlineRegr Client {suffix}")
        db.add(client)
        await db.flush()
        client_id = client.id
        await db.commit()
    return client_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_patch_job_with_deadline_persists(
    app_client: AsyncClient, app_auth_headers: dict, seeded_client_id: int
) -> None:
    """PATCH /jobs/{id} with a `deadline` returns 200 and persists the date.

    Before the fix this returned 5xx (Activity.details JSONB write failed on
    the `date` object). The Activity row is written on every job update, so a
    plain field change on any job that carries a deadline tripped it.
    """
    job_id: int | None = None
    try:
        create = await app_client.post(
            "/api/jobs",
            headers=app_auth_headers,
            json={
                "title": "Deadline serialization regression",
                "client_id": seeded_client_id,
                "auto_suggest_cc": False,
            },
        )
        assert create.status_code == 201, create.text
        job_id = create.json()["id"]

        patch = await app_client.patch(
            f"/api/jobs/{job_id}",
            headers=app_auth_headers,
            json={"deadline": "2023-04-12"},
        )
        assert patch.status_code == 200, patch.text
        assert patch.json()["deadline"] == "2023-04-12"

        get = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
        assert get.status_code == 200
        assert get.json()["deadline"] == "2023-04-12"
    finally:
        async with AsyncSessionLocal() as db:
            from app.models.job import Job

            if job_id is not None:
                job = await db.get(Job, job_id)
                if job is not None:
                    await db.delete(job)
            client = await db.get(Client, seeded_client_id)
            if client is not None:
                await db.delete(client)
            await db.commit()
