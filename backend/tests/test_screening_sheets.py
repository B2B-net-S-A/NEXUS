"""Odpowiedzi ze screeningu widoczne w profilu kandydata (02.10.2026).

Zgłoszenie testerki: po przejściu wszystkich etapów w profilu kandydata nie
było widać, co odpowiedział na pytania screeningowe — arkusz Championa żył
wyłącznie przy wierszu etapu. Tu:

* odpowiedź niesie własny tekst pytania (identyfikatory pytań są pozycyjne),
* zapis bez zmiany treści nie podmienia „kto i kiedy”,
* `GET /api/candidates/{id}/screening-answers` — jedna rozmowa na rekrutację.
"""

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.schemas.champion import ScreeningAnswers, client_safe_screening
from app.services import screening_sheets as svc
from tests.test_screening_reassign import _seed_recruiter

QUESTIONS = {"q1": "Czy pracowałeś na mikroserwisach?", "q2": "Od kiedy dostępny?"}
NOW = datetime(2026, 10, 2, 10, 0, tzinfo=timezone.utc)


def _sheet(*answers: dict, **extra) -> ScreeningAnswers:
    return ScreeningAnswers.model_validate({"answers": list(answers), **extra})


def _stamp(sheet: ScreeningAnswers, previous=None, questions=QUESTIONS, user_id=5):
    return svc.stamp_sheet(
        sheet, questions=questions, previous=previous, user_id=user_id, now=NOW
    )


# ── tekst pytań ──────────────────────────────────────────────────────────────


def test_question_texts_read_any_profile_shape() -> None:
    profile = {
        "screening_questions": [
            {"id": "q1", "question": "  Ile lat z Kafką? "},
            {"id": "", "question": "bez id"},
            {"id": "q3", "question": ""},
            "nie słownik",
        ]
    }
    assert svc.question_texts(profile) == {"q1": "Ile lat z Kafką?"}
    assert svc.question_texts(None) == {}
    assert svc.question_texts({"screening_questions": "zepsute"}) == {}


def test_first_save_stamps_question_text_author_and_time() -> None:
    sheet = _stamp(
        _sheet(
            # Tekst pytania z żądania jest ignorowany — stempluje serwer.
            {"question_id": "q1", "response": "Tak", "question_text": "podmienione"},
            {"question_id": "q9", "response": "pytanie spoza profilu"},
        )
    )
    assert [a.question_text for a in sheet.answers] == [QUESTIONS["q1"], None]
    assert sheet.answered_at == NOW and sheet.answered_by == 5


def test_unchanged_answer_keeps_the_question_it_was_given_for() -> None:
    """Identyfikatory pytań są pozycyjne: po edycji profilu „q1” znaczy co
    innego, a kandydat odpowiadał na tamto pytanie."""
    saved = _stamp(
        _sheet(
            {"question_id": "q1", "response": "Tak, 3 lata."},
            {"question_id": "q2", "response": "Od listopada"},
        )
    ).model_dump(mode="json")
    edited_profile = {
        "q1": "Jaki masz okres wypowiedzenia?",
        "q2": "Od kiedy możesz zacząć?",
    }
    later = _stamp(
        _sheet(
            {"question_id": "q1", "response": " Tak, 3 lata. "},
            {"question_id": "q2", "response": "Od grudnia"},
        ),
        previous=saved,
        questions=edited_profile,
        user_id=9,
    )
    assert later.answers[0].question_text == QUESTIONS["q1"]
    # Zmieniona odpowiedź dotyczy pytania w dzisiejszym brzmieniu.
    assert later.answers[1].question_text == "Od kiedy możesz zacząć?"


def test_saving_without_changes_keeps_who_and_when() -> None:
    """Ponowny zapis po ruchu karty nie może podmienić autora rozmowy."""
    first_time = datetime(2026, 9, 20, 9, 0, tzinfo=timezone.utc)
    saved = svc.stamp_sheet(
        _sheet({"question_id": "q1", "response": "Tak"}, overall_fit="fit", notes="ok"),
        questions=QUESTIONS,
        previous=None,
        user_id=3,
        now=first_time,
    ).model_dump(mode="json")

    same = _stamp(
        _sheet({"question_id": "q1", "response": "Tak"}, overall_fit="fit", notes="ok"),
        previous=saved,
        user_id=9,
    )
    assert (same.answered_at, same.answered_by) == (first_time, 3)

    changed = _stamp(
        _sheet(
            {"question_id": "q1", "response": "Tak"}, overall_fit="miss", notes="ok"
        ),
        previous=saved,
        user_id=9,
    )
    assert (changed.answered_at, changed.answered_by) == (NOW, 9)


def test_unreadable_previous_sheet_counts_as_no_previous() -> None:
    sheet = _stamp(
        _sheet({"question_id": "q1", "response": "Tak"}),
        previous={"answers": [{"brak": "question_id"}]},
    )
    assert sheet.answers[0].question_text == QUESTIONS["q1"]
    assert sheet.answered_at == NOW


def test_with_question_texts_fills_older_sheets_only() -> None:
    sheet = {
        "answers": [
            {
                "question_id": "q1",
                "response": "Tak",
                "question_text": "Zapisane pytanie",
            },
            {"question_id": "q2", "response": "Od listopada"},
            {"question_id": "q7", "response": "pytanie usunięte z profilu"},
            "zepsuty wpis",
        ],
        "notes": "x",
    }
    out = svc.with_question_texts(sheet, QUESTIONS)
    assert [a.get("question_text") for a in out["answers"][:3]] == [
        "Zapisane pytanie",
        QUESTIONS["q2"],
        None,
    ]
    assert out["answers"][3] == "zepsuty wpis" and out["notes"] == "x"
    # Wejście nietknięte; brak arkusza przechodzi bez zmian.
    assert "question_text" not in sheet["answers"][1]
    assert svc.with_question_texts(None, QUESTIONS) is None


def test_sheet_size_is_bounded_at_the_input() -> None:
    """Odpowiedzi pokazuje profil i czyta je Luna — arkusz nie może być dowolnie duży."""
    from pydantic import ValidationError

    from app.schemas.champion import SCREENING_ANSWERS_MAX, SCREENING_TEXT_MAX_CHARS

    fits = {"question_id": "q1", "response": "x" * SCREENING_TEXT_MAX_CHARS}
    assert ScreeningAnswers.model_validate(
        {
            "answers": [fits] * SCREENING_ANSWERS_MAX,
            "notes": "y" * SCREENING_TEXT_MAX_CHARS,
        }
    )
    for payload in (
        {
            "answers": [
                {"question_id": "q1", "response": "x" * (SCREENING_TEXT_MAX_CHARS + 1)}
            ]
        },
        {"answers": [fits] * (SCREENING_ANSWERS_MAX + 1)},
        {"answers": [], "notes": "y" * (SCREENING_TEXT_MAX_CHARS + 1)},
    ):
        try:
            ScreeningAnswers.model_validate(payload)
        except ValidationError:
            continue
        raise AssertionError("arkusz ponad limit został przyjęty")


def test_question_text_does_not_reach_the_client() -> None:
    sheet = _stamp(_sheet({"question_id": "q1", "response": "Tak"})).model_dump(
        mode="json"
    )
    safe = client_safe_screening(sheet)
    assert safe["answers"] == [
        {"question_id": "q1", "response": "Tak", "deal_breaker_hit": False}
    ]


# ── rozmowy kandydata (baza) ─────────────────────────────────────────────────


async def _seed_conversations(author_id: int) -> dict:
    """Kandydat z rozmowami w dwóch rekrutacjach i jedną rekrutacją bez arkusza."""
    from app.models.candidate import Candidate, CandidateStatus
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    tag = uuid.uuid4().hex[:6]
    async with AsyncSessionLocal() as db:
        cli = Client(name=f"SheetsClient-{tag}")
        cand = Candidate(
            name="Sheet",
            lastname=f"Answers-{tag}",
            email=f"sheets-cand-{tag}@example.com",
            status=CandidateStatus("active"),
        )
        db.add_all([cli, cand])
        await db.flush()

        def job(title: str) -> Job:
            return Job(
                title=f"{title} {tag}",
                status=JobStatus.published,
                client_id=cli.id,
                champion_profile={
                    "screening_questions": [
                        {"id": "q1", "question": "Czy pracowałeś na mikroserwisach?"},
                        {"id": "q2", "question": "Od kiedy dostępny?"},
                    ]
                },
            )

        older, newer, empty = job("Older"), job("Newer"), job("Empty")
        db.add_all([older, newer, empty])
        await db.flush()

        def row(
            job_id: int, when: datetime, code: PipelineStage, answers
        ) -> CandidateStage:
            return CandidateStage(
                candidate_id=cand.id,
                job_id=job_id,
                stage=code,
                moved_at=when,
                screening_answers=answers,
            )

        older_sheet = {
            "answers": [
                {"question_id": "q1", "response": "Tak, 3 lata."},
                {"question_id": "q2", "response": "", "skipped": True},
            ],
            "overall_fit": "fit",
            "notes": "Dobra komunikacja.",
            "internal_note": "pominięte — przepięcie",
            "answered_at": "2026-08-14T09:00:00+00:00",
            "answered_by": author_id,
        }
        newer_sheet = {
            "answers": [
                {
                    "question_id": "q1",
                    "question_text": "Pytanie z chwili rozmowy",
                    "response": "Głównie monolit.",
                    "deal_breaker_hit": True,
                }
            ],
            "experience_checks": [
                {
                    "kind": "domains",
                    "name": "Bankowość",
                    "status": "confirmed",
                    "note": "2 lata",
                }
            ],
            "overall_fit": "miss",
            "answered_at": "2026-09-20T09:00:00+00:00",
        }
        db.add_all(
            [
                # Arkusz jest kopiowany przy ruchu — rekrutację reprezentuje
                # najnowszy WYPEŁNIONY wiersz, a pusty wiersz po nim go nie zasłania.
                row(
                    older.id,
                    datetime(2026, 8, 14, tzinfo=timezone.utc),
                    PipelineStage.screening,
                    {"answers": [{"question_id": "q1", "response": "stara wersja"}]},
                ),
                row(
                    older.id,
                    datetime(2026, 8, 20, tzinfo=timezone.utc),
                    PipelineStage.verified,
                    older_sheet,
                ),
                row(
                    older.id,
                    datetime(2026, 8, 25, tzinfo=timezone.utc),
                    PipelineStage.cv_sent,
                    {"answers": []},
                ),
                row(
                    newer.id,
                    datetime(2026, 9, 20, tzinfo=timezone.utc),
                    PipelineStage.screening,
                    newer_sheet,
                ),
                row(
                    empty.id,
                    datetime(2026, 9, 25, tzinfo=timezone.utc),
                    PipelineStage.new,
                    None,
                ),
            ]
        )
        await db.commit()
        return {
            "candidate_id": cand.id,
            "older_id": older.id,
            "newer_id": newer.id,
            "client_name": cli.name,
        }


async def test_candidate_conversations_one_per_job_newest_first(
    app_client: AsyncClient,
) -> None:
    _headers, author_id = await _seed_recruiter(app_client)
    seed = await _seed_conversations(author_id)
    async with AsyncSessionLocal() as db:
        conversations = await svc.candidate_conversations(
            db, candidate_id=seed["candidate_id"]
        )
        without_newer = await svc.candidate_conversations(
            db, candidate_id=seed["candidate_id"], exclude_job_id=seed["newer_id"]
        )
    assert [c["job_id"] for c in conversations] == [seed["newer_id"], seed["older_id"]]
    assert [c["job_id"] for c in without_newer] == [seed["older_id"]]
    newer, older = conversations
    assert newer["client_name"] == seed["client_name"]
    assert newer["overall_fit"] == "miss" and newer["match_percent"] == 0.0
    assert newer["answers"][0]["question_text"] == "Pytanie z chwili rozmowy"
    assert newer["answered_by_name"] is None
    # Starsza rozmowa: wiersz z 20.08 (wypełniony), nie pusty z 25.08.
    assert older["answers"][0]["response"] == "Tak, 3 lata."
    assert older["answers"][0]["question_text"] == "Czy pracowałeś na mikroserwisach?"
    assert older["answered_by_name"] == "Reassign Recruiter"
    assert older["answered_at"] == datetime(2026, 8, 14, 9, 0, tzinfo=timezone.utc)


async def test_profile_endpoint_returns_the_conversations(
    app_client: AsyncClient,
) -> None:
    headers, author_id = await _seed_recruiter(app_client)
    seed = await _seed_conversations(author_id)
    resp = await app_client.get(
        f"/api/candidates/{seed['candidate_id']}/screening-answers", headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidate_id"] == seed["candidate_id"]
    newer, older = body["conversations"]
    assert newer["job_id"] == seed["newer_id"]
    assert newer["job_title"].startswith("Newer ")
    assert newer["answers"] == [
        {
            "question_id": "q1",
            "question_text": "Pytanie z chwili rozmowy",
            "response": "Głównie monolit.",
            "deal_breaker_hit": True,
            "skipped": False,
            # 0421: pochodzenie odpowiedzi (plakietka „zdanie z haseł”).
            "origin": "manual",
            "keywords": None,
        }
    ]
    assert newer["experience_checks"] == [
        {
            "kind": "domains",
            "name": "Bankowość",
            "status": "confirmed",
            "note": "2 lata",
        }
    ]
    assert older["notes"] == "Dobra komunikacja."
    assert older["internal_note"] == "pominięte — przepięcie"
    assert older["answers"][1]["skipped"] is True
    assert older["answered_by_name"] == "Reassign Recruiter"

    missing = await app_client.get(
        "/api/candidates/2000000000/screening-answers", headers=headers
    )
    assert missing.status_code == 404
    # Identyfikator spoza zakresu kolumny to błąd wejścia, nie błąd bazy.
    too_big = await app_client.get(
        "/api/candidates/99999999999/screening-answers", headers=headers
    )
    assert too_big.status_code == 422


async def test_saving_the_sheet_makes_it_visible_in_the_profile(
    app_client: AsyncClient,
) -> None:
    """Cała droga ze zgłoszenia: rekruter wypełnia arkusz na Tablicy, a potem
    widzi odpowiedzi w profilu — także po zmianie pytań w profilu Championa."""
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage

    headers, author_id = await _seed_recruiter(app_client)
    seed = await _seed_conversations(author_id)
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select

        stage_id = await db.scalar(
            select(CandidateStage.id)
            .where(
                CandidateStage.candidate_id == seed["candidate_id"],
                CandidateStage.job_id == seed["newer_id"],
            )
            .limit(1)
        )
    saved = await app_client.post(
        f"/api/pipeline/stages/{stage_id}/screening",
        headers=headers,
        json={
            "answers": [
                {
                    "question_id": "q1",
                    "response": "Tak, dwa projekty.",
                    "question_text": "x",
                },
                {"question_id": "q2", "response": "Od listopada"},
            ],
            "overall_fit": "fit",
        },
    )
    assert saved.status_code == 200, saved.text
    stored = saved.json()["screening_answers"]
    assert [a["question_text"] for a in stored["answers"]] == [
        "Czy pracowałeś na mikroserwisach?",
        "Od kiedy dostępny?",
    ]
    assert stored["answered_by"] == author_id

    # Arkusz ponad limit albo z nieznaną wartością to czytelna odmowa (422),
    # a zapisany arkusz zostaje nietknięty.
    for bad in (
        {"answers": [{"question_id": "q1", "response": "x" * 10_001}]},
        {"answers": [], "overall_fit": "świetny"},
    ):
        refused = await app_client.post(
            f"/api/pipeline/stages/{stage_id}/screening", headers=headers, json=bad
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"].startswith("Arkusz screeningu")
    kept = await app_client.get(
        f"/api/pipeline/stages/{stage_id}/screening", headers=headers
    )
    assert kept.json()["screening_answers"]["answers"][0]["response"] == (
        "Tak, dwa projekty."
    )

    # Delivery Lead zmienia pytania w profilu — identyfikatory zostają te same.
    async with AsyncSessionLocal() as db:
        job = await db.get(Job, seed["newer_id"])
        job.champion_profile = {
            "screening_questions": [{"id": "q1", "question": "Zupełnie inne pytanie"}]
        }
        await db.commit()

    sheet = await app_client.get(
        f"/api/pipeline/stages/{stage_id}/screening", headers=headers
    )
    assert sheet.status_code == 200, sheet.text
    assert sheet.json()["screening_answers"]["answers"][0]["question_text"] == (
        "Czy pracowałeś na mikroserwisach?"
    )
    profile = await app_client.get(
        f"/api/candidates/{seed['candidate_id']}/screening-answers", headers=headers
    )
    newest = profile.json()["conversations"][0]
    assert newest["job_id"] == seed["newer_id"]
    assert [(a["question_text"], a["response"]) for a in newest["answers"]] == [
        ("Czy pracowałeś na mikroserwisach?", "Tak, dwa projekty."),
        ("Od kiedy dostępny?", "Od listopada"),
    ]
    assert newest["answered_by_name"] == "Reassign Recruiter"
