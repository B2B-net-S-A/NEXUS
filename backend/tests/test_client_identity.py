"""Shared client-name and lifecycle visibility contracts."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql

import app.models.skill  # noqa: F401  (register relationship target)
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
