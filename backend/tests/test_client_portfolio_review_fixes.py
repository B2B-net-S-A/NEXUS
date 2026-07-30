"""Regression tests for review findings on the client portfolio foundation."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.models.skill  # noqa: F401  (register relationship target)
from app.models.client import Client, ClientStatus
from app.services.client_portfolio_import import (
    ClientPortfolioImportError,
    _candidate_excluded_client_count,
    _direct_client_fk_counts,
    _merge_kir,
)


def _session_for(dialect_name: str) -> AsyncMock:
    session = AsyncMock(spec=AsyncSession)
    session.get_bind = MagicMock(
        return_value=SimpleNamespace(
            dialect=SimpleNamespace(name=dialect_name),
        )
    )
    return session


@pytest.mark.asyncio
async def test_postgres_fk_inventory_uses_async_session_get_bind() -> None:
    session = _session_for("postgresql")
    result = MagicMock()
    result.all.return_value = []
    session.execute.return_value = result

    assert await _direct_client_fk_counts(session, 17) == []

    session.get_bind.assert_called()
    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_postgres_candidate_exclusion_count_stays_in_sql() -> None:
    session = _session_for("postgresql")
    session.scalar.return_value = 3

    assert await _candidate_excluded_client_count(session, 17) == 3

    session.scalar.assert_awaited_once()
    session.execute.assert_not_awaited()
    compiled = str(session.scalar.await_args.args[0])
    assert "@>" in compiled
    assert "count(" in compiled.lower()


@pytest.mark.asyncio
async def test_kir_merge_rejects_a_target_that_is_itself_merged() -> None:
    source = Client(
        id=1,
        name="KIR",
        status=ClientStatus.active,
        hidden=False,
        external_source="manual",
    )
    target = Client(
        id=2,
        name="Krajowa Izba Rozliczeń",
        status=ClientStatus.active,
        hidden=False,
        external_source="manual",
        merged_into_client_id=3,
    )
    session = _session_for("postgresql")
    result = MagicMock()
    result.scalars.return_value.all.return_value = [source, target]
    session.execute.return_value = result

    with pytest.raises(ClientPortfolioImportError, match="target is itself merged"):
        await _merge_kir(
            session,
            source_id=source.id,
            target_id=target.id,
            expected_source_updated_at=None,
            expected_target_updated_at=None,
            archived_by=None,
        )
