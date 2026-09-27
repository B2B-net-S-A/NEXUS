"""Runda 9 (R9-X1-5): import iCal nie trzyma pętli zdarzeń.

``Calendar.from_ical`` (kanał do 5 MiB) i jeden flush tysięcy wierszy biegły
na pętli jedynego procesu uvicorna, a trasa nie miała limitu wywołań.
"""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import ical_import as ii

_APP = Path(__file__).resolve().parents[1] / "app"


def _feed(count: int) -> bytes:
    start = (datetime.now(timezone.utc) + timedelta(days=3)).strftime("%Y%m%dT%H%M%SZ")
    events = "".join(
        f"BEGIN:VEVENT\r\nUID:r9-{i}\r\nSUMMARY:Spotkanie {i}\r\n"
        f"DTSTART:{start}\r\nEND:VEVENT\r\n"
        for i in range(count)
    )
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//t//t//\r\n"
        f"{events}END:VCALENDAR\r\n"
    ).encode()


def _db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()
    db.scalar.return_value = None
    return db


@pytest.mark.asyncio
async def test_feed_is_parsed_off_the_event_loop(monkeypatch) -> None:
    monkeypatch.setattr(ii, "_fetch_ical_safely", AsyncMock(return_value=_feed(2)))
    threaded: list[object] = []
    real_to_thread = ii.asyncio.to_thread

    async def spy(func, *args, **kwargs):
        threaded.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(ii.asyncio, "to_thread", spy)
    res = await ii.import_ical_url(_db(), "https://cal.example.com/x.ics", creator_id=1)

    assert res.inserted == 2, res.as_dict()
    assert ii._parse_feed in threaded


@pytest.mark.asyncio
async def test_events_are_committed_in_batches(monkeypatch) -> None:
    monkeypatch.setattr(ii, "_fetch_ical_safely", AsyncMock(return_value=_feed(450)))
    monkeypatch.setattr(ii, "_COMMIT_BATCH", 200)
    db = _db()

    res = await ii.import_ical_url(db, "https://cal.example.com/x.ics", creator_id=1)

    assert res.inserted == 450
    assert db.commit.await_count == 3  # 200 + 200 + 50


@pytest.mark.asyncio
async def test_failed_batch_is_not_counted_and_does_not_stop_the_import(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ii, "_fetch_ical_safely", AsyncMock(return_value=_feed(450)))
    monkeypatch.setattr(ii, "_COMMIT_BATCH", 200)
    db = _db()
    db.commit.side_effect = [None, RuntimeError("unique"), None]

    res = await ii.import_ical_url(db, "https://cal.example.com/x.ics", creator_id=1)

    assert res.inserted == 250
    assert res.errors == 1
    assert res.error_samples == ["commit: RuntimeError"]
    db.rollback.assert_awaited_once()


@pytest.mark.asyncio
async def test_unparseable_feed_reports_error_without_contents(monkeypatch) -> None:
    monkeypatch.setattr(
        ii, "_fetch_ical_safely", AsyncMock(return_value=b"\x00 not a calendar")
    )
    res = await ii.import_ical_url(_db(), "https://cal.example.com/x.ics", creator_id=1)

    assert res.errors == 1
    assert res.error_samples[0].startswith("parse: ")


def test_import_route_is_rate_limited() -> None:
    source = (_APP / "api" / "calendar.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    # slowapi + PEP 563 zamienia parametry w QUERY (slowapi #579).
    assert "from __future__ import annotations" not in source
    route = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "import_ical"
    )
    decorators = [ast.unparse(d) for d in route.decorator_list]
    assert any(d.startswith("limiter.limit(") for d in decorators), decorators
    assert "user_or_ip_key" in " ".join(decorators)
    assert route.args.args[0].arg == "request"
