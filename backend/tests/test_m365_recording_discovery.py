"""Unit tests for Phase 7.8 — Teams recording discovery via OneDrive.

Two layers:

1. ``app.services.m365.onedrive`` — pure helpers
   (``extract_meeting_id_fragment``, ``_is_recording_candidate``,
   ``_pick_best_match``) and the ``find_meeting_recording`` orchestrator
   driven against an ``AsyncMock`` GraphClient.
2. ``app.tasks.microsoft365_sync._recording_discovery_pass`` — the loop
   body with the SELECT and GraphClient stubbed via ``monkeypatch``.

Same fakes-on-SimpleNamespace pattern as ``test_m365_rematch.py`` so the
suite runs in CI without postgres.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.services.m365.graph_client import GraphRequestError
from app.services.m365.onedrive import (
    _Candidate,
    _is_recording_candidate,
    _pick_best_match,
    extract_meeting_id_fragment,
    find_meeting_recording,
)
from app.tasks import microsoft365_sync as sync_mod
from app.tasks.microsoft365_sync import (
    RecordingDiscoveryStats,
    _recording_discovery_pass,
)


# ── extract_meeting_id_fragment ─────────────────────────────────────────────


def test_extract_meeting_id_handles_typical_teams_url() -> None:
    url = (
        "https://teams.microsoft.com/l/meetup-join/"
        "19%3ameeting_ZjE5OWQwNWUtNjY%40thread.v2/0?context=..."
    )
    fragment = extract_meeting_id_fragment(url)
    assert fragment is not None
    # First 12 chars of the base64 token — long enough to be specific.
    assert fragment == "ZjE5OWQwNWUt"


def test_extract_meeting_id_returns_none_when_no_match() -> None:
    assert extract_meeting_id_fragment("https://example.com/notateams") is None


def test_extract_meeting_id_returns_none_for_empty_or_none() -> None:
    assert extract_meeting_id_fragment(None) is None
    assert extract_meeting_id_fragment("") is None


# ── _is_recording_candidate filter ──────────────────────────────────────────


def _window(end_at: datetime) -> tuple[datetime, datetime]:
    return end_at - timedelta(minutes=30), end_at + timedelta(hours=4)


def _drive_item(
    *,
    name: str = "Recording.mp4",
    web_url: str = "https://onedrive.example/Recording.mp4",
    created_at: str | None = "2026-05-14T11:00:00Z",
    mime: str | None = "video/mp4",
) -> dict[str, Any]:
    item: dict[str, Any] = {"name": name, "webUrl": web_url}
    if created_at is not None:
        item["createdDateTime"] = created_at
    if mime is not None:
        item["file"] = {"mimeType": mime}
    return item


def test_is_recording_candidate_accepts_mp4_inside_window() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    start, end = _window(end_at)
    item = _drive_item()  # created at 11:00 UTC, ends 10:00 → +1h inside window
    candidate = _is_recording_candidate(item, window_start=start, window_end=end)
    assert candidate is not None
    assert candidate.name == "Recording.mp4"
    assert candidate.content_type == "video/mp4"


def test_is_recording_candidate_rejects_non_mp4_suffix() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    start, end = _window(end_at)
    item = _drive_item(name="Notes.docx", mime=None)
    assert _is_recording_candidate(item, window_start=start, window_end=end) is None


def test_is_recording_candidate_rejects_outside_window() -> None:
    """File created a full day after the event end is not the recording."""
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    start, end = _window(end_at)
    item = _drive_item(created_at="2026-05-15T10:00:00Z")  # +24h
    assert _is_recording_candidate(item, window_start=start, window_end=end) is None


def test_is_recording_candidate_accepts_octet_stream_mime() -> None:
    """Some tenants ship ``application/octet-stream`` with ``.mp4`` extension."""
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    start, end = _window(end_at)
    item = _drive_item(mime="application/octet-stream")
    assert _is_recording_candidate(item, window_start=start, window_end=end) is not None


def test_is_recording_candidate_rejects_unknown_mime() -> None:
    """Wrong MIME on a `.mp4`-named file → still reject. Avoids picking up
    a renamed text file or similar misfiled blob."""
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    start, end = _window(end_at)
    item = _drive_item(mime="text/plain")
    assert _is_recording_candidate(item, window_start=start, window_end=end) is None


def test_is_recording_candidate_rejects_missing_created_at() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    start, end = _window(end_at)
    item = _drive_item(created_at=None)
    assert _is_recording_candidate(item, window_start=start, window_end=end) is None


# ── _pick_best_match heuristic ──────────────────────────────────────────────


def _cand(name: str, minutes_after_end: int) -> _Candidate:
    """Helper: build a candidate at `end_at + N min`."""
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    return _Candidate(
        name=name,
        web_url=f"https://onedrive.example/{name}",
        created_at=end_at + timedelta(minutes=minutes_after_end),
        content_type="video/mp4",
    )


def test_pick_best_match_prefers_meeting_id_in_name() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _cand("Recording-meeting_ZjE5OWQwNWUt.mp4", 90),
        _cand("Some other Recording.mp4", 60),  # closer in time but no ID match
    ]
    best = _pick_best_match(
        candidates,
        event_end_at=end_at,
        meeting_id_fragment="ZjE5OWQwNWUt",
    )
    assert best is not None
    assert best.name == "Recording-meeting_ZjE5OWQwNWUt.mp4"


def test_pick_best_match_falls_back_to_closest_by_time() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _cand("Recording-late.mp4", 180),
        _cand("Recording-early.mp4", 45),
    ]
    best = _pick_best_match(
        candidates,
        event_end_at=end_at,
        meeting_id_fragment=None,
    )
    assert best is not None
    assert best.name == "Recording-early.mp4"


def test_pick_best_match_returns_none_for_empty_list() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    assert _pick_best_match([], event_end_at=end_at, meeting_id_fragment=None) is None


def test_pick_best_match_uses_time_when_multiple_id_hits() -> None:
    """ID-matching candidates still need time-ranking — a leftover from an
    earlier re-recorded meeting should NOT beat today's recording."""
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    candidates = [
        _cand("Recording-meeting_XYZ_old.mp4", 220),
        _cand("Recording-meeting_XYZ_fresh.mp4", 30),
    ]
    best = _pick_best_match(
        candidates,
        event_end_at=end_at,
        meeting_id_fragment="meeting_XYZ",
    )
    assert best is not None
    assert best.name == "Recording-meeting_XYZ_fresh.mp4"


# ── find_meeting_recording orchestrator ─────────────────────────────────────


def _gc_with(payload: Any) -> Any:
    """Return a SimpleNamespace exposing an async `get` returning the payload."""
    return SimpleNamespace(get=AsyncMock(return_value=payload))


async def test_find_meeting_recording_picks_match_via_meeting_id() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    gc = _gc_with(
        {
            "value": [
                _drive_item(
                    name="Recording-meeting_ABCDEFGHIJKL.mp4",
                    web_url="https://onedrive/Recording-meeting_ABCDEFGHIJKL.mp4",
                    created_at="2026-05-14T10:45:00Z",
                ),
                _drive_item(
                    name="Recording-other.mp4",
                    web_url="https://onedrive/other.mp4",
                    created_at="2026-05-14T10:30:00Z",
                ),
            ]
        }
    )
    url = await find_meeting_recording(
        gc,
        online_meeting_url=(
            "https://teams.microsoft.com/l/meetup-join/"
            "19%3ameeting_ABCDEFGHIJKL%40thread.v2/0"
        ),
        event_end_at=end_at,
    )
    assert url == "https://onedrive/Recording-meeting_ABCDEFGHIJKL.mp4"


async def test_find_meeting_recording_returns_none_when_no_value() -> None:
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    gc = _gc_with({"value": []})
    assert (
        await find_meeting_recording(gc, online_meeting_url=None, event_end_at=end_at)
        is None
    )


async def test_find_meeting_recording_returns_none_on_graph_error() -> None:
    """403 / 404 from Graph (Files.Read missing, OneDrive not provisioned)
    must not crash the loop — log and return None so the loop retries later."""
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    gc = SimpleNamespace(get=AsyncMock(side_effect=GraphRequestError(403, "forbidden")))
    assert (
        await find_meeting_recording(gc, online_meeting_url=None, event_end_at=end_at)
        is None
    )


async def test_find_meeting_recording_rejects_naive_event_end() -> None:
    naive = datetime(2026, 5, 14, 10, 0)  # tz-less
    gc = _gc_with({"value": []})
    assert (
        await find_meeting_recording(
            gc, online_meeting_url=None, event_end_at=naive
        )
        is None
    )
    gc.get.assert_not_called()


async def test_find_meeting_recording_falls_back_to_time_when_no_id() -> None:
    """No meeting URL → no fragment → fall back to closest by time."""
    end_at = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    gc = _gc_with(
        {
            "value": [
                _drive_item(
                    name="Recording-distant.mp4",
                    web_url="https://onedrive/distant.mp4",
                    created_at="2026-05-14T13:30:00Z",
                ),
                _drive_item(
                    name="Recording-close.mp4",
                    web_url="https://onedrive/close.mp4",
                    created_at="2026-05-14T10:20:00Z",
                ),
            ]
        }
    )
    url = await find_meeting_recording(
        gc, online_meeting_url=None, event_end_at=end_at
    )
    assert url == "https://onedrive/close.mp4"


# ── _recording_discovery_pass loop body ─────────────────────────────────────


def _make_event(
    *,
    eid: int = 1,
    user_id: int | None = 1,
    online_meeting_url: str | None = "https://teams.microsoft.com/l/meetup-join/19%3ameeting_TOKEN%40thread.v2/0",
    end_time: datetime | None = None,
) -> SimpleNamespace:
    """Minimal stand-in for the CalendarEvent model."""
    return SimpleNamespace(
        id=eid,
        created_by=user_id,
        online_meeting_url=online_meeting_url,
        recording_url=None,
        recording_discovered_at=None,
        end_time=end_time
        or (datetime.now(timezone.utc) - timedelta(hours=2)),
    )


def _make_db(rows: list[Any]) -> SimpleNamespace:
    """Fake AsyncSession whose execute() returns the rows for the SELECT, then
    scalar_one_or_none() returns one of the rows for the user-conn lookup.

    The implementation calls ``db.execute`` twice (once for the events SELECT,
    once for the per-user connection SELECT). We side_effect through both with
    a queue of return values so tests can independently shape each call.
    """
    events_scalars = SimpleNamespace(all=lambda: rows)
    events_result = SimpleNamespace(scalars=lambda: events_scalars)
    return SimpleNamespace(
        execute=AsyncMock(return_value=events_result),
        commit=AsyncMock(),
        rollback=AsyncMock(),
    )


async def test_recording_discovery_pass_empty_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _make_db([])
    stats = await _recording_discovery_pass(db)
    assert stats == RecordingDiscoveryStats(processed=0, matched=0)
    db.commit.assert_not_called()


async def test_recording_discovery_pass_marks_scanned_even_when_unmatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`recording_url` stays None when Graph returns no recording, but
    `recording_discovered_at` MUST be set so the next pass deprioritises this
    row instead of re-scanning it every tick."""
    event = _make_event(eid=10)
    db = _make_db([event])

    # Stub the per-user connection lookup → fake live connection.
    fake_conn = SimpleNamespace(id=99, user_id=1, is_active=True)
    monkeypatch.setattr(
        sync_mod,
        "_active_connection_for_user",
        AsyncMock(return_value=fake_conn),
    )

    # Stub GraphClient context manager + find_meeting_recording.
    class _FakeGC:
        async def __aenter__(self) -> "_FakeGC":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(sync_mod, "GraphClient", lambda *_args, **_kw: _FakeGC())
    monkeypatch.setattr(
        sync_mod,
        "find_meeting_recording",
        AsyncMock(return_value=None),
    )

    stats = await _recording_discovery_pass(db)

    assert stats.processed == 1
    assert stats.matched == 0
    assert event.recording_url is None
    assert event.recording_discovered_at is not None
    assert event.recording_discovered_at.tzinfo == timezone.utc
    db.commit.assert_awaited_once()


async def test_recording_discovery_pass_persists_url_when_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = _make_event(eid=20)
    db = _make_db([event])

    monkeypatch.setattr(
        sync_mod,
        "_active_connection_for_user",
        AsyncMock(return_value=SimpleNamespace(id=99, user_id=1, is_active=True)),
    )

    class _FakeGC:
        async def __aenter__(self) -> "_FakeGC":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(sync_mod, "GraphClient", lambda *_args, **_kw: _FakeGC())
    monkeypatch.setattr(
        sync_mod,
        "find_meeting_recording",
        AsyncMock(return_value="https://onedrive/Recording-meeting_TOKEN12345.mp4"),
    )

    stats = await _recording_discovery_pass(db)

    assert stats.processed == 1
    assert stats.matched == 1
    assert event.recording_url == "https://onedrive/Recording-meeting_TOKEN12345.mp4"
    assert event.recording_discovered_at is not None
    db.commit.assert_awaited_once()


async def test_recording_discovery_pass_skips_event_without_organiser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Event with `created_by=None` (e.g. an iCal import) has no OneDrive to
    scan — skip it entirely without consulting Graph."""
    event = _make_event(eid=30, user_id=None)
    db = _make_db([event])

    spy = AsyncMock()
    monkeypatch.setattr(sync_mod, "_active_connection_for_user", spy)

    stats = await _recording_discovery_pass(db)

    assert stats == RecordingDiscoveryStats(processed=0, matched=0)
    spy.assert_not_called()


async def test_recording_discovery_pass_skips_when_no_active_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Organiser disconnected M365 → leave the event alone so reconnecting
    later picks it up automatically. No partial state on the row."""
    event = _make_event(eid=40)
    db = _make_db([event])

    monkeypatch.setattr(
        sync_mod,
        "_active_connection_for_user",
        AsyncMock(return_value=None),
    )

    stats = await _recording_discovery_pass(db)

    assert stats == RecordingDiscoveryStats(processed=0, matched=0)
    assert event.recording_discovered_at is None  # untouched
    db.commit.assert_not_called()


async def test_recording_discovery_pass_continues_when_graph_helper_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash on event N must not poison events N+1..N+k for the same
    organiser — we want batch resilience, not all-or-nothing."""
    e1 = _make_event(eid=51)
    e2 = _make_event(eid=52)
    db = _make_db([e1, e2])

    monkeypatch.setattr(
        sync_mod,
        "_active_connection_for_user",
        AsyncMock(return_value=SimpleNamespace(id=99, user_id=1, is_active=True)),
    )

    class _FakeGC:
        async def __aenter__(self) -> "_FakeGC":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

    monkeypatch.setattr(sync_mod, "GraphClient", lambda *_args, **_kw: _FakeGC())

    calls = {"n": 0}

    async def flaky(
        gc: Any, *, online_meeting_url: Any, event_end_at: Any
    ) -> str | None:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated Graph blowup")
        return "https://onedrive/Recording-good.mp4"

    monkeypatch.setattr(sync_mod, "find_meeting_recording", flaky)

    stats = await _recording_discovery_pass(db)

    assert stats.processed == 2
    assert stats.matched == 1
    # First event crashed → no URL but also no scanned marker (since the
    # marker write is reached only after the helper returns cleanly).
    assert e1.recording_url is None
    assert e1.recording_discovered_at is None
    # Second event succeeded.
    assert e2.recording_url == "https://onedrive/Recording-good.mp4"
    assert e2.recording_discovered_at is not None


async def test_recording_discovery_pass_select_filters_match_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pin the SELECT WHERE clause: online_meeting_url IS NOT NULL,
    recording_url IS NULL, end_time inside the window."""
    db = _make_db([])
    await _recording_discovery_pass(db)
    db.execute.assert_awaited()
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "calendar_events.online_meeting_url IS NOT NULL" in sql
    assert "calendar_events.recording_url IS NULL" in sql
    assert "calendar_events.end_time IS NOT NULL" in sql
