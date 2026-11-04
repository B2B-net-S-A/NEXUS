"""Live kanban — ``pipeline_changed`` WebSocket event (17.09.2026).

A move made by one recruiter stayed invisible to a colleague on the same board
until a reload. After a committed board change the handler broadcasts
``{"type": "pipeline_changed", "data": {"job_id": ...}}`` to the recruitment's
team, except the author; the WebSocket manager drops it for users without the
pipeline section.

27.10.2026: admins outside the team no longer get every move in the company —
only while they have the board open (presence ``job:{id}``) — and the payload
names the job's Delivery Lead so only their "to send" queue refreshes.
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

    def __init__(self, delivery_lead_id: int | None = 8) -> None:
        self.savepoints = 0
        self.rolled_back = 0
        self.delivery_lead_id = delivery_lead_id

    async def get(self, model, pk):
        if model is User:
            return User(id=pk, is_active=True)
        return model(id=pk, delivery_lead_id=self.delivery_lead_id)

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


@pytest.fixture
def no_viewers(monkeypatch):
    monkeypatch.setattr(pipeline_realtime.manager, "viewer_ids", lambda *_: set())


@pytest.mark.asyncio
async def test_broadcast_reaches_the_team_but_not_the_author(monkeypatch, no_viewers):
    notify = AsyncMock()
    members = AsyncMock(return_value=[4, 7, 9])
    monkeypatch.setattr(pipeline_realtime, "list_job_member_ids", members)
    monkeypatch.setattr(pipeline_realtime, "notify_user", notify)

    await pipeline_realtime.broadcast_pipeline_changed(_Db(), 12, 7)

    event = {"type": "pipeline_changed", "data": {"job_id": 12, "delivery_lead_id": 8}}
    assert [c.args for c in notify.await_args_list] == [(4, event), (9, event)]
    # Admins outside the team are not "the team".
    assert members.await_args.kwargs == {"include_admins": False}


@pytest.mark.asyncio
async def test_whoever_has_the_board_open_gets_it_too_but_not_the_author(monkeypatch):
    """An admin outside the team watching the board still sees moves live."""
    notify = AsyncMock()
    monkeypatch.setattr(
        pipeline_realtime, "list_job_member_ids", AsyncMock(return_value=[4, 9])
    )
    monkeypatch.setattr(pipeline_realtime, "notify_user", notify)
    monkeypatch.setattr(pipeline_realtime, "ensure_job_read_access", AsyncMock())
    seen: list[tuple] = []

    def viewers(resource_type, resource_id):
        seen.append((resource_type, resource_id))
        return {9, 21, 7}

    monkeypatch.setattr(pipeline_realtime.manager, "viewer_ids", viewers)

    await pipeline_realtime.broadcast_pipeline_changed(
        _Db(delivery_lead_id=None), 12, 7
    )

    assert seen == [("job", 12)]
    event = {
        "type": "pipeline_changed",
        "data": {"job_id": 12, "delivery_lead_id": None},
    }
    assert [c.args for c in notify.await_args_list] == [
        (4, event),
        (9, event),
        (21, event),
    ]


@pytest.mark.asyncio
async def test_a_watcher_without_access_to_the_board_gets_nothing(monkeypatch):
    """Presence is a role check only; the board itself is members-only."""
    from fastapi import HTTPException

    notify = AsyncMock()
    monkeypatch.setattr(
        pipeline_realtime, "list_job_member_ids", AsyncMock(return_value=[4])
    )
    monkeypatch.setattr(pipeline_realtime, "notify_user", notify)
    monkeypatch.setattr(pipeline_realtime.manager, "viewer_ids", lambda *_: {4, 21, 30})
    checked: list[int] = []

    async def guard(db, user, job_id):
        checked.append(user.id)
        if user.id == 21:
            raise HTTPException(status_code=403, detail="no access")

    monkeypatch.setattr(pipeline_realtime, "ensure_job_read_access", guard)

    await pipeline_realtime.broadcast_pipeline_changed(_Db(), 12, None)

    # Team members are not re-checked; the outsider without access is dropped.
    assert sorted(checked) == [21, 30]
    assert [c.args[0] for c in notify.await_args_list] == [4, 30]


@pytest.mark.asyncio
async def test_viewer_ids_lists_every_open_tab_of_the_job_only() -> None:
    from app.api.ws import ConnectionManager

    manager = ConnectionManager()
    manager._viewers = {
        "job:12": {3: {object()}, 5: {object()}},
        "job:13": {6: {object()}},
    }
    assert manager.viewer_ids("job", 12) == {3, 5}
    assert manager.viewer_ids("job", 99) == set()


@pytest.mark.asyncio
async def test_broadcast_survives_a_dead_socket_and_a_failed_lookup(
    monkeypatch, no_viewers
):
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


@pytest.mark.asyncio
async def test_member_list_without_admins_leaves_out_admins_outside_the_team(
    app_client: AsyncClient,
):
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.services.job_membership import list_job_member_ids

    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        admin_id = await db.scalar(
            select(User.id).where(
                User.email == app_client.headers.get("X-Test-Admin-Email")
            )
        )
        client = Client(name=f"RealtimeAdmins-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"RealtimeAdmins-{tag}",
            status=JobStatus.published,
            client_id=client.id,
        )
        db.add(job)
        await db.commit()
        job_id = job.id

    async with AsyncSessionLocal() as db:
        # Chat, mentions and access still count every admin as a member.
        assert admin_id in await list_job_member_ids(db, job_id)
        assert admin_id not in await list_job_member_ids(
            db, job_id, include_admins=False
        )
