"""API v1: rozmowy kandydatów u klienta i prepy (``calendar:read``).

Dwie części:

* bez bazy — czyste projekcje ``services/integration_calendar_reads``: faza
  jednej rozmowy liczona krokami cyklu, prepy jednej rozmowy (runda i prepy
  „po terminie”), cykl pary jak plakietka na Tablicy, debrief z flagami
  zawsze, treścią z ``notes:read`` i warunkiem kandydata z ``amounts:read``;
* z bazą (CI) — trasy przez HTTP: filtry listy, brak treści wydarzenia
  (tytuł, opis, uczestnicy, miejsce, link), rozmowy ukrytego klienta nie
  istnieją, 403 bez scope'u, prepy i debrief w szczegółach.

Dane są zmyślone (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_interview_slot_request import ClientInterviewSlotRequest
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.job import Job, JobStatus
from app.models.prep_meeting import PrepMeeting
from app.services import integration_calendar_reads as reads
from app.services.interview_cycle import EventRef, PairSnapshot, SlotRef
from tests.test_service_accounts import _account_with_key

V1 = "/api/integrations/v1"
NOW = datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc)
WINDOW = 30


# ── Bez bazy: faza jednej rozmowy ───────────────────────────────────────────


@pytest.mark.parametrize(
    ("start", "debriefed", "status", "expected"),
    [
        (NOW + timedelta(days=1), False, "scheduled", reads.PHASE_SCHEDULED),
        # W trakcie rozmowy telefon jeszcze nie jest należny.
        (NOW - timedelta(minutes=10), False, "scheduled", reads.PHASE_SCHEDULED),
        # Koniec 15 min temu (rozmowa 1 h) — okno telefonu 30 min.
        (NOW - timedelta(minutes=75), False, "completed", reads.PHASE_CALL_DUE),
        (NOW - timedelta(hours=3), False, "completed", reads.PHASE_DEBRIEF_OVERDUE),
        (NOW - timedelta(days=2), True, "completed", reads.PHASE_DEBRIEFED),
        (NOW - timedelta(days=2), True, "cancelled", reads.PHASE_CANCELLED),
    ],
)
def test_event_phase_follows_the_cycle_steps(start, debriefed, status, expected):
    phase = reads.event_phase(
        status=status,
        start=start,
        end=start + timedelta(hours=1),
        debriefed=debriefed,
        now=NOW,
        call_window=WINDOW,
    )
    assert phase == expected


def test_event_phase_without_end_assumes_an_hour():
    start = NOW - timedelta(minutes=70)
    assert (
        reads.event_phase(
            status="completed",
            start=start,
            end=None,
            debriefed=False,
            now=NOW,
            call_window=WINDOW,
        )
        == reads.PHASE_CALL_DUE
    )


def test_naive_query_time_is_utc():
    naive = datetime(2026, 10, 1, 8, 0)
    assert reads.aware(naive) == datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
    assert reads.aware(None) is None


# ── Bez bazy: prepy jednej rozmowy ──────────────────────────────────────────


def _prep(pid: int, start: datetime, prep_no=None) -> EventRef:
    return EventRef(
        id=pid, start=start, end=None, title="", status="scheduled", prep_no=prep_no
    )


def test_round_preps_belong_to_the_interview_they_precede():
    first = (10, NOW - timedelta(days=5))
    second = (11, NOW + timedelta(days=5))
    preps = [
        _prep(1, NOW - timedelta(days=7)),  # przed pierwszą rozmową
        _prep(2, NOW - timedelta(days=1), prep_no=1),  # między rozmowami
        _prep(3, NOW + timedelta(days=2), prep_no=2),  # między rozmowami
        _prep(4, NOW + timedelta(days=6)),  # po ostatniej, przyszłej rozmowie
    ]
    on_time, late = reads.split_round_preps([first, second], preps, 10, NOW)
    assert [p.id for p in on_time] == [1]
    assert late == []

    on_time, late = reads.split_round_preps([first, second], preps, 11, NOW)
    assert [(p.id, p.ordinal) for p in on_time] == [(2, 1), (3, 2)]
    # Prep po rozmowie bierze numer wolny po prepach rundy — jak na ekranie.
    assert [(p.id, p.ordinal) for p in late] == [(4, 3)]


def test_no_late_preps_after_an_interview_that_already_happened():
    past = (10, NOW - timedelta(days=2))
    preps = [_prep(1, NOW - timedelta(days=1))]
    on_time, late = reads.split_round_preps([past], preps, 10, NOW)
    assert on_time == [] and late == []


def test_cancelled_or_unknown_interview_has_no_preps():
    assert reads.split_round_preps([], [_prep(1, NOW)], 10, NOW) == ([], [])


def test_prep_out_reports_nexus_number_and_state_without_content():
    prep = EventRef(
        id=5,
        start=NOW,
        end=NOW + timedelta(minutes=30),
        title="Przygotowanie do spotkania z Klientem — Anna Przykładowa",
        status="completed",
        online_meeting_url="https://teams.example.com/prep",
        prep_no=2,
        ordinal=2,
        transcription_setup="enabled",
        transcript_status="fetched",
        review_status="ok",
        review_level="good",
    )
    out = reads.prep_out(prep, late=False)
    assert out["prep_no"] == 2 and out["from_nexus"] is True
    assert out["transcript_status"] == "fetched" and out["review_level"] == "good"
    assert "title" not in out and "online_meeting_url" not in out


# ── Bez bazy: cykl pary jak plakietka Tablicy ───────────────────────────────


def test_cycle_of_open_slot_request_is_the_recruiter_pick():
    snapshot = PairSnapshot(
        candidate_id=1,
        job_id=2,
        slot_request=SlotRef(
            id=3,
            status="awaiting_recruiter",
            slots=({"start": (NOW + timedelta(days=3)).isoformat()},),
            chosen_index=None,
            respond_by=None,
            recruiter_id=None,
            created_by=None,
            duration_minutes=60,
            note=None,
            event_id=None,
        ),
    )
    cycle = reads.cycle_of(snapshot, NOW, call_window=WINDOW)
    assert cycle.phase == "awaiting_recruiter_pick"
    assert cycle.current_step == "choice"
    assert cycle.slot_request_status == "awaiting_recruiter"
    assert cycle.interview_event_id is None and cycle.round_event_ids == frozenset()


def test_cycle_of_finished_interview_without_debrief_waits_for_the_call():
    start = NOW - timedelta(minutes=70)
    snapshot = PairSnapshot(
        candidate_id=1,
        job_id=2,
        interview=EventRef(
            id=9, start=start, end=start + timedelta(hours=1), title="", status="x"
        ),
    )
    cycle = reads.cycle_of(snapshot, NOW, call_window=WINDOW)
    assert cycle.phase == "debrief_due"
    assert cycle.current_step == "call"
    assert cycle.interview_event_id == 9 and cycle.round_event_ids == {9}


# ── Bez bazy: debrief ───────────────────────────────────────────────────────


def _feedback(**overrides):
    values = {
        "id": 7,
        "overall_impression": 5,
        "offer_acceptance": "likely",
        "acceptance_condition": "Minimum 160 zł/h netto",
        "candidate_questions": None,
        "client_questions": "Pytanie o Kafkę\n\nPytanie o testy\n",
        "concerns": "Kandydat zadowolony z rozmowy",
        "no_client_questions": False,
        "updated_at": NOW - timedelta(days=1),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_debrief_flags_without_notes_scope():
    out = reads.debrief_out(
        _feedback(), start=NOW - timedelta(days=2), notes=False, costs=True
    )
    assert out["done"] is True
    assert out["outcome"] == "good" and out["offer_acceptance"] == "likely"
    assert out["client_questions_count"] == 2
    assert out["has_acceptance_condition"] is True
    assert out["notes_redacted"] is True
    assert out["candidate_comment"] is None and out["client_questions"] is None
    # Warunek wymaga OBU scope'ów — sam ``amounts:read`` go nie odsłania.
    assert out["acceptance_condition"] is None
    assert out["costs_redacted"] is False


def test_debrief_text_with_notes_and_condition_only_with_amounts():
    start = NOW - timedelta(days=2)
    notes_only = reads.debrief_out(_feedback(), start=start, notes=True, costs=False)
    assert notes_only["candidate_comment"] == "Kandydat zadowolony z rozmowy"
    assert notes_only["client_questions"] == ["Pytanie o Kafkę", "Pytanie o testy"]
    assert notes_only["acceptance_condition"] is None
    assert notes_only["costs_redacted"] is True

    full = reads.debrief_out(_feedback(), start=start, notes=True, costs=True)
    assert full["acceptance_condition"] == "Minimum 160 zł/h netto"


def test_debrief_saved_before_the_interview_does_not_close_the_round():
    start = NOW - timedelta(hours=2)
    out = reads.debrief_out(
        _feedback(updated_at=start - timedelta(minutes=5)),
        start=start,
        notes=False,
        costs=False,
    )
    assert out["done"] is False
    without_questions = reads.debrief_out(
        _feedback(client_questions=None),
        start=NOW - timedelta(days=2),
        notes=False,
        costs=False,
    )
    assert without_questions["done"] is False


def test_interview_out_has_no_event_content_fields():
    """Pilnuje kształtu: treść wydarzenia nigdy nie trafia do odpowiedzi."""
    from app.api.integrations_v1.calendar import InterviewDetailOut

    fields = set(InterviewDetailOut.model_fields)
    for forbidden in (
        "title",
        "description",
        "attendees",
        "location",
        "teams_link",
        "online_meeting_url",
        "recording_url",
    ):
        assert forbidden not in fields


# ── Z bazą (CI): trasy v1 ────────────────────────────────────────────────────


def _h(api_key: str) -> dict:
    return {"X-API-Key": api_key}


async def _key(app_client: AsyncClient, headers: dict, scopes: list[str]) -> str:
    _, api_key, _ = await _account_with_key(app_client, headers, scopes)
    return api_key


async def _world(*, hidden_client: bool = False) -> dict:
    """Klient z rekrutacją: Anna po rozmowie z debriefem i prepem, Jan przed
    rozmową z nowym wnioskiem o terminy, odwołana rozmowa w drugiej rekrutacji."""
    tag = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        client = Client(name=f"V1 Kalendarz {tag}", hidden=hidden_client)
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Java Developer {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        other = Job(
            title=f"Tester manualny {tag}",
            client_id=client.id,
            status=JobStatus.published,
        )
        anna = Candidate(
            name="Anna",
            lastname=f"Przykładowa-{tag}",
            email=f"anna-cal-{tag}@example.com",
        )
        jan = Candidate(
            name="Jan", lastname=f"Testowy-{tag}", email=f"jan-cal-{tag}@example.com"
        )
        db.add_all([job, other, anna, jan])
        await db.flush()

        def interview(candidate, job_row, start, **extra):
            return CalendarEvent(
                title=f"Rozmowa {candidate.name} SEKRET-{tag}",
                description=f"Notatka DL {tag}: stawka do uzgodnienia",
                event_type=EventType.client_interview,
                start_time=start,
                end_time=start + timedelta(hours=1),
                candidate_id=candidate.id,
                job_id=job_row.id,
                client_id=client.id,
                attendees=[f"uczestnik-{tag}@example.com"],
                location=f"Biuro klienta {tag}, ul. Przykładowa 1",
                teams_link=f"https://teams.example.com/{tag}",
                **extra,
            )

        past = interview(
            anna, job, now - timedelta(days=3), status=EventStatus.completed
        )
        future = interview(jan, job, now + timedelta(days=2))
        cancelled = interview(
            anna, other, now + timedelta(days=4), status=EventStatus.cancelled
        )
        prep = CalendarEvent(
            title=f"Przygotowanie {tag}",
            event_type=EventType.prep_call,
            start_time=now - timedelta(days=4),
            end_time=now - timedelta(days=4) + timedelta(minutes=30),
            candidate_id=anna.id,
            job_id=job.id,
            status=EventStatus.completed,
        )
        db.add_all([past, future, cancelled, prep])
        await db.flush()
        db.add_all(
            [
                PrepMeeting(
                    calendar_event_id=prep.id,
                    candidate_id=anna.id,
                    job_id=job.id,
                    prep_no=1,
                    organizer_upn=f"dl-{tag}@example.com",
                    transcription_setup="enabled",
                    transcript_status="fetched",
                ),
                InterviewFeedback(
                    calendar_event_id=past.id,
                    candidate_id=anna.id,
                    job_id=job.id,
                    feedback_source=FeedbackSource.candidate_side,
                    overall_impression=5,
                    concerns=f"Kandydatka zadowolona {tag}",
                    client_questions="Pytanie o Kafkę\nPytanie o testy",
                    offer_acceptance="likely",
                    acceptance_condition="Minimum 160 zł/h netto",
                ),
                ClientInterviewSlotRequest(
                    candidate_id=jan.id,
                    job_id=job.id,
                    client_id=client.id,
                    slots=[
                        {
                            "start": (now + timedelta(days=6)).isoformat(),
                            "end": (now + timedelta(days=6, hours=1)).isoformat(),
                        }
                    ],
                    duration_minutes=60,
                    status="awaiting_recruiter",
                ),
            ]
        )
        await db.commit()
        return {
            "tag": tag,
            "now": now,
            "job_id": job.id,
            "other_id": other.id,
            "anna": anna.id,
            "jan": jan.id,
            "past": past.id,
            "future": future.id,
            "cancelled": cancelled.id,
            "prep": prep.id,
        }


async def _list(app_client: AsyncClient, api_key: str, **params) -> dict:
    resp = await app_client.get(f"{V1}/interviews", headers=_h(api_key), params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


class TestInterviews:
    async def test_list_filters_and_carries_no_event_content(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["calendar:read"])

        body = await _list(app_client, api_key, job_id=world["job_id"])
        by_id = {item["event_id"]: item for item in body["items"]}
        assert list(by_id) == [world["past"], world["future"]]  # rosnąco po starcie
        assert body["total"] == 2

        past = by_id[world["past"]]
        assert past["phase"] == "debriefed" and past["debrief_done"] is True
        assert past["candidate_id"] == world["anna"]
        assert past["candidate_first_name"] == "Anna"
        assert past["job_title"] == f"Java Developer {world['tag']}"
        assert past["current_round"] is True
        assert past["cycle"]["phase"] == "debriefed"

        future = by_id[world["future"]]
        assert future["phase"] == "scheduled" and future["debrief_done"] is False
        assert future["cycle"]["slot_request_status"] == "awaiting_recruiter"
        assert future["cycle"]["phase"] == "awaiting_recruiter_pick"

        raw = str(body)
        for secret in (
            f"SEKRET-{world['tag']}",
            f"Notatka DL {world['tag']}",
            f"uczestnik-{world['tag']}@example.com",
            f"Biuro klienta {world['tag']}",
            f"teams.example.com/{world['tag']}",
            f"Kandydatka zadowolona {world['tag']}",
        ):
            assert secret not in raw

        only_anna = await _list(app_client, api_key, candidate_id=world["anna"])
        assert [i["event_id"] for i in only_anna["items"]] == [
            world["past"],
            world["cancelled"],
        ]

        later = await _list(
            app_client,
            api_key,
            job_id=world["job_id"],
            **{"from": world["now"].isoformat()},
        )
        assert [i["event_id"] for i in later["items"]] == [world["future"]]

        earlier = await _list(
            app_client,
            api_key,
            job_id=world["job_id"],
            to=world["now"].isoformat(),
        )
        assert [i["event_id"] for i in earlier["items"]] == [world["past"]]

        cancelled = await _list(
            app_client, api_key, candidate_id=world["anna"], status="cancelled"
        )
        assert [i["event_id"] for i in cancelled["items"]] == [world["cancelled"]]
        assert cancelled["items"][0]["phase"] == "cancelled"

    async def test_hidden_client_interviews_do_not_exist(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world(hidden_client=True)
        api_key = await _key(app_client, app_auth_headers, ["calendar:read"])
        body = await _list(app_client, api_key, job_id=world["job_id"])
        assert body["items"] == [] and body["total"] == 0
        resp = await app_client.get(
            f"{V1}/interviews/{world['past']}", headers=_h(api_key)
        )
        assert resp.status_code == 404, resp.text
        assert resp.json()["error"]["code"] == "not_found"

    async def test_requires_calendar_scope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        api_key = await _key(app_client, app_auth_headers, ["candidates:read"])
        for path in ("/interviews", f"/interviews/{world['past']}"):
            resp = await app_client.get(f"{V1}{path}", headers=_h(api_key))
            assert resp.status_code == 403, resp.text
            assert resp.json()["error"]["code"] == "insufficient_scope"

    async def test_detail_preps_and_debrief_per_scope(
        self, app_client: AsyncClient, app_auth_headers: dict
    ):
        world = await _world()
        path = f"{V1}/interviews/{world['past']}"

        calendar_only = await _key(app_client, app_auth_headers, ["calendar:read"])
        resp = await app_client.get(path, headers=_h(calendar_only))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert [p["event_id"] for p in body["preps"]] == [world["prep"]]
        prep = body["preps"][0]
        assert prep["prep_no"] == 1 and prep["from_nexus"] is True
        assert prep["transcript_status"] == "fetched" and prep["late"] is False
        debrief = body["debrief"]
        assert debrief["done"] is True and debrief["outcome"] == "good"
        assert debrief["client_questions_count"] == 2
        assert debrief["has_acceptance_condition"] is True
        assert debrief["notes_redacted"] is True
        assert debrief["candidate_comment"] is None
        assert debrief["client_questions"] is None
        assert debrief["acceptance_condition"] is None

        with_notes = await _key(
            app_client, app_auth_headers, ["calendar:read", "notes:read"]
        )
        debrief = (await app_client.get(path, headers=_h(with_notes))).json()["debrief"]
        assert debrief["candidate_comment"] == f"Kandydatka zadowolona {world['tag']}"
        assert debrief["client_questions"] == ["Pytanie o Kafkę", "Pytanie o testy"]
        assert debrief["acceptance_condition"] is None
        assert debrief["costs_redacted"] is True

        with_amounts = await _key(
            app_client,
            app_auth_headers,
            ["calendar:read", "notes:read", "amounts:read"],
        )
        debrief = (await app_client.get(path, headers=_h(with_amounts))).json()[
            "debrief"
        ]
        assert debrief["acceptance_condition"] == "Minimum 160 zł/h netto"

        future = (
            await app_client.get(
                f"{V1}/interviews/{world['future']}", headers=_h(calendar_only)
            )
        ).json()
        assert future["debrief"] is None and future["preps"] == []
