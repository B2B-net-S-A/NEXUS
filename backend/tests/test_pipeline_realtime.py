"""Live kanban — ``pipeline_changed`` WebSocket event (17.09.2026).

A move made by one recruiter stayed invisible to a colleague on the same board
until a reload. After a committed board change the handler broadcasts
``{"type": "pipeline_changed", "data": {"job_id": ...}}`` to the recruitment's
team, except the author; the WebSocket manager drops it for users without the
pipeline section.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import app.models  # noqa: F401  (register every mapper)
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.services import pipeline_realtime
from app.services.notification_access import user_can_receive_realtime_event
from app.services.section_permissions import ProductSection


class _Db:
    """Request session stand-in: the lookup runs inside a savepoint."""

    def __init__(self) -> None:
        self.savepoints = 0
        self.rolled_back = 0

    def begin_nested(self):
        db = self

        class _Savepoint:
            async def __aenter__(self):
                db.savepoints += 1

            async def __aexit__(self, exc_type, exc, tb):
                if exc_type is not None:
                    db.rolled_back += 1
                return False

        return _Savepoint()


def _user(**access: str) -> User:
    user = User(
        id=963852,
        email="pipeline-realtime@example.com",
        name="Pipeline Realtime",
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value],
        is_active=True,
    )
    user.effective_section_access = {
        section.value: access.get(section.value, "none") for section in ProductSection
    }
    return user


@pytest.mark.asyncio
async def test_broadcast_reaches_the_team_but_not_the_author(monkeypatch):
    notify = AsyncMock()
    monkeypatch.setattr(
        pipeline_realtime, "list_job_member_ids", AsyncMock(return_value=[4, 7, 9])
    )
    monkeypatch.setattr(pipeline_realtime, "notify_user", notify)

    await pipeline_realtime.broadcast_pipeline_changed(_Db(), 12, 7)

    event = {"type": "pipeline_changed", "data": {"job_id": 12}}
    assert [c.args for c in notify.await_args_list] == [(4, event), (9, event)]


@pytest.mark.asyncio
async def test_broadcast_survives_a_dead_socket_and_a_failed_lookup(monkeypatch):
    notify = AsyncMock(side_effect=[RuntimeError("socket closed"), None])
    monkeypatch.setattr(
        pipeline_realtime, "list_job_member_ids", AsyncMock(return_value=[4, 9])
    )
    monkeypatch.setattr(pipeline_realtime, "notify_user", notify)
    await pipeline_realtime.broadcast_pipeline_changed(_Db(), 12, None)
    assert notify.await_count == 2

    db = _Db()
    monkeypatch.setattr(
        pipeline_realtime,
        "list_job_member_ids",
        AsyncMock(side_effect=RuntimeError("db gone")),
    )
    notify.reset_mock()
    await pipeline_realtime.broadcast_pipeline_changed(db, 12, None)
    notify.assert_not_awaited()
    # Only the savepoint is rolled back — never the request session.
    assert (db.savepoints, db.rolled_back) == (1, 1)


def test_pipeline_changed_needs_the_pipeline_section() -> None:
    event = {"type": "pipeline_changed", "data": {"job_id": 12}}
    assert not user_can_receive_realtime_event(_user(sourcing="write"), event)
    assert user_can_receive_realtime_event(_user(pipeline="read"), event)


@pytest.mark.asyncio
async def test_a_committed_move_broadcasts_for_its_job(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    from app.api import pipeline as pipeline_api
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    calls: list[tuple] = []

    async def capture(db, job_id, actor_id):
        calls.append((job_id, actor_id))

    monkeypatch.setattr(pipeline_api, "broadcast_pipeline_changed", capture)

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        admin_id = await db.scalar(
            select(User.id).where(
                User.email == app_client.headers.get("X-Test-Admin-Email")
            )
        )
        client = Client(name=f"RealtimeClient-{tag}")
        candidate = Candidate(
            name="Realtime", lastname=f"Move-{tag}", email=f"rt-{tag}@example.com"
        )
        db.add_all([client, candidate])
        await db.flush()
        job = Job(
            title=f"RealtimeJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        job_id, candidate_id = job.id, candidate.id

    resp = await app_client.post(
        "/api/pipeline/move",
        headers=app_auth_headers,
        json={"candidate_id": candidate_id, "job_id": job_id, "stage": "screening"},
    )

    assert resp.status_code == 200, resp.text
    assert calls == [(job_id, admin_id)]
