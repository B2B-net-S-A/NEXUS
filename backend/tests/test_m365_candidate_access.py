"""Candidate-domain boundary for Microsoft 365 and synced mailbox data."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import email_threads, microsoft365
from app.api.candidate_access import CandidatePIIAccess, CandidateWriteAccess
from app.models.m365 import M365Connection
from app.models.user import User, UserRole


def _user(role: UserRole) -> User:
    return User(
        id=37,
        email=f"m365-{role.value}@example.com",
        name=f"M365 {role.value}",
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
        authorization_version=1,
    )


def test_all_user_facing_m365_and_mailbox_routes_use_candidate_guard() -> None:
    """A future sibling route must not silently fall back to plain auth."""

    read_handlers = (
        microsoft365.authorize,
        microsoft365.get_connection,
        microsoft365.disconnect,
        microsoft365.trigger_sync,
        microsoft365.free_busy,
        email_threads.list_candidate_emails,
        email_threads.list_thread_messages,
        email_threads.get_email,
        email_threads.download_attachment,
        email_threads.search_emails,
    )
    write_handlers = (
        email_threads.compose_email,
        email_threads.reply_email,
        email_threads.bulk_email_action,
    )

    for handler in read_handlers:
        annotation = get_type_hints(handler, include_extras=True)["current_user"]
        assert annotation == CandidatePIIAccess, handler.__name__
    for handler in write_handlers:
        annotation = get_type_hints(handler, include_extras=True)["current_user"]
        assert annotation == CandidateWriteAccess, handler.__name__


def test_email_search_openapi_keeps_current_user_as_dependency() -> None:
    """slowapi must not turn the candidate guard into a public query field."""

    from app.main import app
    from tests._route_introspection import iter_api_routes

    route = next(
        route
        for path, route in iter_api_routes(app)
        if path == "/api/microsoft365/emails/search"
    )
    assert all(param.name != "current_user" for param in route.dependant.query_params)
    assert any(
        dependency.name == "current_user" for dependency in route.dependant.dependencies
    )

    # This used to raise PydanticUserError because the unresolved dependency
    # was registered as Annotated[ForwardRef(...), Query(...)].
    app.openapi_schema = None
    operation = app.openapi()["paths"]["/api/microsoft365/emails/search"]["get"]
    assert {param["name"] for param in operation["parameters"]} == {
        "q",
        "limit",
        "offset",
    }


# Finance ma od 19.08 pelny dostep operacyjny (user_can_access_candidate_domain
# przepuszcza) — jedyna nieuprawniona persona to wycofywany viewer `user`.
@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_oauth_callback_rechecks_role_before_token_exchange(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A role change while Microsoft consent is open must close reconnect."""

    db = AsyncMock()
    db.get.return_value = _user(role)
    exchange_code = AsyncMock()
    monkeypatch.setattr(
        microsoft365.m365_oauth,
        "verify_state",
        MagicMock(return_value=(37, "pkce-verifier")),
    )
    monkeypatch.setattr(microsoft365.m365_oauth, "exchange_code", exchange_code)

    response = await microsoft365.callback.__wrapped__(
        request=MagicMock(),
        code="authorization-code",
        state="signed-state",
        error=None,
        error_description=None,
        db=db,
    )

    assert response.status_code == 302
    assert "status=error" in response.headers["location"]
    exchange_code.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.parametrize("role", [UserRole.user])
@pytest.mark.asyncio
async def test_webhook_sync_rechecks_connection_owner_role(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stale Graph subscription cannot revive sync after a role cutover."""

    connection = SimpleNamespace(id=81, user_id=37, is_active=True)
    owner = _user(role)
    db = AsyncMock()

    async def _get(model, row_id, **_kwargs):
        if model is M365Connection and row_id == connection.id:
            return connection
        if model is User and row_id == owner.id:
            return owner
        return None

    db.get.side_effect = _get

    @asynccontextmanager
    async def _session():
        yield db

    sync_connection = AsyncMock()
    monkeypatch.setattr(microsoft365, "AsyncSessionLocal", _session)
    monkeypatch.setattr(microsoft365, "sync_connection", sync_connection)

    await microsoft365._webhook_dispatch_sync(connection.id)

    sync_connection.assert_not_awaited()


@pytest.mark.asyncio
async def test_webhook_sync_still_allows_operational_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = SimpleNamespace(id=82, user_id=37, is_active=True)
    owner = _user(UserRole.recruiter)
    db = AsyncMock()

    async def _get(model, row_id, **_kwargs):
        if model is M365Connection and row_id == connection.id:
            return connection
        if model is User and row_id == owner.id:
            return owner
        return None

    db.get.side_effect = _get

    @asynccontextmanager
    async def _session():
        yield db

    sync_connection = AsyncMock()
    monkeypatch.setattr(microsoft365, "AsyncSessionLocal", _session)
    monkeypatch.setattr(microsoft365, "sync_connection", sync_connection)

    await microsoft365._webhook_dispatch_sync(connection.id)

    sync_connection.assert_awaited_once_with(db, connection)
