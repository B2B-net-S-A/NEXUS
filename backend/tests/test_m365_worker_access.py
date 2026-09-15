"""Fail-closed RBAC checks at Microsoft 365 worker execution boundaries."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.dialects import postgresql

from app.models.m365 import M365Connection, M365SyncStatus
from app.models.recruitment_pipeline import PipelineStage
from app.models.rejection_email import RejectionEmailStatus
from app.models.section_permission import (
    RoleSectionPermission,
    UserSectionOverride,
)
from app.models.user import User, UserRole
from app.services import rejection_email_scheduler
from app.services.m365 import sender, sync, webhooks
from app.services.m365.access import M365OwnerIneligible
from app.services.m365.graph_client import GraphClient
from app.services.section_permissions import (
    DEFAULT_ROLE_SECTION_ACCESS,
    ProductSection,
)
from app.tasks import m365_cv_parse, microsoft365_sync


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


def _policy_db() -> AsyncMock:
    """AsyncSession double with the authoritative section-policy queries."""

    db = AsyncMock()
    # AsyncSession.add() is synchronous; leaving the dynamically-created
    # AsyncMock in place hides incorrect awaits and emits un-awaited warnings.
    db.add = MagicMock()
    role_rows = [
        RoleSectionPermission(
            role=role.value,
            section=section.value,
            access=access.name,
        )
        for role, policy in DEFAULT_ROLE_SECTION_ACCESS.items()
        for section, access in policy.items()
    ]

    async def _scalars(statement):
        entity = statement.column_descriptions[0].get("entity")
        rows = role_rows if entity is RoleSectionPermission else []
        assert entity in {RoleSectionPermission, UserSectionOverride}
        return SimpleNamespace(all=lambda: rows)

    db.scalars.side_effect = _scalars
    return db


@pytest.mark.asyncio
async def test_cv_worker_commits_result_outside_graph_sync(monkeypatch) -> None:
    """The durable worker owns paid parsing after the Graph page is committed."""
    attachment = SimpleNamespace(
        id=91,
        email_id=72,
        parsed_candidate_id=None,
    )
    email = SimpleNamespace(id=72, candidate_id=37)
    db = AsyncMock()
    db.scalar.return_value = attachment
    db.get.return_value = email

    @asynccontextmanager
    async def _session():
        yield db

    async def _parse(_db, claimed, email_row):
        assert _db is db
        assert claimed is attachment
        claimed.parsed_candidate_id = email_row.candidate_id

    outcome = MagicMock()
    monkeypatch.setattr(m365_cv_parse, "AsyncSessionLocal", _session)
    monkeypatch.setattr(m365_cv_parse.attachment_handler, "try_parse_cv", _parse)
    monkeypatch.setattr(m365_cv_parse, "record_job_outcome", outcome)
    monkeypatch.setattr(m365_cv_parse.settings, "M365_INTEGRATION_ENABLED", True)
    monkeypatch.setattr(m365_cv_parse.settings, "M365_AUTO_PARSE_CV", True)

    assert await m365_cv_parse.run_m365_cv_parse_once() is True
    claim = db.scalar.await_args.args[0]
    claim_sql = str(claim.compile(dialect=postgresql.dialect()))
    assert "IS DISTINCT FROM" in claim_sql
    assert "FOR UPDATE OF email_attachments SKIP LOCKED" in claim_sql
    db.commit.assert_awaited_once()
    outcome.assert_called_once_with(
        "m365_cv_parse",
        True,
        interval_seconds=max(60, m365_cv_parse.settings.M365_CV_PARSE_INTERVAL_SECONDS),
        subject_id=attachment.id,
    )


def test_graph_sync_does_not_run_cv_parser_inline() -> None:
    """Regression guard for the eight-minute page timeout."""
    import inspect

    source = inspect.getsource(sync._upsert_message)
    assert "download_for_email" in source
    assert "try_parse_cv" not in source


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
    db = _policy_db()
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
    db = _policy_db()
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
    db = _policy_db()
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
    client._db = _policy_db()
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
    client._db = _policy_db()
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
    db = _policy_db()

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
    db = _policy_db()
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
    db = _policy_db()
    db.scalar.return_value = row
    db.get.return_value = _user(role)

    await rejection_email_scheduler.dispatch(db, row.id)

    assert row.status == RejectionEmailStatus.skipped
    assert row.last_error == "m365_owner_outside_candidate_domain"
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()
    assert db.scalar.await_count == 1


@pytest.mark.asyncio
async def test_rejection_worker_skips_after_pipeline_write_is_revoked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row = SimpleNamespace(
        id=503,
        recruiter_id=37,
        candidate_id=70,
        job_id=80,
        status=RejectionEmailStatus.pending,
        last_error=None,
    )
    owner = _user(UserRole.recruiter)
    owner.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    owner.effective_section_access[ProductSection.sourcing.value] = "write"
    eligible_owner = AsyncMock(return_value=owner)
    send_new = AsyncMock()
    db = _policy_db()
    db.scalar.return_value = row
    monkeypatch.setattr(
        rejection_email_scheduler,
        "eligible_m365_owner",
        eligible_owner,
    )
    monkeypatch.setattr(sender, "send_new", send_new)

    await rejection_email_scheduler.dispatch(db, row.id)

    assert row.status == RejectionEmailStatus.skipped
    assert row.last_error == "pipeline_write_access_revoked"
    send_new.assert_not_awaited()
    db.flush.assert_awaited_once()
    db.commit.assert_awaited_once()
    audit = db.add.call_args.args[0]
    assert audit.action == "rejection_email_skipped"
    assert audit.details["reason"] == "pipeline_write_access_revoked"


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
    db = _policy_db()
    db.scalar.side_effect = [row, PipelineStage.rejected, connection]
    db.get.return_value = _user(UserRole.recruiter)
    send_new = AsyncMock(side_effect=M365OwnerIneligible("role changed"))
    monkeypatch.setattr(sender, "send_new", send_new)

    await rejection_email_scheduler.dispatch(db, row.id)

    assert row.status == RejectionEmailStatus.skipped
    assert row.last_error == "m365_owner_outside_candidate_domain"
    db.rollback.assert_not_awaited()
    db.commit.assert_awaited_once()
