"""Unit tests for the Teams-meeting payload contract in m365.calendar.

Phase 7.1 — interview/screening events ask Graph for a Teams join URL by
default; other types stay off. The decision happens in
`_resolve_with_teams`; the payload shape is assembled by
`_build_event_payload`. Both are pure helpers extracted from
`create_event` so we don't need to mock GraphClient + a DB session just
to lock in the request shape.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.models.calendar_event import EventType
from app.services.m365.calendar import (
    _build_event_payload,
    _resolve_with_teams,
)


# ── _resolve_with_teams ──────────────────────────────────────────────────────


def test_resolve_with_teams_explicit_true_wins_for_meeting() -> None:
    """Caller override must beat the event-type default."""
    assert _resolve_with_teams(True, EventType.meeting) is True


def test_resolve_with_teams_explicit_false_wins_for_interview() -> None:
    """Recruiter can opt out of Teams even on an interview."""
    assert _resolve_with_teams(False, EventType.interview) is False


def test_resolve_with_teams_defaults_on_for_interview() -> None:
    assert _resolve_with_teams(None, EventType.interview) is True


def test_resolve_with_teams_defaults_on_for_screening() -> None:
    assert _resolve_with_teams(None, EventType.screening) is True


def test_resolve_with_teams_defaults_off_for_meeting() -> None:
    """Generic meetings stay opt-in — they may be physical or phone."""
    assert _resolve_with_teams(None, EventType.meeting) is False


def test_resolve_with_teams_defaults_off_for_deadline() -> None:
    assert _resolve_with_teams(None, EventType.deadline) is False


# ── _build_event_payload ─────────────────────────────────────────────────────


def _sample_window() -> tuple[datetime, datetime]:
    start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    return start, end


def test_build_event_payload_with_teams_sets_online_meeting_flags() -> None:
    """The two flags are coupled — both go in together or not at all."""
    start, end = _sample_window()
    payload = _build_event_payload(
        title="Interview: Alice",
        description="Talk about backend role.",
        start=start,
        end=end,
        attendee_emails=["alice@example.com"],
        want_teams=True,
    )
    assert payload["isOnlineMeeting"] is True
    assert payload["onlineMeetingProvider"] == "teamsForBusiness"


def test_build_event_payload_without_teams_omits_online_meeting_flags() -> None:
    """Without the flags, Graph does not generate a join URL — preserve that."""
    start, end = _sample_window()
    payload = _build_event_payload(
        title="Deadline: contract signed",
        description="",
        start=start,
        end=end,
        attendee_emails=[],
        want_teams=False,
    )
    assert "isOnlineMeeting" not in payload
    assert "onlineMeetingProvider" not in payload


def test_build_event_payload_attendees_are_required_type() -> None:
    """Every attendee is `required` — Graph defaults to `required` anyway
    but spelling it out keeps the diff readable in Graph traces."""
    start, end = _sample_window()
    payload = _build_event_payload(
        title="Screening",
        description="hi",
        start=start,
        end=end,
        attendee_emails=["a@example.com", "b@example.com"],
        want_teams=True,
    )
    assert payload["attendees"] == [
        {"emailAddress": {"address": "a@example.com"}, "type": "required"},
        {"emailAddress": {"address": "b@example.com"}, "type": "required"},
    ]


def test_build_event_payload_uses_html_body_content_type() -> None:
    """We sanitize and ship the description as HTML — Graph renders it inline
    in the Outlook invite. Plain-text would lose links and formatting."""
    start, end = _sample_window()
    payload = _build_event_payload(
        title="Interview",
        description="<p>Welcome <strong>Alice</strong>.</p>",
        start=start,
        end=end,
        attendee_emails=[],
        want_teams=True,
    )
    body = payload["body"]
    assert body["contentType"] == "HTML"
    # Sanitizer keeps allowed tags; we only assert the bold survives — the
    # exact attribute whitelist is covered in test_html_sanitize.
    assert "<strong>Alice</strong>" in body["content"]


# ── FIX-08 (audyt 22.09 r2): transactionId z identyfikatora okna ─────────────


def test_transaction_id_from_intent_differs_for_identical_content() -> None:
    from app.services.m365.calendar import event_transaction_id

    start = datetime(2026, 9, 23, 10, tzinfo=timezone.utc)
    end = datetime(2026, 9, 23, 11, tzinfo=timezone.utc)
    common = dict(
        owner_user_id=1,
        title="Rozmowa",
        start=start,
        end=end,
        attendee_emails=["a@b.pl"],
    )
    first = event_transaction_id(**common, intent_id="invite-form|1|aaaaaaaa-1")
    second = event_transaction_id(**common, intent_id="invite-form|1|bbbbbbbb-2")
    retry = event_transaction_id(**common, intent_id="invite-form|1|aaaaaaaa-1")
    assert first != second, "drugie identyczne spotkanie Graph uzna za ponowienie"
    assert first == retry


@pytest.mark.asyncio
async def test_invite_endpoint_passes_form_intent_to_graph(monkeypatch) -> None:
    from types import SimpleNamespace

    from app.api import calendar as calendar_api
    from app.services.m365 import calendar as m365_calendar

    captured: dict = {}

    class _Stop(Exception):
        pass

    async def _create(db, conn, **kwargs):  # noqa: ANN001
        captured.update(kwargs)
        raise _Stop()

    async def _scope(*_a, **_kw):  # noqa: ANN002
        return None

    class _Db:
        async def scalar(self, _stmt):  # noqa: ANN001
            return SimpleNamespace(is_active=True, user_id=7)

        async def get(self, _model, _id):  # noqa: ANN001
            return SimpleNamespace(email="kandydat@example.com")

    monkeypatch.setattr(m365_calendar, "create_event", _create)
    monkeypatch.setattr(calendar_api, "_ensure_calendar_job_scope", _scope)
    body = calendar_api.M365InviteRequest(
        candidate_id=1,
        title="Rozmowa",
        start=datetime(2026, 9, 23, 10, tzinfo=timezone.utc),
        end=datetime(2026, 9, 23, 11, tzinfo=timezone.utc),
        client_request_id="abcdef12-3456",
    )
    with pytest.raises(_Stop):
        await calendar_api.create_m365_invite(
            body, current_user=SimpleNamespace(id=7), db=_Db()
        )
    assert captured["intent_id"] == "invite-form|7|abcdef12-3456"

    # Formularz ogólny tworzy też spotkanie Outlook/Teams bez kandydata.
    captured.clear()
    general = calendar_api.M365InviteRequest(
        title="Spotkanie zespołu",
        start=datetime(2026, 9, 23, 10, tzinfo=timezone.utc),
        end=datetime(2026, 9, 23, 11, tzinfo=timezone.utc),
        event_type="meeting",
        invite_candidate=False,
        add_teams_meeting=True,
        extra_attendees=["kolega@example.com"],
        client_request_id="general12-3456",
    )
    with pytest.raises(_Stop):
        await calendar_api.create_m365_invite(
            general, current_user=SimpleNamespace(id=7), db=_Db()
        )
    assert captured["candidate"] is None
    assert captured["extra_attendees"] == ["kolega@example.com"]
    assert captured["with_teams_meeting"] is True
    assert captured["intent_id"] == "invite-form|7|general12-3456"
