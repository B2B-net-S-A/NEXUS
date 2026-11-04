"""A Teams follow-up creates one invite and persists its transcript in NEXUS."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent
from app.models.candidate import Candidate, CandidateStatus
from app.models.followup_meeting import FollowupMeeting
from app.models.user import User, UserRole
from app.services import followup_meetings
from app.services.m365 import teams_prep_auth, teams_prep_graph


async def test_invite_is_idempotent_and_transcript_is_stored(monkeypatch) -> None:
    calls: list[dict] = []

    async def create_event(_upn, payload):
        calls.append(payload)
        return teams_prep_graph.CreatedPrepEvent(
            graph_event_id="graph-followup-1",
            change_key="ck1",
            join_url="https://teams.microsoft.com/l/meetup-join/followup",
        )

    async def resolve_user_id(_upn):
        return "aad-user"

    async def find_online_meeting(_user_id, _join_url):
        return "online-meeting-1"

    async def enable_auto_transcription(_user_id, _meeting_id):
        return None

    async def get_event(_upn, _event_id):
        return None

    async def list_transcripts(_user_id, _meeting_id):
        return [teams_prep_graph.TranscriptRef(id="transcript-1", created=None)]

    async def transcript_vtt(_user_id, _meeting_id, _transcript_id):
        return (
            "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n<v Jan Kandydat>Dzień dobry</v>"
        )

    for name, func in (
        ("create_event", create_event),
        ("resolve_user_id", resolve_user_id),
        ("find_online_meeting", find_online_meeting),
        ("enable_auto_transcription", enable_auto_transcription),
        ("get_event", get_event),
        ("list_transcripts", list_transcripts),
        ("transcript_vtt", transcript_vtt),
    ):
        monkeypatch.setattr(teams_prep_graph, name, func)
    monkeypatch.setattr(settings, "TEAMS_PREP_APP_ONLY_ENABLED", True)
    monkeypatch.setattr(settings, "TEAMS_PREP_AUTO_TRANSCRIBE", True)
    monkeypatch.setattr(teams_prep_auth, "credentials_configured", lambda: True)

    tag = uuid.uuid4().hex[:12]
    start = datetime.now(timezone.utc) + timedelta(hours=1)
    end = start + timedelta(minutes=30)
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"followup-{tag}@example.com",
            name="Anna Rekruter",
            role=UserRole.recruiter,
            roles=["recruiter"],
        )
        candidate = Candidate(
            name="Jan",
            lastname="Kandydat",
            email=f"candidate-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([user, candidate])
        await db.flush()
        request_id = f"followup-test-{tag}"
        first = await followup_meetings.create_followup_meeting(
            db,
            candidate=candidate,
            organizer=user,
            start=start,
            end=end,
            client_request_id=request_id,
        )
        await db.commit()
        assert first.transcription_setup == "enabled"
        second = await followup_meetings.create_followup_meeting(
            db,
            candidate=candidate,
            organizer=user,
            start=start,
            end=end,
            client_request_id=request_id,
        )
        assert first.id == second.id
        assert len(calls) == 1
        assert calls[0]["isOnlineMeeting"] is True
        assert "nagrywane" in calls[0]["body"]["content"]
        assert (
            await followup_meetings.fetch_due(db, now=end + timedelta(minutes=30)) == 1
        )
        row = await db.scalar(
            select(FollowupMeeting).where(FollowupMeeting.id == first.id)
        )
        assert row is not None and row.transcript_status == "fetched"
        assert "Dzień dobry" in row.transcript_text
        event = await db.get(CalendarEvent, row.calendar_event_id)
        assert event is not None and event.candidate_id == candidate.id
