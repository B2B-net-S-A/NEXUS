"""Import pytań klienta z notatek po rozmowie (20.10.2026).

Pilnuje: które notatki biorą udział, kontroli cytatu z modelu (ta sama co
archiwum z Excela), zapisu (odbyta rozmowa + debrief + bank pytań) zamykającego
bramkę przed „Umową”, powtórki bez dubli i pełnego cofnięcia.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

import app.models  # noqa: F401
from app.core.database import AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventType
from app.models.interview_feedback import FeedbackSource, InterviewFeedback
from app.models.interview_question import InterviewQuestion, JobQuestion
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.debrief_gate import missing_debrief
from scripts import import_note_client_questions as imp

NOTE = (
    "Po rozmowie z klientem. Klient pytał o: różnice między Spring Boot 2 i 3, "
    "jak testuje integracje z Kafką. Kandydatka zadowolona."
)


def test_note_rule_matches_the_front():
    assert imp.looks_like_client_questions(NOTE)
    assert imp.looks_like_client_questions("Na technicznej pytali o testy")
    assert not imp.looks_like_client_questions("Pytała o urlop w grudniu.")
    assert not imp.looks_like_client_questions("")


def test_group_by_pair_dedups_and_skips_notes():
    rows = [
        {
            "note_id": 1,
            "candidate_id": 5,
            "job_id": 7,
            "question": "Jak testujesz Kafkę?",
        },
        {
            "note_id": 2,
            "candidate_id": 5,
            "job_id": 7,
            "question": "jak  testujesz kafkę?",
        },
        {"note_id": 3, "candidate_id": 5, "job_id": 7, "question": "Spring Boot 3?"},
        {"note_id": 4, "candidate_id": 6, "job_id": 7, "question": "Helm?"},
    ]
    pairs = imp.group_by_pair(rows, skip_notes=frozenset({3}))
    assert [q["note_id"] for q in pairs[(5, 7)]] == [1]
    assert [q["note_id"] for q in pairs[(6, 7)]] == [4]


# ── Notatka bez rekrutacji przy kilku parach (audyt 21.10.2026) ──────────────
# Notatka bez `job_id` łączyła się z KAŻDĄ parą kandydata w oknie, więc te same
# pytania lądowały w debriefach i bankach kilku klientów.


def _row(note_id: int, job_id: int, *, candidate_id: int = 5) -> imp.NoteRow:
    return imp.NoteRow(
        note_id=note_id,
        candidate_id=candidate_id,
        job_id=job_id,
        job_title=f"Rola {job_id}",
        client_id=job_id * 10,
        author_id=9,
        created_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        content=NOTE,
    )


def test_note_without_job_goes_to_the_only_matching_pair():
    kept, rejected = imp.split_ambiguous_notes([_row(1, 7), _row(2, 7), _row(2, 8)])
    assert [(n.note_id, n.job_id) for n in kept] == [(1, 7)]
    assert rejected == [
        {
            "note_id": 2,
            "reason": "niejednoznaczna rekrutacja",
            "question": "rekrutacje: 7, 8",
        }
    ]


async def test_build_plan_rejects_ambiguous_notes_without_asking_the_model(
    monkeypatch,
):
    seen: list[int] = []

    async def fake_payload(entry):
        seen.append(entry.row)
        return {
            "questions": [
                {
                    "question": "Czym różni się Spring Boot 2 od 3?",
                    "quote": "różnice między Spring Boot 2 i 3",
                }
            ],
            "people": [],
        }

    monkeypatch.setattr(imp, "_model_payload", fake_payload)
    plan = await imp.build_plan([_row(1, 7), _row(2, 7), _row(2, 8)])
    assert seen == [1]
    assert {(q["note_id"], q["job_id"]) for q in plan["questions"]} == {(1, 7)}
    assert {"note_id": 2, "reason": "niejednoznaczna rekrutacja"}.items() <= (
        plan["rejected"][0].items()
    )
    assert plan["notes"] == 2


def test_group_by_pair_drops_a_note_spread_over_several_pairs():
    """Plan sprzed poprawki: ta sama notatka przy dwóch parach nie trafia do
    żadnej — nie wiadomo, której rozmowy dotyczyła."""
    rows = [
        {"note_id": 1, "candidate_id": 5, "job_id": 7, "question": "Helm?"},
        {"note_id": 1, "candidate_id": 5, "job_id": 8, "question": "Helm?"},
        {"note_id": 2, "candidate_id": 5, "job_id": 8, "question": "Kafka?"},
    ]
    pairs = imp.group_by_pair(rows)
    assert (5, 7) not in pairs
    assert [q["note_id"] for q in pairs[(5, 8)]] == [2]


def test_skip_notes_accepts_note_and_job():
    notes, note_jobs = imp.parse_skip_notes("101, 102:7 ,")
    assert notes == frozenset({101})
    assert note_jobs == frozenset({(102, 7)})
    rows = [
        {"note_id": 102, "candidate_id": 5, "job_id": 7, "question": "Helm?"},
        {"note_id": 103, "candidate_id": 5, "job_id": 7, "question": "Kafka?"},
    ]
    pairs = imp.group_by_pair(rows, skip_note_jobs=note_jobs)
    assert [q["note_id"] for q in pairs[(5, 7)]] == [103]
    with pytest.raises(ValueError):
        imp.parse_skip_notes("abc")


async def test_build_plan_keeps_only_quoted_questions(monkeypatch):
    async def fake_payload(entry):
        return {
            "questions": [
                {
                    "question": "Czym różni się Spring Boot 2 od 3?",
                    "quote": "różnice między Spring Boot 2 i 3",
                },
                {"question": "Jak skalujesz Redisa?", "quote": "Redis w klastrze"},
            ],
            "people": [],
        }

    monkeypatch.setattr(imp, "_model_payload", fake_payload)
    note = imp.NoteRow(
        note_id=11,
        candidate_id=5,
        job_id=7,
        job_title="Java Developer",
        client_id=3,
        author_id=9,
        created_at=datetime(2026, 10, 15, 12, 0, tzinfo=timezone.utc),
        content=NOTE,
    )
    plan = await imp.build_plan([note])
    assert [q["question"] for q in plan["questions"]] == [
        "Czym różni się Spring Boot 2 od 3?"
    ]
    assert plan["questions"][0]["note_day"] == "2026-10-15"
    assert [r["reason"] for r in plan["rejected"]] == ["cytat spoza notatki"]


# ── Z bazą ──────────────────────────────────────────────────────────────────


async def _pair_with_note(*, note_text: str = NOTE) -> tuple[int, int, int, int, int]:
    from app.core.security import hash_password
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.note import Note

    tag = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        rec = User(
            email=f"noteq-{tag}@example.com",
            password_hash=hash_password(f"N0teq_{tag}!pw"),
            name=f"Noteq {tag}",
            role=UserRole.recruiter,
            roles=["recruiter"],
            is_active=True,
            profile_completed=True,
        )
        client = Client(name=f"NoteqClient-{tag}")
        db.add_all([rec, client])
        await db.flush()
        job = Job(
            title=f"NoteqJob-{tag}",
            status=JobStatus.published,
            client_id=client.id,
            recruiter_id=rec.id,
        )
        cand = Candidate(
            name="Ola",
            lastname=f"Notatka-{tag}",
            email=f"noteq-cand-{tag}@example.com",
            status=CandidateStatus.active,
        )
        db.add_all([job, cand])
        await db.flush()
        db.add(
            CandidateStage(
                candidate_id=cand.id,
                job_id=job.id,
                stage=PipelineStage.client_interview,
                moved_by=rec.id,
                moved_at=now - timedelta(days=3),
            )
        )
        note = Note(
            content=note_text, candidate_id=cand.id, job_id=job.id, author_id=rec.id
        )
        db.add(note)
        await db.flush()
        note.created_at = now - timedelta(days=2)
        # Notatka systemowa (bez autora) i notatka sprzed etapu — poza importem.
        db.add(
            Note(content=note_text, candidate_id=cand.id, job_id=job.id, author_id=None)
        )
        old = Note(
            content=note_text, candidate_id=cand.id, job_id=job.id, author_id=rec.id
        )
        db.add(old)
        await db.flush()
        old.created_at = now - timedelta(days=30)
        await db.commit()
        return job.id, cand.id, client.id, rec.id, note.id


def _plan(job_id: int, cand_id: int, client_id: int, rec_id: int, note_id: int) -> dict:
    day = (datetime.now(timezone.utc) - timedelta(days=2)).date().isoformat()
    base = {
        "note_id": note_id,
        "candidate_id": cand_id,
        "job_id": job_id,
        "job_title": "Java",
        "client_id": client_id,
        "author_id": rec_id,
        "note_day": day,
        "quote": "x",
    }
    return {
        "version": imp.PLAN_VERSION,
        "questions": [
            {**base, "question": "Czym różni się Spring Boot 2 od 3?"},
            {**base, "question": "Jak testujesz integrację z Kafką?"},
        ],
    }


async def test_candidate_notes_window():
    job_id, cand_id, _client, _rec, note_id = await _pair_with_note()
    async with AsyncSessionLocal() as db:
        notes = await imp.candidate_notes(db, days=30, now=datetime.now(timezone.utc))
    mine = [n for n in notes if n.candidate_id == cand_id and n.job_id == job_id]
    assert [n.note_id for n in mine] == [note_id]


async def test_apply_closes_the_gate_and_rollback_undoes_it():
    from app.models.app_setting import AppSetting

    # Paragon jest wspólny dla bazy shardu — cofnięcie liczy tylko ten test.
    async with AsyncSessionLocal() as db:
        setting = await db.get(AppSetting, imp.RECEIPT_KEY)
        if setting is not None:
            await db.delete(setting)
            await db.commit()
    job_id, cand_id, client_id, rec_id, note_id = await _pair_with_note()
    plan = _plan(job_id, cand_id, client_id, rec_id, note_id)
    async with AsyncSessionLocal() as db:
        assert (await missing_debrief(db, candidate_id=cand_id, job_id=job_id))[
            "event_id"
        ] is None
        receipt = await imp.apply_plan(db, plan)
        await db.commit()
    assert receipt["pairs"] == 1
    assert len(receipt["event_ids"]) == 1
    assert len(receipt["feedback_ids"]) == 1
    assert len(receipt["question_ids"]) == 2
    assert len(receipt["pin_ids"]) == 2

    async with AsyncSessionLocal() as db:
        assert await missing_debrief(db, candidate_id=cand_id, job_id=job_id) is None
        fb = await db.scalar(
            select(InterviewFeedback).where(
                InterviewFeedback.candidate_id == cand_id,
                InterviewFeedback.job_id == job_id,
                InterviewFeedback.feedback_source == FeedbackSource.candidate_side,
            )
        )
        assert fb.client_questions.splitlines() == [
            "Czym różni się Spring Boot 2 od 3?",
            "Jak testujesz integrację z Kafką?",
        ]
        assert fb.author_id == rec_id

        # Powtórka nic nie dubluje.
        again = await imp.apply_plan(db, plan)
        await db.commit()
    assert again["pairs"] == 0
    assert again["pairs_already_closed"] == 1

    async with AsyncSessionLocal() as db:
        counts = await imp.rollback(db)
        await db.commit()
    assert counts["events"] == 1 and counts["feedbacks"] == 1
    assert counts["questions"] == 2 and counts["pins"] == 2
    async with AsyncSessionLocal() as db:
        events = await db.scalar(
            select(func.count(CalendarEvent.id)).where(
                CalendarEvent.candidate_id == cand_id,
                CalendarEvent.event_type == EventType.client_interview,
            )
        )
        assert events == 0
        assert (
            await db.scalar(
                select(func.count(InterviewQuestion.id)).where(
                    InterviewQuestion.client_id == client_id
                )
            )
        ) == 0
        assert (
            await db.scalar(
                select(func.count(JobQuestion.id)).where(JobQuestion.job_id == job_id)
            )
        ) == 0
        assert (await missing_debrief(db, candidate_id=cand_id, job_id=job_id))[
            "event_id"
        ] is None


async def test_apply_respects_skipped_notes():
    job_id, cand_id, client_id, rec_id, note_id = await _pair_with_note()
    async with AsyncSessionLocal() as db:
        receipt = await imp.apply_plan(
            db,
            _plan(job_id, cand_id, client_id, rec_id, note_id),
            skip_notes=frozenset({note_id}),
        )
        await db.commit()
    assert receipt["pairs"] == 0
    assert receipt["event_ids"] == []
