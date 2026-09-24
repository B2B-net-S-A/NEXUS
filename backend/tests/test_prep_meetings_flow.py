"""Prepy w Teams (0370) na prawdziwej bazie: zakładanie, transkrypt, ocena, RODO.

Graph jest podmieniony na poziomie ``teams_prep_graph`` (jedyna warstwa, która
rozmawia z Microsoftem), model — na poziomie ``prep_review._call_model``.
Cała reszta (trasy, bramki, zapisy, kolejka, notatka) działa naprawdę.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

import app.models  # noqa: F401
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.security import create_access_token, hash_password
from app.models.calendar_event import CalendarEvent, EventType
from app.models.note import Note
from app.models.prep_meeting import PrepMeeting, PrepReview, PrepTranscript
from app.models.user import User, UserRole
from app.services import prep_review, prep_transcripts
from app.services.m365 import teams_prep_auth, teams_prep_graph
from app.services.m365.graph_client import GraphRequestError


class FakeGraph:
    """Zapis wywołań + sterowane odpowiedzi Grapha."""

    def __init__(self) -> None:
        self.created: list[tuple[str, dict]] = []
        self.transcripts: list[teams_prep_graph.TranscriptRef] = []
        self.vtt = ""
        self.event_state: dict = {}
        self.fail_list_with: int | None = None
        self.patched = 0

    async def create_event(self, upn, payload):
        self.created.append((upn, payload))
        return teams_prep_graph.CreatedPrepEvent(
            graph_event_id=f"g-{uuid.uuid4().hex[:8]}",
            change_key="ck1",
            join_url="https://teams.microsoft.com/l/meetup-join/abc",
        )

    async def resolve_user_id(self, upn):
        return "aad-organizer"

    async def find_online_meeting(self, user_id, join_url):
        return "meeting-1"

    async def enable_auto_transcription(self, user_id, meeting_id):
        self.patched += 1

    async def get_event(self, upn, graph_event_id):
        return self.event_state or None

    async def list_transcripts(self, user_id, meeting_id):
        if self.fail_list_with:
            raise GraphRequestError(self.fail_list_with, {"error": "x"})
        return self.transcripts

    async def transcript_vtt(self, user_id, meeting_id, transcript_id):
        return self.vtt


@pytest.fixture
def graph(monkeypatch):
    fake = FakeGraph()
    for name in (
        "create_event",
        "resolve_user_id",
        "find_online_meeting",
        "enable_auto_transcription",
        "get_event",
        "list_transcripts",
        "transcript_vtt",
    ):
        monkeypatch.setattr(teams_prep_graph, name, getattr(fake, name))
    monkeypatch.setattr(settings, "TEAMS_PREP_APP_ONLY_ENABLED", True)
    monkeypatch.setattr(teams_prep_auth, "credentials_configured", lambda: True)
    return fake


async def _user(role: UserRole, name: str) -> tuple[int, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"prep-{role.value}-{tag}@example.com",
            password_hash=hash_password(f"Prep_{tag}!pw"),
            name=name,
            role=role,
            roles=[role.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        uid = user.id
    token = create_access_token(uid, role.value, roles=[role.value])
    return uid, {"Authorization": f"Bearer {token}"}


async def _pair(*, recruiter_id: int, dl_id: int) -> tuple[int, int]:
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"PrepClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Java Developer {tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=recruiter_id,
            delivery_lead_id=dl_id,
            must_skills=["Kafka", "Kubernetes"],
        )
        cand = Candidate(
            name="Jan",
            lastname=f"Prepowy{tag}",
            email=f"prep-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.client_interview,
                moved_by=recruiter_id,
            )
        )
        await db.commit()
        return job.id, cand.id


def _at(hours: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _create(client: AsyncClient, headers, **body):
    return await client.post("/api/interview-cycle/preps", headers=headers, json=body)


async def test_prep1_is_created_in_the_dl_calendar_with_teams_and_notice(
    app_client: AsyncClient, graph: FakeGraph
):
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl_id, dl_h = await _user(UserRole.delivery_lead, "Kasia Lead")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)

    opts = await app_client.get(
        f"/api/interview-cycle/preps/options?candidate_id={cand_id}&job_id={job_id}",
        headers=rec_h,
    )
    assert opts.status_code == 200, opts.text
    body = opts.json()
    assert body["enabled"] is True
    assert body["suggested"]["1"]["id"] == dl_id
    assert body["suggested"]["2"]["id"] == rec_id

    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(24),
        end=_at(24.75),
        attendee_user_ids=[rec_id],
        client_request_id="req-1",
    )
    assert resp.status_code == 201, resp.text
    out = resp.json()
    assert out["prep_no"] == 1
    assert out["transcription_setup"] == "enabled"
    assert out["transcript_status"] == "waiting"

    upn, payload = graph.created[-1]
    assert upn.startswith("prep-delivery_lead-")
    assert payload["isOnlineMeeting"] is True
    assert payload["onlineMeetingProvider"] == "teamsForBusiness"
    assert payload["transactionId"].startswith("nexus-")
    addresses = [a["emailAddress"]["address"] for a in payload["attendees"]]
    assert any(a.startswith("prep-cand-") for a in addresses)
    assert any(a.startswith("prep-recruiter-") for a in addresses)
    assert "nagrywana i transkrybowana" in payload["body"]["content"]
    # Klient nie trafia do tytułu, który widzi kandydat.
    assert "PrepClient" not in payload["subject"]

    async with AsyncSessionLocal() as db:
        ev = await db.get(CalendarEvent, out["event_id"])
        assert ev.event_type == EventType.prep_call
        assert ev.operational_owner_id == dl_id
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == ev.id)
        )
        assert prep.organizer_aad_id == "aad-organizer"
        assert prep.online_meeting_id == "meeting-1"
        assert prep.scheduled_by_user_id == rec_id

    dup = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(30),
        end=_at(31),
    )
    assert dup.status_code == 409
    assert dup.json()["detail"]["code"] == "PREP_ALREADY_SCHEDULED"


async def test_organizer_outside_the_team_is_rejected(
    app_client: AsyncClient, graph: FakeGraph
):
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola R")
    dl_id, _ = await _user(UserRole.delivery_lead, "Kasia L")
    stranger_id, _ = await _user(UserRole.recruiter, "Obcy R")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)
    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=2,
        organizer_user_id=stranger_id,
        start=_at(24),
        end=_at(25),
    )
    assert resp.status_code == 422, resp.text
    assert graph.created == []


async def test_disabled_integration_answers_503_and_writes_nothing(
    app_client: AsyncClient, graph: FakeGraph, monkeypatch
):
    monkeypatch.setattr(settings, "TEAMS_PREP_APP_ONLY_ENABLED", False)
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola R")
    dl_id, _ = await _user(UserRole.delivery_lead, "Kasia L")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)
    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(24),
        end=_at(25),
    )
    assert resp.status_code == 503
    assert graph.created == []


async def _past_prep(app_client, graph, *, hours_ago: float = 1.0):
    rec_id, rec_h = await _user(UserRole.recruiter, "Ola Rekruter")
    dl_id, _ = await _user(UserRole.delivery_lead, "Kasia Lead")
    job_id, cand_id = await _pair(recruiter_id=rec_id, dl_id=dl_id)
    resp = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(-hours_ago - 0.75),
        end=_at(-hours_ago),
    )
    assert resp.status_code == 201, resp.text
    event_id = resp.json()["event_id"]
    async with AsyncSessionLocal() as db:
        prep = await db.scalar(
            select(PrepMeeting).where(PrepMeeting.calendar_event_id == event_id)
        )
        prep.next_fetch_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        await db.commit()
        return prep.id, event_id, cand_id, rec_h


VTT = """WEBVTT

00:00:00.000 --> 00:05:00.000
<v Kasia Lead>Opowiedz o Kafce i o tym, jak klient pyta o skalowanie.</v>

00:05:00.000 --> 00:20:00.000
<v Jan Prepowy (Gość)>W banku przez dwa lata budowałem integracje na Kafce. Zwiększam liczbę partycji w grupie konsumentów.</v>
"""


async def test_transcript_is_fetched_graded_and_summarised_in_a_note(
    app_client: AsyncClient, graph: FakeGraph, monkeypatch
):
    prep_id, event_id, cand_id, rec_h = await _past_prep(app_client, graph)
    graph.transcripts = [teams_prep_graph.TranscriptRef(id="t1", created="2031")]
    graph.vtt = VTT
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )

    def fake_model(chain, prompt):
        assert "<transcript>" in prompt or "transcript" in prompt
        return json.dumps(
            {
                "summary": "Kandydat opowiedział o Kafce.",
                "must_haves": [
                    {
                        "key": "must:Kafka",
                        "status": "covered",
                        "quote": "budowałem integracje na Kafce",
                    },
                    {"key": "must:Kubernetes", "status": "missing", "quote": None},
                ],
                "client_questions": [],
                "own_projects": {"told": True, "quote": "W banku przez dwa lata"},
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr(prep_review, "_call_model", fake_model)

    async with AsyncSessionLocal() as db:
        stats = await prep_transcripts.run_once(db)
    assert stats.fetched >= 1

    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        assert prep.transcript_status == "fetched"
        tr = await db.scalar(
            select(PrepTranscript).where(PrepTranscript.prep_meeting_id == prep_id)
        )
        assert tr.candidate_seconds == 900 and tr.staff_seconds == 300
        assert float(tr.talk_share) == 0.75
        review = await db.scalar(
            select(PrepReview).where(PrepReview.prep_meeting_id == prep_id)
        )
        assert review.status == "ok"
        # Kubernetes nie omówiony → pokrycie 50% = słaby (próg 50% to OK, poniżej słaby).
        assert float(review.coverage) == 0.5
        assert review.level in ("ok", "weak")
        assert review.remaining == ["Kubernetes"]
        note = await db.get(Note, tr.summary_note_id)
        assert note.candidate_id == cand_id
        assert "Prep 1 — podsumowanie z Teams" in note.content
        assert "Na Prep 2 zostało: Kubernetes" in note.content
        # Notatka nie niesie surowego transkryptu.
        assert "Zwiększam liczbę partycji" not in note.content

    out = await app_client.get(f"/api/interview-cycle/preps/{event_id}", headers=rec_h)
    assert out.status_code == 200, out.text
    assert out.json()["review"]["remaining"] == ["Kubernetes"]
    text = await app_client.get(
        f"/api/interview-cycle/preps/{event_id}/transcript", headers=rec_h
    )
    assert text.status_code == 200
    assert "Zwiększam liczbę partycji" in text.json()["text"]

    # Od #1742 (decyzja 23.09.2026) rekrutację widzi każda rola wewnętrzna,
    # także rekruter spoza zespołu — transkrypt stoi za tą samą bramką.
    # Odmowę bez sekcji Pipeline pilnuje `test_section_revocation_http.py`.
    _outsider_id, outsider_h = await _user(UserRole.recruiter, "Spoza zespołu")
    outsider = await app_client.get(
        f"/api/interview-cycle/preps/{event_id}/transcript", headers=outsider_h
    )
    assert outsider.status_code == 200, outsider.text


async def test_model_failure_leaves_no_grade_but_a_note_with_facts(
    app_client: AsyncClient, graph: FakeGraph, monkeypatch
):
    prep_id, _event_id, _cand, _h = await _past_prep(app_client, graph)
    graph.transcripts = [teams_prep_graph.TranscriptRef(id="t1", created=None)]
    graph.vtt = VTT
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )

    def boom(chain, prompt):
        raise RuntimeError("model down")

    monkeypatch.setattr(prep_review, "_call_model", boom)
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
    async with AsyncSessionLocal() as db:
        review = await db.scalar(
            select(PrepReview).where(PrepReview.prep_meeting_id == prep_id)
        )
        assert review.status == "unavailable"
        assert review.level is None
        tr = await db.scalar(
            select(PrepTranscript).where(PrepTranscript.prep_meeting_id == prep_id)
        )
        note = await db.get(Note, tr.summary_note_id)
        assert "Ocena" not in note.content


async def test_no_transcript_after_give_up_window_marks_prep_unrecorded(
    app_client: AsyncClient, graph: FakeGraph
):
    prep_id, *_ = await _past_prep(app_client, graph, hours_ago=60)
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        assert prep.transcript_status == "missing"
        assert prep.next_fetch_at is None


async def test_no_transcript_yet_backs_off(app_client: AsyncClient, graph: FakeGraph):
    prep_id, *_ = await _past_prep(app_client, graph, hours_ago=0.5)
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        assert prep.transcript_status == "waiting"
        assert prep.fetch_attempts == 1
        assert prep.next_fetch_at > datetime.now(timezone.utc)


async def test_forbidden_is_a_state_that_does_not_burn_attempts(
    app_client: AsyncClient, graph: FakeGraph
):
    prep_id, *_ = await _past_prep(app_client, graph)
    graph.fail_list_with = 403
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        assert prep.transcript_status == "forbidden"
        assert prep.fetch_attempts == 0
        assert prep.last_error == "http_403"


async def test_outlook_cancellation_stops_waiting(
    app_client: AsyncClient, graph: FakeGraph
):
    prep_id, event_id, *_ = await _past_prep(app_client, graph)
    graph.event_state = {"isCancelled": True, "start": None, "end": None}
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        assert prep.transcript_status == "cancelled"


async def test_deleting_the_candidate_erases_transcript_and_review(
    app_client: AsyncClient, graph: FakeGraph, monkeypatch
):
    prep_id, _event_id, cand_id, _h = await _past_prep(app_client, graph)
    graph.transcripts = [teams_prep_graph.TranscriptRef(id="t1", created=None)]
    graph.vtt = VTT
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: False
    )
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
    _admin_id, admin_h = await _user(UserRole.admin, "Admin Prep")
    resp = await app_client.delete(f"/api/candidates/{cand_id}", headers=admin_h)
    assert resp.status_code in (200, 204), resp.text
    async with AsyncSessionLocal() as db:
        assert await db.get(PrepMeeting, prep_id) is None
        assert (
            await db.scalar(
                select(PrepTranscript).where(PrepTranscript.candidate_id == cand_id)
            )
        ) is None
        assert (
            await db.scalar(
                select(PrepReview).where(PrepReview.candidate_id == cand_id)
            )
        ) is None


async def test_cycle_overview_shows_prep_grade_and_weak_todo(
    app_client: AsyncClient, graph: FakeGraph, monkeypatch
):
    """Po ocenie „słaby” karta cyklu ma jakość kroku i zadanie „Prep słaby”."""
    prep_id, event_id, cand_id, rec_h = await _past_prep(app_client, graph)
    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        job_id = prep.job_id
        prep.transcript_status = "fetched"
        prep.next_fetch_at = None
        db.add(
            PrepReview(
                prep_meeting_id=prep_id,
                candidate_id=cand_id,
                job_id=job_id,
                status="ok",
                level="weak",
                criteria={},
                remaining=[],
            )
        )
        ev = await db.get(CalendarEvent, event_id)
        db.add(
            CalendarEvent(
                title="Rozmowa u klienta",
                event_type=EventType.client_interview,
                start_time=datetime.now(timezone.utc) + timedelta(days=2),
                end_time=datetime.now(timezone.utc) + timedelta(days=2, hours=1),
                candidate_id=cand_id,
                job_id=job_id,
                created_by=ev.operational_owner_id,
                operational_owner_id=ev.operational_owner_id,
            )
        )
        await db.commit()

    overview = await app_client.get("/api/interview-cycle?scope=jobs", headers=rec_h)
    assert overview.status_code == 200, overview.text
    data = overview.json()
    item = next(i for i in data["items"] if i["candidate_id"] == cand_id)
    prep_step = next(s for s in item["steps"] if s["key"] == "prep")
    assert prep_step["quality"] == "weak"
    kinds = {t["kind"] for t in data["todos"] if t["candidate_id"] == cand_id}
    assert {"prep_weak", "prep2_missing"} <= kinds


# ── Przegląd 23.09: runda rozmów, pusty transkrypt, ponowne zaplanowanie ─────


async def _interview(cand_id: int, job_id: int, owner_id: int, *, hours: float) -> int:
    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="Rozmowa u klienta",
            event_type=EventType.client_interview,
            start_time=datetime.now(timezone.utc) + timedelta(hours=hours),
            end_time=datetime.now(timezone.utc) + timedelta(hours=hours + 1),
            candidate_id=cand_id,
            job_id=job_id,
            created_by=owner_id,
            operational_owner_id=owner_id,
        )
        db.add(ev)
        await db.commit()
        return ev.id


async def test_a_new_interview_round_allows_new_preps(
    app_client: AsyncClient, graph: FakeGraph
):
    """Prep 1 z poprzedniej rundy (przed rozmową, która już była) nie blokuje
    Prepu 1 przed kolejną rozmową u klienta."""
    prep_id, event_id, cand_id, rec_h = await _past_prep(
        app_client, graph, hours_ago=48
    )
    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        job_id, dl_id = prep.job_id, prep.organizer_user_id
    await _interview(cand_id, job_id, dl_id, hours=-24)  # runda 1 za nami
    await _interview(cand_id, job_id, dl_id, hours=72)  # runda 2 przed nami

    overview = await app_client.get("/api/interview-cycle?scope=jobs", headers=rec_h)
    item = next(i for i in overview.json()["items"] if i["candidate_id"] == cand_id)
    kinds = {
        t["kind"] for t in overview.json()["todos"] if t["candidate_id"] == cand_id
    }
    assert "prep_missing" in kinds, item["steps"]

    again = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(24),
        end=_at(25),
    )
    assert again.status_code == 201, again.text


async def test_unrecorded_prep_does_not_block_planning_it_again(
    app_client: AsyncClient, graph: FakeGraph
):
    prep_id, _event_id, cand_id, rec_h = await _past_prep(
        app_client, graph, hours_ago=60
    )
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
        prep = await db.get(PrepMeeting, prep_id)
        assert prep.transcript_status == "missing"
        job_id, dl_id = prep.job_id, prep.organizer_user_id
    again = await _create(
        app_client,
        rec_h,
        candidate_id=cand_id,
        job_id=job_id,
        prep_no=1,
        organizer_user_id=dl_id,
        start=_at(24),
        end=_at(25),
    )
    assert again.status_code == 201, again.text


async def test_moving_an_unrecorded_prep_to_the_future_waits_for_transcript_again():
    from app.services.prep_meetings import reschedule_fetch

    prep = PrepMeeting(
        transcript_status="missing", fetch_attempts=5, next_fetch_at=None
    )
    reschedule_fetch(prep, datetime.now(timezone.utc) + timedelta(days=1))
    assert prep.transcript_status == "waiting"
    assert prep.fetch_attempts == 0
    assert prep.next_fetch_at is not None


async def test_empty_transcript_is_unrecorded_not_weak(
    app_client: AsyncClient, graph: FakeGraph, monkeypatch
):
    prep_id, *_ = await _past_prep(app_client, graph)
    graph.transcripts = [teams_prep_graph.TranscriptRef(id="t1", created=None)]
    graph.vtt = "WEBVTT\n\n"
    called = []
    monkeypatch.setattr(prep_review, "_call_model", lambda *a: called.append(a))
    async with AsyncSessionLocal() as db:
        await prep_transcripts.run_once(db)
    async with AsyncSessionLocal() as db:
        prep = await db.get(PrepMeeting, prep_id)
        assert prep.transcript_status == "missing"
        assert prep.last_error == "empty_transcript"
        assert (
            await db.scalar(
                select(PrepReview).where(PrepReview.prep_meeting_id == prep_id)
            )
        ) is None
    assert called == []
