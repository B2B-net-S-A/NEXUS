"""Runda 8 audytu — cykl rozmów u klienta i prepy (CAL: R8-N9-*, R8-X1-2).

Czyste testy (bez bazy) pilnują reguł; testy z ``AsyncSessionLocal`` na dole
sprawdzają te same scenariusze na prawdziwych zapytaniach (CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.services.debrief_gate import pick_current_round
from app.services.interview_cycle import (
    PairSnapshot,
    SlotRef,
    compute_todos,
)
from app.services.prep_review import Item, parse_review

NOW = datetime(2031, 6, 10, 12, 0, tzinfo=timezone.utc)


# ── R8-N9-3: jedna reguła „bieżącej rundy” ──────────────────────────────────


def test_round_that_just_ended_without_debrief_beats_the_next_round() -> None:
    rounds = [(NOW - timedelta(minutes=70), False), (NOW + timedelta(days=5), False)]
    assert pick_current_round(rounds, NOW) == 0


def test_debriefed_round_gives_way_to_the_nearest_future_round() -> None:
    rounds = [
        (NOW - timedelta(days=3), True),
        (NOW + timedelta(days=2), False),
        (NOW + timedelta(days=5), False),
    ]
    assert pick_current_round(rounds, NOW) == 1


def test_two_future_rounds_the_earlier_one_is_current() -> None:
    rounds = [(NOW + timedelta(days=2), False), (NOW + timedelta(days=5), False)]
    assert pick_current_round(rounds, NOW) == 0


def test_all_rounds_closed_the_last_one_stays() -> None:
    rounds = [(NOW - timedelta(days=9), True), (NOW - timedelta(days=2), True)]
    assert pick_current_round(rounds, NOW) == 1
    assert pick_current_round([], NOW) is None


def test_old_round_without_debrief_after_a_later_held_round_is_abandoned() -> None:
    rounds = [
        (NOW - timedelta(days=9), False),
        (NOW - timedelta(days=2), True),
        (NOW + timedelta(days=3), False),
    ]
    assert pick_current_round(rounds, NOW) == 2


# ── R8-N9-2: awaria protokołu modelu = „niedostępna”, nie „słaby” ───────────

_T = "Jan: pracowałem w Javie 5 lat w banku. Anna: dziękuję."
_ITEMS = [Item("must:Java", "Java", "must")]


def test_keys_not_matching_the_items_are_a_protocol_error() -> None:
    raw = (
        '{"summary":"x","must_haves":[{"key":"Java","status":"covered",'
        '"quote":"pracowałem w Javie 5 lat"}],"client_questions":[]}'
    )
    with pytest.raises(ValueError):
        parse_review(raw, items=_ITEMS, transcript=_T)


def test_missing_group_is_a_protocol_error() -> None:
    items = _ITEMS + [Item("q:7", "Jak testujesz?", "question")]
    raw = (
        '{"summary":"x","must_haves":[{"key":"must:Java","status":"covered",'
        '"quote":"pracowałem w Javie 5 lat"}]}'
    )
    with pytest.raises(ValueError):
        parse_review(raw, items=items, transcript=_T)


def test_unknown_statuses_are_a_protocol_error_but_case_is_tolerated() -> None:
    bad = (
        '{"summary":"x","must_haves":[{"key":"must:Java","status":"done",'
        '"quote":"pracowałem w Javie 5 lat"}],"client_questions":[]}'
    )
    with pytest.raises(ValueError):
        parse_review(bad, items=_ITEMS, transcript=_T)
    ok = bad.replace('"done"', '"Covered"')
    parsed = parse_review(ok, items=_ITEMS, transcript=_T)
    assert parsed["items"][0]["status"] == "covered"


# ── R8-N9-1: ocena prepu = pytania z prep-kitu ──────────────────────────────


@pytest.mark.asyncio
async def test_build_items_scores_only_questions_the_prep_kit_shows(monkeypatch):
    from app.services import dz_review, prep_review, question_suggestions
    from app.services.question_suggestions import SuggestedQuestion

    class _Db:
        async def execute(self, _statement):
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    bank = [
        SuggestedQuestion(
            text="Jak używasz Spring Boot?",
            source_tier="client_debrief",
            question_id=1,
            skill_tags=["spring boot"],
        ),
        SuggestedQuestion(
            text="Jak budujesz aplikacje w Power Apps?",
            source_tier="client_debrief",
            question_id=2,
            skill_tags=["power apps"],
        ),
        SuggestedQuestion(
            text="Dlaczego chcesz zmienić projekt?",
            source_tier="client_debrief",
            question_id=3,
        ),
    ]
    asked = []

    async def tier(db, job):
        asked.append(job.id)
        return bank

    monkeypatch.setattr(question_suggestions, "_tier_client_debrief", tier)
    monkeypatch.setattr(
        question_suggestions, "job_requirement_names", lambda job: {"power apps"}
    )
    monkeypatch.setattr(
        question_suggestions,
        "mentioned_technologies",
        lambda text, tags=None: set(tags or []),
    )
    monkeypatch.setattr(
        dz_review,
        "job_requirements",
        lambda job: ([SimpleNamespace(label="Power Apps")], []),
    )
    job = SimpleNamespace(id=5, client_id=9)
    items = await prep_review.build_items(_Db(), job)
    assert asked == [5]
    assert [i.key for i in items] == ["must:Power Apps", "q:2", "q:3"]


# ── R8-N9-6: zastępca dostaje zadania terminu ───────────────────────────────


def _slot(status: str) -> SlotRef:
    return SlotRef(
        id=3,
        status=status,
        slots=({"start": "2031-06-12T08:00:00+00:00"},),
        chosen_index=0,
        respond_by=NOW + timedelta(days=1),
        recruiter_id=11,
        created_by=11,
        duration_minutes=60,
        note=None,
        event_id=None,
    )


def test_substitute_gets_pick_and_confirm_todos() -> None:
    from app.models.client_interview_slot_request import (
        SLOT_STATUS_AWAITING_DL,
        SLOT_STATUS_AWAITING_RECRUITER,
    )

    for status, kind in (
        (SLOT_STATUS_AWAITING_RECRUITER, "slots_pick"),
        (SLOT_STATUS_AWAITING_DL, "slots_confirm"),
    ):
        pair = PairSnapshot(1, 2, slot_request=_slot(status))
        without = compute_todos(
            pair, NOW, call_window_minutes=30, user_id=77, is_dl_view=False
        )
        assert kind not in [t["kind"] for t in without]
        with_sub = compute_todos(
            pair,
            NOW,
            call_window_minutes=30,
            user_id=77,
            is_dl_view=False,
            acting_for={77, 11},
        )
        assert kind in [t["kind"] for t in with_sub]


# ── R8-N9-4: blokada w Outlooku nie steruje rozmową z NEXUSA ────────────────


class _OneRowDb:
    def __init__(self, row):
        self.row = row

    async def scalar(self, _statement):
        return self.row


def _nexus_interview(start: datetime) -> CalendarEvent:
    return CalendarEvent(
        id=1,
        title="Rozmowa u klienta",
        description="Notatka DL: sala 3",
        event_type=EventType.client_interview,
        status=EventStatus.scheduled,
        start_time=start,
        end_time=start + timedelta(hours=1),
        operational_owner_id=5,
        external_source="microsoft365",
        external_id="G1",
        m365_change_key="ck1",
    )


@pytest.mark.asyncio
async def test_removed_outlook_block_does_not_cancel_the_nexus_interview():
    from app.services.m365 import sync

    ev = _nexus_interview(datetime.now(timezone.utc) + timedelta(days=2))
    conn = SimpleNamespace(id=1, user_id=5)
    await sync._upsert_event(
        _OneRowDb(ev), conn, {"id": "G1", "@removed": {"reason": "deleted"}}
    )
    assert ev.status == EventStatus.scheduled
    assert ev.external_id is None and ev.external_source is None


@pytest.mark.asyncio
async def test_moved_outlook_block_does_not_move_the_nexus_interview():
    from app.services.m365 import sync

    start = datetime.now(timezone.utc) + timedelta(days=2)
    ev = _nexus_interview(start)
    conn = SimpleNamespace(id=1, user_id=5)
    moved = (start + timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S.0000000")
    await sync._upsert_event(
        _OneRowDb(ev),
        conn,
        {
            "id": "G1",
            "changeKey": "ck2",
            "subject": "blokada",
            "body": {"content": "blokada w kalendarzu"},
            "start": {"dateTime": moved, "timeZone": "UTC"},
            "end": {"dateTime": moved, "timeZone": "UTC"},
        },
    )
    assert ev.start_time == start
    assert ev.description == "Notatka DL: sala 3"
    assert ev.status == EventStatus.scheduled


# ── R8-N9-7: przypomnienie wraca po przełożeniu ─────────────────────────────


def test_rescheduling_to_the_future_rearms_the_reminder() -> None:
    now = datetime.now(timezone.utc)
    ev = CalendarEvent(start_time=now + timedelta(minutes=10))
    ev.reminder_sent_at = now
    ev.start_time = now + timedelta(minutes=10)  # ten sam termin
    assert ev.reminder_sent_at == now
    ev.start_time = now + timedelta(hours=2)
    assert ev.reminder_sent_at is None


def test_moving_into_the_past_keeps_the_stamp() -> None:
    now = datetime.now(timezone.utc)
    ev = CalendarEvent(start_time=now + timedelta(minutes=10))
    ev.reminder_sent_at = now
    ev.start_time = now - timedelta(hours=2)
    assert ev.reminder_sent_at == now


# ── R8-N9-8: usunięty odbyty prep to nie odwołanie ──────────────────────────


@pytest.mark.asyncio
async def test_deleted_held_prep_is_not_cancelled(monkeypatch):
    from app.services import prep_transcripts
    from app.services.m365 import teams_prep_graph
    from app.services.m365.graph_client import GraphRequestError

    async def gone(upn, event_id):
        raise GraphRequestError(404, "not found")

    monkeypatch.setattr(teams_prep_graph, "get_event", gone)
    prep = SimpleNamespace(organizer_upn="dl@example.com")
    now = datetime.now(timezone.utc)
    held = SimpleNamespace(
        external_id="G9",
        start_time=now - timedelta(hours=2),
        end_time=now - timedelta(hours=1),
    )
    assert await prep_transcripts._refresh_event(prep, held, now) == "gone"
    ahead = SimpleNamespace(
        external_id="G9",
        start_time=now + timedelta(hours=2),
        end_time=now + timedelta(hours=3),
    )
    assert await prep_transcripts._refresh_event(prep, ahead, now) == "cancelled"


# ── R8-N9-9: długi transkrypt nie jest ucinany ──────────────────────────────


@pytest.mark.asyncio
async def test_too_long_transcript_is_unavailable_not_truncated(monkeypatch):
    from app.services import prep_review

    long_text = "Jan: " + "a" * (prep_review.MAX_TRANSCRIPT_CHARS + 10)
    called = []
    monkeypatch.setattr(prep_review, "_call_model", lambda *a: called.append(a))

    async def items(db, job):
        return [Item("must:Java", "Java", "must")]

    monkeypatch.setattr(prep_review, "build_items", items)
    monkeypatch.setattr(
        "app.services.llm_providers.api_key_configured", lambda model: True
    )
    prep = SimpleNamespace(
        id=1, job_id=2, candidate_id=3, prep_no=1, organizer_user_id=4
    )
    transcript = SimpleNamespace(
        plain_text=long_text, talk_share=None, duration_seconds=3600
    )
    job = SimpleNamespace(id=2, title="Rola")
    added, notes = [], []

    class _Db:
        async def get(self, model, _id):
            return prep if model.__name__ == "PrepMeeting" else job

        async def scalar(self, statement):
            text = str(statement)
            if "prep_transcripts" in text:
                return transcript
            return None

        def add(self, obj):
            added.append(obj)

        async def commit(self):
            return None

    async def upsert_note(db, p, t, content):
        notes.append(content)

    monkeypatch.setattr(prep_review, "_upsert_note", upsert_note)
    review = await prep_review.review_prep(_Db(), 1)
    assert called == []
    assert review.status == "unavailable" and review.level is None


# ── Z bazą (CI) ──────────────────────────────────────────────────────────────


async def _seed_pair():
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"R8CalClient-{tag}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"R8CalJob-{tag}", status=JobStatus.published, client_id=client.id
        )
        cand = Candidate(
            name="Ola",
            lastname=f"Runda-{tag}",
            email=f"r8cal-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.commit()
        return job.id, cand.id, client.id


async def _seed_event(
    cand_id, job_id, client_id, start, etype, status=EventStatus.scheduled
):
    from app.core.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ev = CalendarEvent(
            title="E",
            event_type=etype,
            start_time=start,
            end_time=start + timedelta(hours=1),
            status=status,
            candidate_id=cand_id,
            job_id=job_id,
            client_id=client_id,
            attendees=[],
        )
        db.add(ev)
        await db.commit()
        return ev.id


async def test_call_after_round_a_is_not_hidden_by_round_b():
    from app.core.database import AsyncSessionLocal
    from app.services.debrief_gate import missing_debrief
    from app.services.interview_cycle import load_snapshots

    now = datetime.now(timezone.utc)
    job_id, cand_id, client_id = await _seed_pair()
    a = await _seed_event(
        cand_id,
        job_id,
        client_id,
        now - timedelta(minutes=70),
        EventType.client_interview,
        EventStatus.completed,
    )
    await _seed_event(
        cand_id, job_id, client_id, now + timedelta(days=5), EventType.client_interview
    )
    async with AsyncSessionLocal() as db:
        snaps = await load_snapshots(
            db,
            [(cand_id, job_id)],
            window_start=now - timedelta(days=14),
            window_end=now + timedelta(days=30),
            now=now,
        )
        snap = snaps[(cand_id, job_id)]
        assert snap.interview is not None and snap.interview.id == a
        todos = compute_todos(
            snap, now, call_window_minutes=30, user_id=1, is_dl_view=True
        )
        assert ("call_now", a) in [(t["kind"], t["event_id"]) for t in todos]
        gate = await missing_debrief(db, candidate_id=cand_id, job_id=job_id, now=now)
        assert gate is not None and gate["event_id"] == a
        assert gate["interview_pending"] is False


async def test_prep_missing_on_screen_means_prep_can_be_scheduled():
    from app.core.database import AsyncSessionLocal
    from app.models.prep_meeting import PrepMeeting
    from app.services.interview_cycle import load_snapshots
    from app.services.prep_meetings import active_prep

    now = datetime.now(timezone.utc)
    job_id, cand_id, client_id = await _seed_pair()
    await _seed_event(
        cand_id, job_id, client_id, now + timedelta(days=2), EventType.client_interview
    )
    await _seed_event(
        cand_id, job_id, client_id, now + timedelta(days=5), EventType.client_interview
    )
    prep_ev = await _seed_event(
        cand_id, job_id, client_id, now + timedelta(days=1), EventType.prep_call
    )
    async with AsyncSessionLocal() as db:
        db.add(
            PrepMeeting(
                calendar_event_id=prep_ev,
                candidate_id=cand_id,
                job_id=job_id,
                prep_no=1,
                organizer_upn="dl@example.com",
            )
        )
        await db.commit()
    async with AsyncSessionLocal() as db:
        snap = (
            await load_snapshots(
                db,
                [(cand_id, job_id)],
                window_start=now - timedelta(days=14),
                window_end=now + timedelta(days=30),
                now=now,
            )
        )[(cand_id, job_id)]
        todos = compute_todos(
            snap, now, call_window_minutes=30, user_id=1, is_dl_view=True
        )
        screen_wants_prep1 = "prep_missing" in [t["kind"] for t in todos]
        existing = await active_prep(db, candidate_id=cand_id, job_id=job_id, prep_no=1)
        assert screen_wants_prep1 == (existing is None)
        assert existing is not None  # Prep 1 jutro należy do rundy A


async def test_client_feedback_alert_sees_client_interview_and_hm_verdict():
    from zoneinfo import ZoneInfo

    from sqlalchemy import select

    from app.core.config import settings
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.interview_feedback import FeedbackSource, InterviewFeedback
    from app.models.job import Job
    from app.models.notification import Notification, NotificationType
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.user import User, UserRole
    from app.services import notification_triggers as nt

    tz = ZoneInfo(settings.BUSINESS_TZ)
    today = datetime.now(tz).date()
    now = datetime(
        today.year,
        today.month,
        today.day,
        settings.CLIENT_FEEDBACK_ALERT_HOUR,
        settings.CLIENT_FEEDBACK_ALERT_MINUTE,
        tzinfo=tz,
    )
    start = datetime(today.year, today.month, today.day, 9, 0, tzinfo=tz)

    async def scenario(with_verdict: bool) -> bool:
        tag = uuid.uuid4().hex[:8]
        job_id, cand_id, client_id = await _seed_pair()
        async with AsyncSessionLocal() as db:
            dl = User(
                email=f"r8cal-dl-{tag}@example.com",
                password_hash=hash_password(f"Dl_{tag}!pw9"),
                name=f"DL {tag}",
                role=UserRole.delivery_lead,
                roles=[UserRole.delivery_lead.value],
                is_active=True,
                profile_completed=True,
            )
            db.add(dl)
            await db.flush()
            job = await db.get(Job, job_id)
            job.delivery_lead_id = dl.id
            db.add(
                CandidateStage(
                    candidate_id=cand_id,
                    job_id=job_id,
                    stage=PipelineStage.client_interview,
                    moved_at=start - timedelta(days=1),
                )
            )
            await db.commit()
            dl_id = dl.id
        ev_id = await _seed_event(
            cand_id,
            job_id,
            client_id,
            start,
            EventType.client_interview,
            EventStatus.completed,
        )
        if with_verdict:
            async with AsyncSessionLocal() as db:
                db.add(
                    InterviewFeedback(
                        calendar_event_id=None,
                        candidate_id=cand_id,
                        job_id=job_id,
                        feedback_source=FeedbackSource.client_side,
                        overall_impression=4,
                        # Werdykt zapisany po rozmowie (niezależnie od pory CI).
                        created_at=start + timedelta(hours=3),
                        updated_at=start + timedelta(hours=3),
                    )
                )
                await db.commit()
        async with AsyncSessionLocal() as db:
            await nt.check_client_feedback_eobd(db, now)
            await db.commit()
        async with AsyncSessionLocal() as db:
            found = await db.scalar(
                select(Notification.id).where(
                    Notification.user_id == dl_id,
                    Notification.notification_type
                    == NotificationType.client_feedback_eobd,
                    Notification.related_entity_id == ev_id,
                )
            )
        return found is not None

    assert await scenario(with_verdict=False) is True
    assert await scenario(with_verdict=True) is False


async def test_closed_job_does_not_ask_dl_for_client_slots():
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage
    from app.models.user import User, UserRole
    from app.services.interview_cycle import load_overview

    tag = uuid.uuid4().hex[:8]
    job_id, cand_id, _client_id = await _seed_pair()
    open_job_id, open_cand_id, _ = await _seed_pair()
    async with AsyncSessionLocal() as db:
        dl = User(
            email=f"r8cal-closed-{tag}@example.com",
            password_hash=hash_password(f"Dl_{tag}!pw9"),
            name=f"DL {tag}",
            role=UserRole.delivery_lead,
            roles=[UserRole.delivery_lead.value],
            is_active=True,
            profile_completed=True,
        )
        db.add(dl)
        await db.flush()
        job = await db.get(Job, job_id)
        job.delivery_lead_id = dl.id
        job.status = JobStatus.closed
        (await db.get(Job, open_job_id)).delivery_lead_id = dl.id
        for c_id, j_id in ((cand_id, job_id), (open_cand_id, open_job_id)):
            db.add(
                CandidateStage(
                    candidate_id=c_id,
                    job_id=j_id,
                    stage=PipelineStage.client_interview,
                    moved_at=datetime.now(timezone.utc) - timedelta(days=2),
                )
            )
        await db.commit()
        dl_id = dl.id
    async with AsyncSessionLocal() as db:
        user = await db.get(User, dl_id)
        overview = await load_overview(db, user, scope="jobs")
    todos = {(t["candidate_id"], t["kind"]) for t in overview["todos"]}
    assert (open_cand_id, "slots_missing") in todos  # kontrola: otwarta jest
    assert all(i["candidate_id"] != cand_id for i in overview["items"])
    assert all(c != cand_id for c, _kind in todos)
