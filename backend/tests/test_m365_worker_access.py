"""Fail-closed RBAC checks at Microsoft 365 worker execution boundaries."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.m365 import M365Connection, M365SyncStatus
from app.models.recruitment_pipeline import PipelineStage
from app.models.rejection_email import RejectionEmailStatus
from app.models.user import User, UserRole
from app.services import rejection_email_scheduler
from app.services.m365 import sender, sync, webhooks
from app.services.m365.access import M365OwnerIneligible
from app.services.m365.graph_client import GraphClient
from app.tasks import microsoft365_sync


def _user(role: UserRole) -> User:
    return User(
        id=37,
        email=f"m365-worker-{role.value}@example.com",
        name=f"M365 worker {role.value}",
        role=role,
        roles=[role.value],
        is_active=True,
        authorization_version=1,
    )


def _connection() -> SimpleNamespace:
    return SimpleNamespace(
        id=81,
        user_id=37,
        is_active=True,
        last_sync_status=M365SyncStatus.idle,
        last_error="preserve-me",
        mailbox_upn="owner@example.com",
    )


# Finance ma od 19.08 pelny dostep operacyjny (user_can_access_candidate_domain
# przepuszcza) — jedyna nieuprawniona persona to wycofywany viewer `user`.
@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_polling_tick_filters_ineligible_owner_before_execution(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _connection()
    owner = _user(role)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [connection])
    )
    db.get.return_value = owner

    @asynccontextmanager
    async def _session():
        yield db

    run_sync = AsyncMock()
    monkeypatch.setattr(microsoft365_sync, "AsyncSessionLocal", _session)
    monkeypatch.setattr(microsoft365_sync, "sync_connection", run_sync)

    await microsoft365_sync._tick(interval=300)

    run_sync.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_sync_connection_refuses_owner_without_mutating_connection(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _connection()
    db = AsyncMock()
    db.get.return_value = _user(role)
    graph_client = MagicMock()
    monkeypatch.setattr(sync, "GraphClient", graph_client)

    result = await sync.sync_connection(db, connection)

    assert result.connection_id == connection.id
    assert result.messages_ingested == 0
    assert result.events_ingested == 0
    assert connection.is_active is True
    assert connection.last_sync_status == M365SyncStatus.idle
    assert connection.last_error == "preserve-me"
    db.commit.assert_not_awaited()
    graph_client.assert_not_called()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_sender_refuses_before_idempotency_or_graph(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _connection()
    db = AsyncMock()
    db.get.return_value = _user(role)
    graph_client = MagicMock()
    monkeypatch.setattr(sender, "GraphClient", graph_client)

    with pytest.raises(M365OwnerIneligible):
        await sender.send_new(
            db,
            connection,
            to=["candidate@example.com"],
            subject="Candidate update",
            body_html="<p>PII</p>",
        )

    db.scalar.assert_not_awaited()
    db.flush.assert_not_awaited()
    graph_client.assert_not_called()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_graph_client_context_is_final_fail_closed_boundary(
    role: UserRole,
) -> None:
    """Even a future caller that forgets its worker guard cannot reach Graph."""

    client = object.__new__(GraphClient)
    client._conn = _connection()
    client._db = AsyncMock()
    client._db.get.return_value = _user(role)
    client._client = SimpleNamespace(aclose=AsyncMock())

    with pytest.raises(M365OwnerIneligible):
        await client.__aenter__()

    client._client.aclose.assert_awaited_once()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_graph_client_rechecks_role_before_each_outbound_request(
    role: UserRole,
) -> None:
    """A role cutover during a long sync stops its next Graph page request."""

    client = object.__new__(GraphClient)
    client._conn = _connection()
    client._db = AsyncMock()
    client._db.get.return_value = _user(role)
    client._client = SimpleNamespace(request=AsyncMock())

    with pytest.raises(M365OwnerIneligible):
        await client._request("GET", "/me/messages")

    client._client.request.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_subscription_renewal_does_not_touch_graph_or_rows(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _connection()
    subscription = SimpleNamespace(id=9, m365_connection_id=connection.id)
    owner = _user(role)
    db = AsyncMock()

    async def _get(model, row_id, **_kwargs):
        if model is M365Connection and row_id == connection.id:
            return connection
        if model is User and row_id == owner.id:
            return owner
        return None

    db.get.side_effect = _get
    monkeypatch.setattr(
        webhooks,
        "list_due_for_renewal",
        AsyncMock(return_value=[subscription]),
    )
    renew = AsyncMock()
    graph_client = MagicMock()
    monkeypatch.setattr(webhooks, "renew", renew)
    monkeypatch.setattr(microsoft365_sync, "GraphClient", graph_client)

    await microsoft365_sync._renewal_tick(db)

    graph_client.assert_not_called()
    renew.assert_not_awaited()
    db.delete.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_recording_connection_lookup_stops_before_connection_query(
    role: UserRole,
) -> None:
    db = AsyncMock()
    db.get.return_value = _user(role)

    connection = await microsoft365_sync._active_connection_for_user(db, 37)

    assert connection is None
    db.get.assert_awaited_once_with(User, 37, populate_existing=True)
    db.execute.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_rejection_worker_marks_ineligible_owner_skipped_without_retry(
    role: UserRole,
) -> None:
    row = SimpleNamespace(
        id=501,
        recruiter_id=37,
        status=RejectionEmailStatus.pending,
        last_error=None,
    )
    db = AsyncMock()
    db.scalar.return_value = row
    db.get.return_value = _user(role)

    await rejection_email_scheduler.dispatch(db, row.id)

    assert row.status == RejectionEmailStatus.skipped
    assert row.last_error == "m365_owner_outside_candidate_domain"
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert db.scalar.await_count == 1


@pytest.mark.asyncio
async def test_rejection_worker_treats_role_change_at_send_as_terminal_skip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        id=502,
        recruiter_id=37,
        candidate_id=70,
        job_id=80,
        to_email="candidate@example.com",
        subject="Update",
        body_html="<p>Update</p>",
        status=RejectionEmailStatus.pending,
        last_error=None,
    )
    connection = _connection()
    db = AsyncMock()
    db.scalar.side_effect = [row, PipelineStage.rejected, connection]
    db.get.return_value = _user(UserRole.recruiter)
    send_new = AsyncMock(side_effect=M365OwnerIneligible("role changed"))
    monkeypatch.setattr(sender, "send_new", send_new)

    await rejection_email_scheduler.dispatch(db, row.id)

    assert row.status == RejectionEmailStatus.skipped
    assert row.last_error == "m365_owner_outside_candidate_domain"
    db.rollback.assert_not_awaited()
    db.commit.assert_awaited_once()
