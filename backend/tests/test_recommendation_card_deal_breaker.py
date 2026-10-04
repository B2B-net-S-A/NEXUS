"""„Odpada, gdy…” na karcie rekomendacji (04.10.2026).

Czysta reguła + trasa `POST /api/recommendation-cards/deal-breaker` i odczyt
w „Przesuń dalej” z bazą (CI).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services import move_requirements
from app.services.recommendation_card_rules import attach_deal_breakers
from tests.test_recommendation_cards import _login, _seed_pair, _seed_user

QUESTIONS = [
    {
        "id": "q1",
        "question": "Czy pracujesz z Kafką?",
        "ideal_answer": "produkcyjnie",
        "deal_breaker": "",
    },
    {
        "id": "q2",
        "question": "Ile dni w biurze akceptujesz?",
        "ideal_answer": "2",
        "deal_breaker": "Tylko praca zdalna.",
    },
]


# ── bez bazy ─────────────────────────────────────────────────────────────────


def test_attach_adds_question_id_condition_and_hit() -> None:
    merged = [
        {"number": 1, "question": "A", "answer": "", "source": None},
        {"number": 2, "question": "B", "answer": "zdalnie", "source": "sheet"},
    ]
    sheet = [{"question_id": "q2", "response": "zdalnie", "deal_breaker_hit": True}]
    out = attach_deal_breakers(merged, QUESTIONS, sheet)
    assert [
        (q["question_id"], q["deal_breaker"], q["deal_breaker_hit"]) for q in out
    ] == [
        ("q1", None, False),
        ("q2", "Tylko praca zdalna.", True),
    ]
    # Wejście nie jest zmieniane.
    assert "question_id" not in merged[0]


def test_questions_only_from_the_note_cannot_carry_a_hit() -> None:
    merged = [{"number": 1, "question": "Z notatki?", "answer": "x", "source": "note"}]
    (item,) = attach_deal_breakers(merged, [], [])
    assert item["question_id"] is None
    assert item["deal_breaker"] is None and item["deal_breaker_hit"] is False


# ── z bazą ───────────────────────────────────────────────────────────────────


async def _world(*, with_sheet: bool = True) -> tuple[int, int]:
    candidate_id, job_id = await _seed_pair()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.champion_profile = {"screening_questions": QUESTIONS}
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage.screening,
                moved_at=datetime.now(timezone.utc) - timedelta(minutes=5),
                # Arkusz z odpowiedzią na inne pytanie — zaznaczenie q2 dopisuje
                # pozycję do istniejącego arkusza.
                screening_answers=(
                    {"answers": [{"question_id": "q1", "response": "tak"}]}
                    if with_sheet
                    else None
                ),
            )
        )
        await db.commit()
    return candidate_id, job_id


async def _post(client: AsyncClient, headers, candidate_id, job_id, qid, hit):
    return await client.post(
        "/api/recommendation-cards/deal-breaker",
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "question_id": qid,
            "hit": hit,
        },
        headers=headers,
    )


@pytest.mark.asyncio
async def test_marking_a_hit_writes_the_pair_sheet_and_warns_in_the_move(
    app_client: AsyncClient,
) -> None:
    candidate_id, job_id = await _world()
    user_id, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    resp = await _post(app_client, headers, candidate_id, job_id, "q2", True)

    assert resp.status_code == 200, resp.text
    q2 = next(q for q in resp.json()["questions"] if q["question_id"] == "q2")
    assert q2["deal_breaker_hit"] is True
    assert q2["deal_breaker"] == "Tylko praca zdalna."
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )
        answers = row.screening_answers["answers"]
        q2_answer = next(a for a in answers if a["question_id"] == "q2")
        assert q2_answer == {
            **q2_answer,
            "response": "",
            "deal_breaker_hit": True,
            "question_text": "Ile dni w biurze akceptujesz?",
        }
        activity = await db.scalar(
            select(Activity).where(
                Activity.action == "screening_deal_breaker_marked",
                Activity.entity_id == row.id,
            )
        )
        assert activity is not None
        assert activity.details == {
            "candidate_id": candidate_id,
            "job_id": job_id,
            "question_id": "q2",
            "hit": True,
        }

        facts = await move_requirements.load_pair_facts(
            db,
            candidate=await db.get(Candidate, candidate_id),
            job=await db.get(Job, job_id),
            user=await db.get(User, user_id),
        )
    assert facts.deal_breaker_hits[0]["deal_breaker"] == "Tylko praca zdalna."
    keys = [
        i["key"]
        for i in move_requirements.build_requirements(facts, "verified")["items"]
    ]
    assert "deal_breaker" in keys

    cleared = await _post(app_client, headers, candidate_id, job_id, "q2", False)
    assert cleared.status_code == 200, cleared.text
    q2 = next(q for q in cleared.json()["questions"] if q["question_id"] == "q2")
    assert q2["deal_breaker_hit"] is False


@pytest.mark.asyncio
async def test_clearing_a_hit_that_never_existed_writes_nothing(
    app_client: AsyncClient,
) -> None:
    candidate_id, job_id = await _world(with_sheet=False)
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    resp = await _post(app_client, headers, candidate_id, job_id, "q1", False)

    assert resp.status_code == 200, resp.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateStage).where(CandidateStage.candidate_id == candidate_id)
        )
        assert row.screening_answers is None


@pytest.mark.asyncio
async def test_unknown_question_and_viewer_are_refused(app_client: AsyncClient) -> None:
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    assert (
        await _post(app_client, headers, candidate_id, job_id, "q9", True)
    ).status_code == 422

    _, v_email, v_password = await _seed_user(UserRole.user)
    viewer = await _login(app_client, v_email, v_password)
    assert (
        await _post(app_client, viewer, candidate_id, job_id, "q2", True)
    ).status_code == 403


@pytest.mark.asyncio
async def test_pair_without_a_stage_row_gets_409(app_client: AsyncClient) -> None:
    candidate_id, job_id = await _seed_pair()
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        job.champion_profile = {"screening_questions": QUESTIONS}
        await db.commit()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    resp = await _post(app_client, headers, candidate_id, job_id, "q2", True)

    assert resp.status_code == 409, resp.text


@pytest.mark.asyncio
async def test_hit_without_any_answer_is_refused_so_an_empty_sheet_never_counts(
    app_client: AsyncClient,
) -> None:
    """Bez arkusza pary zapis byłby pustym arkuszem, który zaliczałby wymóg
    „Arkusz screeningu” — odmawiamy (odpowiedzi z notatek do arkusza nie
    trafiają)."""
    candidate_id, job_id = await _world(with_sheet=False)
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    resp = await _post(app_client, headers, candidate_id, job_id, "q2", True)

    assert resp.status_code == 409, resp.text
    async with AsyncSessionLocal() as db:
        row = await db.scalar(
            select(CandidateStage).where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
        )
        assert not row.screening_answers
