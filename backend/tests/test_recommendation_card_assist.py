"""Karta rekomendacji z notatki i „Ułóż w zdanie” (0421, 06.10.2026).

Czyste reguły (bez bazy) + trasy `/api/recommendation-cards/note/*`
i `/phrase` z bazą (CI). Model jest podmieniany (`_call_model`).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.job import Job
from app.models.note import Note
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import UserRole
from app.schemas.champion import client_safe_screening
from app.services import note_kinds
from app.services import recommendation_card_assist as assist
from app.services.recommendation_card_rules import manual_value, merge_questions
from tests.test_recommendation_cards import _login, _seed_pair, _seed_user

QUESTIONS = [
    {"id": "q1", "question": "Jakie ma doświadczenie z Kafką?"},
    {"id": "q2", "question": "Dlaczego chce zmienić projekt?"},
]
QUESTION_TEXTS = {q["id"]: q["question"] for q in QUESTIONS}

NOTE = (
    "Rozmowa 06.10, Tomasz Wzorcowy, tel 600 100 200, tomasz@example.com\n"
    "stawka 165 netto b2b, niżej nie zejdzie, poprzednio miał 140\n"
    "wypow. miesiąc, start od listopada\n"
    "hybryda ok, max 2 dni w wawie\n"
    "eng B2 gada swobodnie o tech\n"
    "Narodowość: polska\n"
    "kafka 3 lata prod, eventy płatności, consumer groups\n"
    "projekt się kończy w 12, chce dłuższy kontrakt\n"
)


# ── bez bazy: reguła faktów ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sentence", "keywords", "problem"),
    [
        (
            "Kandydat od 3 lat pracuje z Kafką na produkcji przy zdarzeniach "
            "płatności i korzysta z consumer groups.",
            "kafka 3 lata prod, eventy płatności, consumer groups",
            None,
        ),
        ("Kandydat ma 6 lat doświadczenia w Javie.", "6y java", None),
        ("Kandydat ma 7 lat doświadczenia w Javie.", "6y java", "7"),
        ("Okres wypowiedzenia to miesiąc, od 1 listopada.", "1 mc", "listopada"),
        ("Kandydat zna Kubernetes i Dockera.", "docker", "Kubernetes"),
        ("Pracował dla ING i mBanku.", "banki ING mbank", None),
        ("Zna C++.", "java", "C++"),
        (
            "The candidate has 3 years of production experience with Kafka.",
            "kafka 3 lata prod",
            None,
        ),
    ],
)
def test_phrase_guard_rejects_only_new_facts(sentence, keywords, problem) -> None:
    assert assist.phrase_guard(sentence, keywords) == problem


@pytest.mark.parametrize(
    ("sentence", "problem"),
    [
        ("Kandydat pracował w Wipro.", "Wipro"),
        ("Kandydat zna Azure.", "Azure"),
        ("Kandydat pracował w Allegro.", "Allegro"),
        ("Kandydat zna Docker.", "Docker"),
        ("Kandydat zna Javę.", None),
    ],
)
def test_short_words_of_the_note_do_not_vouch_for_names(sentence, problem) -> None:
    """„w”, „a”, „do” z notatki nie potwierdzają nazw zaczynających się od nich."""
    note = (
        "Rozmowa. Kandydat szuka zmiany, pracuje w banku, zna Javę, a w wolnym "
        "czasie uczy się. Pisze do mnie z domu."
    )
    assert assist.phrase_guard(sentence, note) == problem


def test_question_text_counts_as_a_source() -> None:
    assert (
        assist.phrase_guard(
            "Kandydat pracuje z Kafką od 3 lat.", "3 lata", QUESTION_TEXTS["q1"]
        )
        is None
    )


def test_model_never_sees_nationality_or_contacts() -> None:
    text = assist.model_text(NOTE)
    assert "polska" not in text and "Narodowość" not in text
    assert "600 100 200" not in text and "tomasz@example.com" not in text
    assert "stawka 165" in text


def test_model_fields_need_a_quote_from_the_note() -> None:
    parsed = {
        "fields": {
            "english": {"value": "B2", "quote": "eng B2 gada swobodnie"},
            # Cytatu nie ma w notatce — halucynacja odpada.
            "location": {"value": "Kraków", "quote": "mieszka w Krakowie"},
            # Narodowość nigdy od modelu.
            "nationality": {"value": "polska", "quote": "polska"},
            "rate": {"value": "165 zł/h netto B2B", "quote": "stawka 165 netto b2b"},
        }
    }
    out = assist.validate_model_fields(parsed, note=NOTE)
    assert set(out) == {"english", "rate"}


def test_rate_number_must_stand_in_its_own_quote() -> None:
    parsed = {
        "fields": {
            # 140 jest w notatce, ale cytat mówi o 165 — stawka odpada.
            "rate": {"value": "140 zł/h", "quote": "stawka 165 netto b2b"},
        }
    }
    assert assist.validate_model_fields(parsed, note=NOTE) == {}


def test_model_answer_with_invented_fact_keeps_only_the_keywords() -> None:
    parsed = {
        "answers": [
            {
                "question_id": "q1",
                "quote": "kafka 3 lata prod",
                "sentence": "Kandydat od 5 lat pracuje z Kafką.",
            },
            {"question_id": "q9", "quote": "kafka", "sentence": "x"},
        ]
    }
    out = assist.validate_model_answers(parsed, note=NOTE, questions=QUESTION_TEXTS)
    assert set(out) == {"q1"}
    assert out["q1"]["sentence"] == "" and out["q1"]["problem"] == "5"


def test_rule_beats_the_model_and_unchanged_fields_are_marked() -> None:
    proposal = assist.build_proposal(
        note=NOTE,
        rule_fields={"rate": {"raw": "165 zł/h"}, "nationality": {"raw": "polska"}},
        rule_answers=[],
        model_fields={
            "rate": {"value": "160 zł/h", "quote": "x"},
            "english": {"value": "B2", "quote": "eng B2"},
        },
        model_answers={
            "q2": {
                "quote": "projekt się kończy w 12",
                "sentence": "Obecny projekt kończy się w grudniu.",
                "problem": "",
            }
        },
        current_fields={"english": {"raw": "B2", "source": "manual"}},
        questions=QUESTION_TEXTS,
        current_answers={},
    )
    by_key = {f["key"]: f for f in proposal["fields"]}
    assert by_key["rate"]["proposed"] == "165 zł/h"
    assert by_key["rate"]["origin"] == "note_rule"
    assert by_key["nationality"]["origin"] == "note_rule"
    assert by_key["english"]["changed"] is False
    (answer,) = proposal["answers"]
    assert answer["question_id"] == "q2" and answer["number"] == 2
    assert answer["keywords"] == "projekt się kończy w 12"


def test_phrases_follow_request_order_and_drop_new_facts() -> None:
    items = [
        {"key": "q1", "keywords": "kafka 3 lata", "question": ""},
        {"key": "recommendation", "keywords": "6y java banki", "question": ""},
        {"key": "q2", "keywords": "nudzi go utrzymanie", "question": ""},
    ]
    parsed = {
        "items": [
            {"key": "recommendation", "sentence": "Kandydat ma 9 lat w Javie."},
            {"key": "q1", "sentence": "Kandydat od 3 lat pracuje z Kafką."},
        ]
    }
    out = assist.validate_phrases(parsed, items)
    assert [o["key"] for o in out] == ["q1", "recommendation", "q2"]
    assert out[0]["sentence"] == "Kandydat od 3 lat pracuje z Kafką."
    assert out[1] == {"key": "recommendation", "sentence": None, "problem": "9"}
    assert out[2] == {"key": "q2", "sentence": None, "problem": None}


def test_card_value_keeps_its_origin_and_keywords() -> None:
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    value = manual_value(
        "recommendation",
        "Kandydat ma 6 lat w Javie.",
        user_id=1,
        now=now,
        provenance={"origin": "phrased", "keywords": "6y java", "note_id": 7},
    )
    assert value["origin"] == "phrased" and value["keywords"] == "6y java"
    assert value["note_id"] == 7
    # Nieznane pochodzenie jest pomijane.
    plain = manual_value("rate", "150", user_id=1, now=now, provenance={"origin": "x"})
    assert "origin" not in plain


def test_merged_questions_carry_the_sheet_origin() -> None:
    merged = merge_questions(
        QUESTION_TEXTS,
        [
            {
                "question_id": "q1",
                "response": "Kandydat od 3 lat pracuje z Kafką.",
                "origin": "phrased",
                "keywords": "kafka 3 lata",
            }
        ],
        [],
    )
    assert merged[0]["origin"] == "phrased" and merged[0]["keywords"] == "kafka 3 lata"
    assert "origin" not in merged[1]


def test_keywords_never_reach_the_client() -> None:
    safe = client_safe_screening(
        {
            "answers": [
                {
                    "question_id": "q1",
                    "response": "Zdanie.",
                    "origin": "phrased",
                    "keywords": "hasła",
                }
            ]
        }
    )
    assert safe["answers"] == [{"question_id": "q1", "response": "Zdanie."}]


# ── z bazą ───────────────────────────────────────────────────────────────────


@pytest.fixture
def assist_on(monkeypatch):
    monkeypatch.setattr(settings, "RECOMMENDATION_CARD_ASSIST_ENABLED", True)


async def _world() -> tuple[int, int]:
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
            )
        )
        await db.commit()
    return candidate_id, job_id


def _fake_model(response: dict, captured: list[str] | None = None):
    def fake(feature, system, prompt):  # noqa: ANN001
        if captured is not None:
            captured.append(prompt)
        return json.dumps(response)

    return fake


@pytest.mark.asyncio
async def test_routes_are_hidden_when_the_switch_is_off(app_client: AsyncClient):
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    resp = await app_client.post(
        "/api/recommendation-cards/note/read",
        json={"candidate_id": candidate_id, "job_id": job_id, "text": NOTE},
        headers=headers,
    )
    assert resp.status_code == 404
    card = await app_client.get(
        f"/api/recommendation-cards?candidate_id={candidate_id}&job_id={job_id}",
        headers=headers,
    )
    assert card.json()["assist_enabled"] is False


@pytest.mark.asyncio
async def test_read_proposes_without_writing(
    app_client: AsyncClient, assist_on, monkeypatch
):
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    prompts: list[str] = []
    monkeypatch.setattr(
        assist,
        "_call_model",
        _fake_model(
            {
                "fields": {
                    "english": {"value": "B2", "quote": "eng B2 gada swobodnie"},
                    "rate": {
                        "value": "165 zł/h netto B2B",
                        "quote": "stawka 165 netto b2b",
                    },
                },
                "answers": [
                    {
                        "question_id": "q1",
                        "quote": "kafka 3 lata prod",
                        "sentence": "Kandydat od 3 lat pracuje z Kafką na produkcji.",
                    }
                ],
            },
            prompts,
        ),
    )

    resp = await app_client.post(
        "/api/recommendation-cards/note/read",
        json={"candidate_id": candidate_id, "job_id": job_id, "text": NOTE},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    by_key = {f["key"]: f for f in body["fields"]}
    assert by_key["nationality"]["origin"] == "note_rule"
    assert by_key["english"]["origin"] == "note_ai"
    assert body["answers"][0]["sentence"].startswith("Kandydat od 3 lat")
    assert "polska" not in prompts[0] and "600 100 200" not in prompts[0]
    async with AsyncSessionLocal() as db:
        notes = (
            await db.scalars(select(Note).where(Note.candidate_id == candidate_id))
        ).all()
        assert notes == []


@pytest.mark.asyncio
async def test_model_failure_still_returns_the_rule_reading(
    app_client: AsyncClient, assist_on, monkeypatch
):
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    def boom(*_args):  # noqa: ANN002
        raise RuntimeError("model down")

    monkeypatch.setattr(assist, "_call_model", boom)
    resp = await app_client.post(
        "/api/recommendation-cards/note/read",
        json={"candidate_id": candidate_id, "job_id": job_id, "text": NOTE},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["available"] is False
    assert [f["key"] for f in body["fields"]] == ["nationality"]


@pytest.mark.asyncio
async def test_apply_writes_note_card_and_sheet(app_client: AsyncClient, assist_on):
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)

    resp = await app_client.post(
        "/api/recommendation-cards/note/apply",
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "text": NOTE,
            "source_name": "notatka.docx",
            "fields": {"english": "B2", "availability": "miesiąc, od listopada"},
            "field_origins": {"english": "note_ai", "availability": "note_ai"},
            "answers": [
                {
                    "question_id": "q1",
                    "response": "Kandydat od 3 lat pracuje z Kafką na produkcji.",
                    "keywords": "kafka 3 lata prod",
                    "origin": "phrased",
                }
            ],
        },
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["fields"]["english"]["origin"] == "note_ai"
    q1 = next(q for q in body["questions"] if q["question_id"] == "q1")
    assert q1["origin"] == "phrased" and q1["keywords"] == "kafka 3 lata prod"
    async with AsyncSessionLocal() as db:
        note = await db.scalar(select(Note).where(Note.candidate_id == candidate_id))
        # Zwykła notatka, nie karta — projekcja nie dopisze odznaczonych pól.
        assert note.kind == note_kinds.HUMAN
        assert note.content.startswith("Notatka z rozmowy (plik: notatka.docx)")
        assert body["fields"]["english"]["note_id"] == note.id
        stage = await db.scalar(
            select(CandidateStage).where(CandidateStage.candidate_id == candidate_id)
        )
        (answer,) = stage.screening_answers["answers"]
        assert answer["origin"] == "phrased"
        assert answer["keywords"] == "kafka 3 lata prod"
        assert answer["question_text"] == QUESTIONS[0]["question"]


@pytest.mark.asyncio
async def test_apply_refuses_unknown_question(app_client: AsyncClient, assist_on):
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    resp = await app_client.post(
        "/api/recommendation-cards/note/apply",
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "text": NOTE,
            "answers": [{"question_id": "q9", "response": "x"}],
        },
        headers=headers,
    )
    assert resp.status_code == 422
    async with AsyncSessionLocal() as db:
        assert (
            await db.scalar(select(Note).where(Note.candidate_id == candidate_id))
        ) is None


@pytest.mark.asyncio
async def test_phrase_route_uses_the_guard(
    app_client: AsyncClient, assist_on, monkeypatch
):
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    monkeypatch.setattr(
        assist,
        "_call_model",
        _fake_model(
            {"items": [{"key": "q2", "sentence": "Projekt kończy się w maju."}]}
        ),
    )
    resp = await app_client.post(
        "/api/recommendation-cards/phrase",
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "items": [{"key": "q2", "keywords": "projekt się kończy, chce dłuższy"}],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["language"] == "pl"
    assert body["items"] == [{"key": "q2", "sentence": None, "problem": "maju"}]


@pytest.mark.asyncio
async def test_card_put_accepts_a_phrased_description(
    app_client: AsyncClient, assist_on
):
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    resp = await app_client.put(
        "/api/recommendation-cards",
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "fields": {"recommendation": "Kandydat ma 6 lat w Javie."},
            "origins": {"recommendation": {"origin": "phrased", "keywords": "6y java"}},
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    field = resp.json()["fields"]["recommendation"]
    assert field["origin"] == "phrased" and field["keywords"] == "6y java"

    refused = await app_client.put(
        "/api/recommendation-cards",
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "fields": {"rate": "150"},
            "origins": {"rate": {"origin": "phrased", "keywords": "150"}},
        },
        headers=headers,
    )
    assert refused.status_code == 422


@pytest.mark.asyncio
async def test_apply_answers_even_when_score_marking_fails(
    app_client: AsyncClient, assist_on, monkeypatch
):
    """Po rollbacku (nieudane oznaczenie wyników) odpowiedź nie kończy się 500."""
    from app.services import match_score_cache

    async def boom(*_args, **_kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("cache down")

    monkeypatch.setattr(match_score_cache, "mark_stale_for_candidate", boom)
    candidate_id, job_id = await _world()
    _, email, password = await _seed_user(UserRole.recruiter)
    headers = await _login(app_client, email, password)
    resp = await app_client.post(
        "/api/recommendation-cards/note/apply",
        json={
            "candidate_id": candidate_id,
            "job_id": job_id,
            "text": NOTE,
            "answers": [{"question_id": "q1", "response": "Kafka od 3 lat."}],
        },
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["questions"][0]["answer"] == "Kafka od 3 lat."
