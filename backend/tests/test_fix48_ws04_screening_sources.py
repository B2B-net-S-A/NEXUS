"""Materiał ze screeningu dla generatora i kontroli CV — poprawki po audycie 13.10.2026.

* pkt 10: odpowiedzi kandydata i notatka ze screeningu szły do generatora bez
  filtra stawek i dostępności;
* drobne: odpowiedź łączona z bieżącym pytaniem Championa po numerze `qN`,
  a nie z zapisanym tekstem pytania (`question_text`);
* pkt 12: kontrola AI po ręcznej edycji CV dostawała linie „P:” (pytania
  rekrutera) jak fakty — generator je wycina.

Dane fikcyjne.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import cv_review_sources
from app.services.cv_generator_b2b import standalone_service as svc


def _answers(response: str, question_text: str | None = None) -> dict:
    answer = {"question_id": "q1", "response": response}
    if question_text is not None:
        answer["question_text"] = question_text
    return {"answers": [answer]}


_CURRENT_QUESTIONS = [{"id": "q1", "question": "Czy zna Pan Terraform?"}]


def test_candidate_answer_loses_rate_and_availability_but_keeps_the_fact():
    text = svc._format_candidate_answers(
        _answers("Tak, 4 lata z Kafką. Stawka 150 B2B, dostępny od zaraz."),
        _CURRENT_QUESTIONS,
    )
    assert "Tak, 4 lata z Kafką." in text
    assert "150" not in text and "zaraz" not in text


def test_answer_that_was_only_money_drops_with_its_question():
    text = svc._format_candidate_answers(
        _answers("Chce 160 na B2B"), [{"id": "q1", "question": "Oczekiwania?"}]
    )
    assert text == ""


def test_answer_is_paired_with_the_saved_question_not_the_current_qn():
    # Profil Championa zmieniono po rozmowie: dziś `q1` to inne pytanie.
    text = svc._format_candidate_answers(
        _answers("Tak, 3 lata.", question_text="Czy pracował Pan z Kafką?"),
        _CURRENT_QUESTIONS,
    )
    assert text == "P: Czy pracował Pan z Kafką?\nO: Tak, 3 lata."
    assert "Terraform" not in text


def test_screening_note_fields_lose_money_and_keep_the_skill():
    note = SimpleNamespace(
        personality_notes="Komunikatywny, chce 22k.",
        verified_skills=[{"skill": "Kafka", "level": "senior", "notes": "rate 140"}],
    )
    text = svc._format_screening_note(note)
    assert "Komunikatywny" in text and "Kafka (senior)" in text
    assert "22k" not in text and "140" not in text


@pytest.mark.asyncio
async def test_generator_material_has_no_rates_from_answers_or_screening_note():
    db = AsyncMock()
    note = SimpleNamespace(
        personality_notes="Spokojny. Zarabia 18k.",
        verified_skills=[{"skill": "Java", "level": "", "notes": ""}],
    )
    # Kolejność odczytów: notatki ze screeningu, notatki kandydata; karta
    # rekomendacji i pierwszy ruch pary przez `scalar`.
    db.scalars.side_effect = [
        SimpleNamespace(all=lambda: [note]),
        SimpleNamespace(all=lambda: []),
    ]
    db.scalar.side_effect = [None, None]
    text = await svc.collect_screening_notes_text(
        db,
        candidate_id=1,
        stage=SimpleNamespace(
            screening_answers=_answers(
                "Tak, Spring Boot. Notice: 1 month, rate 140.",
                question_text="Czy zna Pan Spring Boot?",
            ),
            notes=None,
        ),
        job=SimpleNamespace(
            id=2, champion_profile={"screening_questions": _CURRENT_QUESTIONS}
        ),
    )
    assert "P: Czy zna Pan Spring Boot?" in text and "O: Tak, Spring Boot." in text
    assert "Spokojny." in text and "Java" in text
    for hidden in ("140", "18k", "Notice", "Terraform"):
        assert hidden not in text, hidden


def test_review_source_notes_have_no_question_lines():
    frozen = (
        "[Odpowiedzi kandydata na pytania screeningowe]\n"
        "P: Czy pracował Pan z OpenTelemetry?\n"
        "O: Tylko z Grafaną."
    )
    out = cv_review_sources._without_hidden_card_fields(frozen)
    assert "OpenTelemetry" not in out
    assert "O: Tylko z Grafaną." in out


@pytest.mark.asyncio
async def test_approval_review_reads_frozen_notes_without_questions(monkeypatch):
    source = svc.CandidateGenerationSource(
        cv_bytes=b"cv",
        cv_filename="cv.pdf",
        champion_json="{}",
        has_champion=False,
        screening_notes_text="P: Czy pracował Pan z OpenTelemetry?\nO: Nie, z Grafaną.",
        source_warnings=(),
        fallback_name="Jan Testowy",
        job_id=2,
        job_title="Backend Developer",
        client_content_mode_cap=None,
        candidate_id=1,
        stage_id=3,
        cv_document_id=4,
    )
    job = SimpleNamespace(kind="new", input_storage_key="k", input_sha256="sha")
    db = AsyncMock()
    db.scalar.return_value = job
    monkeypatch.setattr(
        cv_review_sources.object_storage, "download_cv", lambda key: b""
    )
    monkeypatch.setattr(
        cv_review_sources,
        "deserialize_job_inputs",
        lambda raw, sha: ("new", {"source": source}),
    )
    review = await cv_review_sources.load_review_source(db, 10)
    assert "OpenTelemetry" not in review.screening_notes
    assert "O: Nie, z Grafaną." in review.screening_notes


def test_upload_notes_reach_the_model_without_rates(monkeypatch):
    # Notatki wpisane w formularzu generacji (upload, CV bez procesu) nie
    # przechodzą przez kolektor — filtr stoi też w samym przepływie.
    import json
    import time

    from app.services.cv_generator_b2b import factual_verification
    from app.services.cv_generator_b2b.legacy_v7 import pipeline as legacy

    monkeypatch.delenv("CV_GENERATION_PIPELINE", raising=False)
    monkeypatch.delenv("CV_SOURCE_EVIDENCE_ENFORCED", raising=False)
    monkeypatch.setenv("CV_FINAL_REVIEW_ENABLED", "false")
    prompts: list[str] = []
    payload = {
        "name": "Jan Testowy",
        "position": "Backend Developer",
        "why_points": [],
        "skills": [],
        "experience": [],
    }

    def analyze(user_content, request_id, system=None, **kwargs):
        prompts.append(user_content)
        return json.dumps(payload)

    def forbidden(*args, **kwargs):
        raise AssertionError("bez modelu kontroli w tym teście")

    monkeypatch.setattr(legacy, "extract_text_from_file", lambda data, name: "CV")
    monkeypatch.setattr(legacy, "analyze_with_ai", analyze)
    monkeypatch.setattr(legacy, "render_cv_to_bytes", lambda *a, **k: b"DOCX")
    monkeypatch.setattr(factual_verification, "analyze_with_ai", forbidden)
    svc._run_generation_pipeline(
        cv_bytes=b"cv",
        cv_filename="cv.pdf",
        champion_dto=None,
        screening_notes_text="Zna Kafkę, stawka 150 B2B. Start: od 1.11",
        language="pl",
        blind_cv=False,
        request_id="fix48-ws04",
        fallback_name="Jan Testowy",
        started_at=time.time(),
        content_mode="polished",
    )
    assert "Zna Kafkę," in prompts[0]
    assert "150" not in prompts[0] and "1.11" not in prompts[0]
