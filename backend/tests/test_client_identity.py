"""Shared client-name and lifecycle visibility contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import app.models.skill  # noqa: F401  (register relationship target)
from app.api.clients import _merged_client_redirect
from app.api.my_clients import client_dashboard
from app.models.client import Client, ClientStatus
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
    is_client_visible,
    resolve_visible_client,
    visible_client_predicates,
)


def _client(client_id: int, name: str, **values) -> Client:
    client = Client(
        name=name,
        status=ClientStatus.active,
        **values,
    )
    client.id = client_id
    return client


def test_shared_selector_prefers_display_name_and_filters_lifecycle() -> None:
    client = _client(1, "Source name", display_name="  Friendly name  ")

    assert client_display_name(client) == "Friendly name"

    statement = select(
        Client.id,
        client_display_name_expression().label("effective_name"),
    ).where(*visible_client_predicates())
    sql = str(statement.compile(dialect=postgresql.dialect())).lower()

    assert "coalesce" in sql
    assert "clients.hidden is false" in sql
    assert "clients.archived_at is null" in sql
    assert "clients.merged_into_client_id is null" in sql


@pytest.mark.asyncio
async def test_merge_redirect_resolves_only_a_visible_canonical_client() -> None:
    duplicate = _client(
        11,
        "Duplicate",
        hidden=True,
        archived_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        merged_into_client_id=12,
    )
    canonical = _client(12, "Canonical", display_name="Canonical display")
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[duplicate, canonical]))

    resolved = await resolve_visible_client(db, duplicate.id, follow_merge=True)

    assert resolved is canonical
    assert is_client_visible(resolved)
    assert client_display_name(resolved) == "Canonical display"


@pytest.mark.asyncio
async def test_broken_or_hidden_merge_target_fails_closed() -> None:
    duplicate = _client(
        21,
        "Duplicate",
        hidden=True,
        archived_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        merged_into_client_id=22,
    )
    hidden_target = _client(22, "Hidden target", hidden=True)
    db = SimpleNamespace(scalar=AsyncMock(side_effect=[duplicate, hidden_target]))

    assert await resolve_visible_client(db, duplicate.id, follow_merge=True) is None


def test_merged_client_api_redirect_is_temporary_for_supported_rollback() -> None:
    duplicate = _client(
        31,
        "Duplicate",
        hidden=True,
        archived_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        merged_into_client_id=32,
    )

    response = _merged_client_redirect(duplicate, suffix="/contacts")

    assert response is not None
    assert response.status_code == 307
    assert response.headers["location"] == "/api/clients/32/contacts"
    assert response.headers["X-Merged-From-Client-Id"] == "31"


@pytest.mark.asyncio
async def test_dashboard_merge_redirect_is_temporary_for_supported_rollback() -> None:
    duplicate = _client(
        41,
        "Duplicate",
        hidden=True,
        archived_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        merged_into_client_id=42,
    )
    canonical = _client(42, "Canonical")
    db = SimpleNamespace(
        scalar=AsyncMock(side_effect=[duplicate, duplicate, canonical])
    )

    response = await client_dashboard(
        client_id=duplicate.id,
        user=SimpleNamespace(),
        db=db,
    )

    assert response.status_code == 307
    assert response.headers["location"] == "/api/my-clients/42/dashboard"
    assert response.headers["X-Merged-From-Client-Id"] == "41"
