"""Runda 9 (R9-N10-8): dopasowanie kandydata po adresie bez wielkości liter."""

from __future__ import annotations

import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from app.core.config import settings
from app.services.m365 import matcher, sync


def _sql(stmt) -> str:
    return str(
        stmt.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


@pytest.fixture(autouse=True)
def _company_domain(monkeypatch):
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "b2bnetwork.pl")


async def test_strict_email_match_compares_lowercased_trimmed_column() -> None:
    captured = []
    stored = SimpleNamespace(id=5, email=" Jan.Kowalski@Example.com")

    async def _execute(stmt):
        captured.append(stmt)
        return SimpleNamespace(
            scalars=lambda: SimpleNamespace(all=lambda: [stored])
        )

    db = SimpleNamespace(execute=AsyncMock(side_effect=_execute))
    found = await matcher._find_candidate_by_email(
        db, ["JAN.kowalski@example.com"], owner_address="rek@b2bnetwork.pl"
    )

    assert found is stored
    sql = _sql(captured[0]).lower()
    assert "lower(trim(candidates.email)) in ('jan.kowalski@example.com')" in sql


def test_calendar_attendee_match_is_case_insensitive() -> None:
    source = inspect.getsource(sync)
    assert "Candidate.email.in_(addrs)" not in source
    assert "func.lower(func.trim(Candidate.email)).in_(addrs)" in source
