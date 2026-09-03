"""Unit tests for `app.tasks.microsoft365_sync._rematch_pass` and helpers.

Pure helpers — the SELECT and matcher.match calls are stubbed via monkeypatch
so the suite runs in CI without postgres. The DB session is a SimpleNamespace
with AsyncMock for `execute` and `commit`.

Behaviour we pin (Phase 5.2 — backfill candidate matcher):
- emails outside the look-back window are filtered server-side (we assert the
  cutoff lands inside the WHERE clause indirectly by inspecting the query).
- a matched email is UPDATED in-place: candidate_id, match_method,
  match_confidence, matched_at.
- an unmatched result leaves the row alone (no churn).
- a single iteration commits only when at least one row was matched.
- `_addresses` extracts only the `address` keys from the JSONB shape.
"""

from __future__ import annotations

from datetime import timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.models.m365 import EmailMatchMethod
from app.models.section_permission import (
    RoleSectionPermission,
    UserSectionOverride,
)
from app.models.user import User, UserRole
from app.services.m365.provider import MatchResult
from app.services.section_permissions import DEFAULT_ROLE_SECTION_ACCESS
from app.tasks import microsoft365_sync as rematch_mod
from app.tasks.microsoft365_sync import RematchStats, _addresses, _rematch_pass


# ── _addresses helper ───────────────────────────────────────────────────────


def test_addresses_extracts_address_keys() -> None:
    raw = [{"address": "a@example.com", "name": "A"}, {"address": "b@example.com"}]
    assert _addresses(raw) == ["a@example.com", "b@example.com"]


def test_addresses_drops_entries_without_address() -> None:
    raw = [{"name": "no-addr"}, {"address": ""}, {"address": "ok@x.com"}]
    assert _addresses(raw) == ["ok@x.com"]


def test_addresses_handles_none_and_non_list() -> None:
    assert _addresses(None) == []
    assert _addresses("nope") == []
    assert _addresses({}) == []


# ── _rematch_pass ───────────────────────────────────────────────────────────


def _make_email(
    *,
    eid: int,
    from_address: str = "jan@b2bnet.pl",
    subject: str | None = "Re: CV",
    conversation_id: str = "AAAA",
    to_addresses: list[dict[str, Any]] | None = None,
    cc_addresses: list[dict[str, Any]] | None = None,
    owner_role: UserRole = UserRole.recruiter,
) -> SimpleNamespace:
    """Minimal stand-in for the Email model — only fields _rematch_pass touches."""
    owner = User(
        id=1000 + eid,
        email=f"rematch-{eid}-{owner_role.value}@example.com",
        name="Rematch owner",
        role=owner_role,
        roles=[owner_role.value],
        is_active=True,
    )
    return SimpleNamespace(
        id=eid,
        user_id=owner.id,
        user=owner,
        from_address=from_address,
        subject=subject,
        m365_conversation_id=conversation_id,
        to_addresses=to_addresses or [],
        cc_addresses=cc_addresses or [],
        # Mutable fields the helper writes back into:
        candidate_id=None,
        match_method=EmailMatchMethod.unmatched,
        match_confidence=None,
        matched_at=None,
    )


# Finance ma od 19.08 dostęp do domeny kandydackiej (pełny dostęp operacyjny)
# — jedyną pomijaną skrzynką zostaje wycofywany viewer `user`.
@pytest.mark.parametrize("role", [UserRole.user])
async def test_rematch_pass_skips_ineligible_mailbox_owner(
    role: UserRole,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    email = _make_email(eid=77, owner_role=role)
    db = _make_db([email])
    matcher = AsyncMock()
    monkeypatch.setattr(rematch_mod.matcher_mod, "match", matcher)

    stats = await _rematch_pass(db)

    assert stats == RematchStats(processed=0, matched=0)
    matcher.assert_not_awaited()
    db.commit.assert_not_awaited()


def _make_db(emails: list[SimpleNamespace]) -> SimpleNamespace:
    """Build a fake AsyncSession whose execute() returns the given emails."""
    scalars_obj = SimpleNamespace(all=lambda: emails)
    result_obj = SimpleNamespace(scalars=lambda: scalars_obj)
    owners = {email.user_id: email.user for email in emails}
    role_rows = [
        RoleSectionPermission(
            role=role.value,
            section=section.value,
            access=access.name,
        )
        for role, policy in DEFAULT_ROLE_SECTION_ACCESS.items()
        for section, access in policy.items()
    ]

    async def _get(model: Any, row_id: int, **_kwargs: Any) -> Any:
        if model is User:
            return owners.get(row_id)
        return None

    async def _scalars(statement: Any) -> SimpleNamespace:
        entity = statement.column_descriptions[0].get("entity")
        rows = role_rows if entity is RoleSectionPermission else []
        assert entity in {RoleSectionPermission, UserSectionOverride}
        return SimpleNamespace(all=lambda: rows)

    return SimpleNamespace(
        execute=AsyncMock(return_value=result_obj),
        scalars=AsyncMock(side_effect=_scalars),
        get=AsyncMock(side_effect=_get),
        commit=AsyncMock(),
    )


async def test_rematch_pass_links_matched_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A matcher hit must update candidate_id + method + confidence + matched_at."""
    email = _make_email(eid=1, from_address="jan@b2bnet.pl")
    db = _make_db([email])

    fake_match = AsyncMock(
        return_value=MatchResult(
            candidate_id=42,
            method=EmailMatchMethod.strict.value,
            confidence=1.0,
        )
    )
    monkeypatch.setattr(rematch_mod.matcher_mod, "match", fake_match)

    stats = await _rematch_pass(db)

    assert isinstance(stats, RematchStats)
    assert stats.processed == 1
    assert stats.matched == 1
    assert email.candidate_id == 42
    assert email.match_method == EmailMatchMethod.strict
    assert email.match_confidence == 1.0
    assert email.matched_at is not None and email.matched_at.tzinfo == timezone.utc
    db.commit.assert_awaited_once()


async def test_rematch_pass_skips_when_matcher_returns_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`candidate_id=None` from matcher → row unchanged, no commit."""
    email = _make_email(eid=2)
    db = _make_db([email])

    fake_match = AsyncMock(
        return_value=MatchResult(
            candidate_id=None,
            method=EmailMatchMethod.unmatched.value,
            confidence=None,
        )
    )
    monkeypatch.setattr(rematch_mod.matcher_mod, "match", fake_match)

    stats = await _rematch_pass(db)

    assert stats.processed == 1
    assert stats.matched == 0
    assert email.candidate_id is None
    assert email.match_method == EmailMatchMethod.unmatched
    db.commit.assert_not_called()


async def test_rematch_pass_mixed_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """Two matches + one miss → processed=3, matched=2, single commit at the end."""
    e1 = _make_email(eid=1, from_address="a@b.com")
    e2 = _make_email(eid=2, from_address="c@d.com")
    e3 = _make_email(eid=3, from_address="e@f.com")
    db = _make_db([e1, e2, e3])

    results = iter(
        [
            MatchResult(candidate_id=10, method="strict", confidence=1.0),
            MatchResult(candidate_id=None, method="unmatched", confidence=None),
            MatchResult(candidate_id=11, method="smart_domain", confidence=0.7),
        ]
    )
    fake_match = AsyncMock(side_effect=lambda db, msg: next(results))
    monkeypatch.setattr(rematch_mod.matcher_mod, "match", fake_match)

    stats = await _rematch_pass(db)

    assert stats.processed == 3
    assert stats.matched == 2
    assert e1.candidate_id == 10
    assert e1.match_method == EmailMatchMethod.strict
    assert e2.candidate_id is None  # unchanged
    assert e3.candidate_id == 11
    assert e3.match_method == EmailMatchMethod.smart_domain
    # One commit covers both updates — batched I/O, not per-row.
    db.commit.assert_awaited_once()


async def test_rematch_pass_empty_batch_does_not_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing to do → no matcher calls, no commit."""
    db = _make_db([])
    fake_match = AsyncMock()
    monkeypatch.setattr(rematch_mod.matcher_mod, "match", fake_match)

    stats = await _rematch_pass(db)

    assert stats == RematchStats(processed=0, matched=0)
    fake_match.assert_not_called()
    db.commit.assert_not_called()


async def test_rematch_pass_query_filters_by_lookback_and_unmatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the SELECT WHERE clause: unmatched + candidate_id IS NULL + received_at cutoff.

    Inspecting the rendered SQL is brittle, but checking the compiled WHERE
    clauses prevents accidental regression of either filter — the most likely
    way to break this loop is to forget the `match_method=unmatched` guard and
    overwrite manually-linked rows.
    """
    db = _make_db([])
    monkeypatch.setattr(
        rematch_mod.matcher_mod,
        "match",
        AsyncMock(),
    )

    await _rematch_pass(db)

    db.execute.assert_awaited_once()
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "emails.candidate_id IS NULL" in sql
    assert "emails.match_method" in sql
    assert "emails.received_at >" in sql


async def test_rematch_pass_skips_row_on_unknown_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensive guard: matcher returning a method string not in EmailMatchMethod
    must NOT crash the pass and must NOT corrupt the email row."""
    email = _make_email(eid=99)
    db = _make_db([email])

    fake_match = AsyncMock(
        return_value=MatchResult(
            candidate_id=7, method="totally_made_up", confidence=0.5
        )
    )
    monkeypatch.setattr(rematch_mod.matcher_mod, "match", fake_match)

    stats = await _rematch_pass(db)

    assert stats.processed == 1
    assert stats.matched == 0
    assert email.candidate_id is None
    assert email.match_method == EmailMatchMethod.unmatched
    db.commit.assert_not_called()


async def test_rematch_pass_continues_when_matcher_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single matcher failure on row N must not poison rows N+1..N+k."""
    e1 = _make_email(eid=1, from_address="boom@x.com")
    e2 = _make_email(eid=2, from_address="ok@y.com")
    db = _make_db([e1, e2])

    async def side_effect(db: Any, msg: Any) -> MatchResult:
        if msg.from_address == "boom@x.com":
            raise RuntimeError("graph timeout — simulated")
        return MatchResult(candidate_id=5, method="strict", confidence=1.0)

    monkeypatch.setattr(
        rematch_mod.matcher_mod, "match", AsyncMock(side_effect=side_effect)
    )

    stats = await _rematch_pass(db)

    assert stats.processed == 2
    assert stats.matched == 1
    assert e1.candidate_id is None  # crashed row left intact
    assert e2.candidate_id == 5
    db.commit.assert_awaited_once()


async def test_rematch_pass_uses_email_address_jsonb_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """to_addresses/cc_addresses are JSONB with {address, name} dicts — we feed
    only the address strings into IncomingMessage."""
    email = _make_email(
        eid=1,
        from_address="from@x.com",
        to_addresses=[{"address": "to@x.com", "name": "T"}],
        cc_addresses=[{"address": "cc@x.com"}],
    )
    db = _make_db([email])

    seen: dict[str, Any] = {}

    async def capture(db: Any, msg: Any) -> MatchResult:
        seen["from_address"] = msg.from_address
        seen["to_addresses"] = list(msg.to_addresses)
        seen["cc_addresses"] = list(msg.cc_addresses)
        return MatchResult(candidate_id=None, method="unmatched", confidence=None)

    monkeypatch.setattr(
        rematch_mod.matcher_mod, "match", AsyncMock(side_effect=capture)
    )

    await _rematch_pass(db)

    assert seen["from_address"] == "from@x.com"
    assert seen["to_addresses"] == ["to@x.com"]
    assert seen["cc_addresses"] == ["cc@x.com"]
