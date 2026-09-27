"""Runda 9 (R9-N10-13): rematch przechodzi przez całe okno, nie w kółko te same maile."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.config import settings
from app.models.app_setting import AppSetting
from app.tasks import microsoft365_sync as rematch_mod


def _email(eid: int, minutes_ago: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=eid,
        user_id=1,
        received_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    )


def _db(emails, setting_row=None):
    result = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: emails))

    async def _get(model, key, **_kw):
        return setting_row if model is AppSetting else None

    return SimpleNamespace(
        execute=AsyncMock(return_value=result),
        get=AsyncMock(side_effect=_get),
        add=MagicMock(),
        commit=AsyncMock(),
    )


@pytest.fixture(autouse=True)
def _skip_owners(monkeypatch):
    monkeypatch.setattr(rematch_mod, "eligible_m365_owner", AsyncMock(return_value=None))
    monkeypatch.setattr(settings, "M365_REMATCH_BATCH_SIZE", 2)


async def test_full_batch_saves_cursor_at_last_row() -> None:
    emails = [_email(10, 1), _email(9, 2)]
    db = _db(emails)

    await rematch_mod._rematch_pass(db)

    saved = db.add.call_args.args[0]
    assert saved.key == rematch_mod.REMATCH_CURSOR_KEY
    assert saved.value["id"] == 9
    db.commit.assert_awaited_once()


async def test_next_pass_continues_below_the_cursor() -> None:
    last = _email(9, 2)
    row = SimpleNamespace(
        value={"received_at": last.received_at.isoformat(), "id": 9}
    )
    db = _db([_email(8, 3)], setting_row=row)

    await rematch_mod._rematch_pass(db)

    sql = str(db.execute.await_args.args[0].compile()).lower()
    assert "(emails.received_at, emails.id) <" in sql
    # Paczka niepełna = koniec okna, następny bieg zaczyna od najnowszych.
    assert row.value == {}
    db.commit.assert_awaited_once()


def test_cursor_outside_lookback_window_is_ignored() -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=30)
    old = {"received_at": (cutoff - timedelta(days=1)).isoformat(), "id": 5}
    assert rematch_mod._parse_rematch_cursor(old, cutoff) is None
    assert rematch_mod._parse_rematch_cursor({"id": "x"}, cutoff) is None
    assert rematch_mod._parse_rematch_cursor(None, cutoff) is None
