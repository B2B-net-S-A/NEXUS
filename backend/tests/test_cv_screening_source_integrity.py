from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot
from tests.test_cv_mode_readiness import generation_entry  # noqa: F401 — fixture


@pytest.mark.parametrize("language", ["pl", "en"])
@pytest.mark.asyncio
async def test_ai_summary_without_transcript_is_not_candidate_evidence(language):
    db = AsyncMock()
    db.scalar.return_value = None
    rows = [
        [],
        [],
        [SimpleNamespace(transcript=None, summary="Kandydat ma certyfikat AWS.")],
    ]
    db.scalars.side_effect = [SimpleNamespace(all=lambda row=row: row) for row in rows]
    warnings = []
    text = await svc.collect_screening_notes_text(
        db,
        candidate_id=1,
        stage=SimpleNamespace(screening_answers={}, notes=None),
        job=SimpleNamespace(id=2, champion_profile={}),
        warnings=warnings,
        language=language,
        sources={"transcripts": True},
    )
    assert text == ""
    assert len(warnings) == 1
    assert "AWS" not in warnings[0]
    assert ("Źródła:" if language == "pl" else "Sources:") in warnings[0]


@pytest.mark.asyncio
async def test_transcript_is_preserved_and_summary_is_never_mixed_into_it():
    db = AsyncMock()
    db.scalar.return_value = None
    rows = [
        [],
        [],
        [
            SimpleNamespace(
                transcript="Nie posiadam certyfikatu AWS.",
                summary="Posiada certyfikat AWS.",
            )
        ],
    ]
    db.scalars.side_effect = [SimpleNamespace(all=lambda row=row: row) for row in rows]
    warnings = []
    text = await svc.collect_screening_notes_text(
        db,
        candidate_id=1,
        stage=SimpleNamespace(screening_answers={}, notes=None),
        job=SimpleNamespace(id=2, champion_profile={}),
        warnings=warnings,
        sources={"transcripts": True},
    )
    assert text == "[Transkrypt rozmowy]\nNie posiadam certyfikatu AWS."
    assert warnings == []


@pytest.mark.asyncio
async def test_call_transcripts_are_off_unless_chosen():
    # 13.10.2026: rozmowa nie ma pola rekrutacji, więc do CV szły też rozmowy
    # o innych procesach. Domyślnie bez transkryptów — bez zapytania o rozmowy.
    db = AsyncMock()
    db.scalar.return_value = None
    rows = [[], []]
    db.scalars.side_effect = [SimpleNamespace(all=lambda row=row: row) for row in rows]
    text = await svc.collect_screening_notes_text(
        db,
        candidate_id=1,
        stage=SimpleNamespace(screening_answers={}, notes=None),
        job=SimpleNamespace(id=2, champion_profile={}),
    )
    assert text == ""
    assert db.scalars.call_count == 2


@pytest.mark.asyncio
async def test_rates_and_availability_are_cut_from_free_notes():
    db = AsyncMock()
    db.scalar.return_value = None
    note = SimpleNamespace(
        content="150 PLN/h + VAT, Lublin, dostępny 06.03.2023 r. W Javie od 2018."
    )
    rows = [[], [note]]
    db.scalars.side_effect = [SimpleNamespace(all=lambda row=row: row) for row in rows]
    text = await svc.collect_screening_notes_text(
        db,
        candidate_id=1,
        stage=SimpleNamespace(
            screening_answers={}, notes="Stawka 140 zł, start od zaraz. Zna Kafkę."
        ),
        job=SimpleNamespace(id=2, champion_profile={}),
    )
    assert "150" not in text and "140" not in text
    assert "06.03.2023" not in text
    assert "W Javie od 2018." in text and "Zna Kafkę." in text


def test_internal_judgments_cannot_pad_screening_source():
    note = SimpleNamespace(
        red_flags="AWS",
        closing_strategy="Podnieść stawkę",
        salary_expectation=100,
        salary_currency="PLN",
        overall_impression=5,
        personality_notes=None,
        verified_skills=[],
    )
    assert svc._format_screening_note(note) == ""


def test_verified_skill_context_and_observed_soft_skills_are_preserved():
    note = SimpleNamespace(
        personality_notes="Wyjaśniał decyzje jasno.",
        verified_skills=[
            {
                "skill": "Python",
                "level": "średni",
                "notes": "Testy w pytest; brak doświadczenia z chmurą.",
            }
        ],
    )
    text = svc._format_screening_note(note)
    assert "Wyjaśniał decyzje jasno." in text
    assert "Python (średni) — Testy w pytest; brak doświadczenia z chmurą." in text


@pytest.mark.asyncio
@pytest.mark.parametrize("minimum", [0, 100])
async def test_worker_excludes_ai_only_notes_and_explains_omission(
    monkeypatch,
    minimum,
    generation_entry,  # noqa: F811
):
    """Odsiew notatek AI i bramka minimum znaków — w obu przepływach."""
    job = SimpleNamespace(
        id=2,
        client_id=None,
        title="Developer",
        requirements=None,
        must_skills=[],
        nice_skills=[],
        champion_profile={},
    )
    stage = SimpleNamespace(candidate_id=1, job=job, screening_answers={}, notes=None)
    document = SimpleNamespace(
        storage_key=None, file_content=b"audit", filename="audit.docx"
    )
    db = AsyncMock()
    db.get.return_value = SimpleNamespace(id=1, name="Audyt", lastname="Testowy")
    db.scalar.return_value = None
    rows = [
        [],
        [],
        [SimpleNamespace(transcript=None, summary="Posiada certyfikat AWS. " * 20)],
    ]
    db.scalars.side_effect = [
        SimpleNamespace(first=lambda: stage),
        SimpleNamespace(first=lambda: document),
        *[SimpleNamespace(all=lambda row=row: row) for row in rows],
    ]
    pipeline = generation_entry
    rule = CvRuleSnapshot(
        None, False, None, False, False, require_screening_notes_min_chars=minimum
    )
    if minimum:
        with pytest.raises(svc.StandaloneGenerationError) as raised:
            await svc.generate_cv_for_candidate(
                db, candidate_id=1, stage_id=1, client_rule=rule
            )
        assert raised.value.code == "no_notes"
        pipeline.assert_not_called()
    else:
        result = await svc.generate_cv_for_candidate(
            db, candidate_id=1, stage_id=1, client_rule=rule
        )
        assert pipeline.call_args.kwargs["screening_notes_text"] == ""
        # Od 13.10.2026 rozmowy są domyślnie poza materiałem generatora (PR 4
        # doda przełącznik w karcie CV), więc o podsumowaniach nie ma uwagi.
        assert not any("podsumowań rozmów" in w for w in result.warnings)


_QUESTIONS = {"screening_questions": [{"id": "q1", "question": "Stack?"}]}
_ANSWERS = {"answers": [{"question_id": "q1", "response": "Kafka i Java w Acme Bank."}]}


@pytest.mark.asyncio
async def test_answers_can_be_left_out_of_the_material():
    # D4 (13.10.2026): przełączniki „Z czego powstało” w karcie CV do klienta.
    db = AsyncMock()
    db.scalar.return_value = None
    db.scalars.side_effect = [SimpleNamespace(all=lambda: []) for _ in range(2)]
    text = await svc.collect_screening_notes_text(
        db,
        candidate_id=1,
        stage=SimpleNamespace(screening_answers=_ANSWERS, notes="Zna Grafanę."),
        job=SimpleNamespace(id=2, champion_profile=_QUESTIONS),
        sources={"answers": False},
    )
    assert "Kafka" not in text
    assert "Zna Grafanę." in text


@pytest.mark.asyncio
async def test_notes_can_be_left_out_without_reading_them():
    db = AsyncMock()
    db.scalar.return_value = None
    text = await svc.collect_screening_notes_text(
        db,
        candidate_id=1,
        stage=SimpleNamespace(screening_answers=_ANSWERS, notes="Zna Grafanę."),
        job=SimpleNamespace(id=2, champion_profile=_QUESTIONS),
        sources={"notes": False},
    )
    assert "Kafka i Java w Acme Bank." in text
    assert "Grafan" not in text
    # Bez notatek i bez prepu nie ma zapytań o notatki ani arkusze.
    assert db.scalars.call_count == 0


def test_chosen_sources_fills_defaults_and_drops_unknown_keys():
    assert svc.chosen_sources(None) == svc.AI_SOURCE_DEFAULTS
    assert svc.chosen_sources({"transcripts": True, "hack": True}) == {
        **svc.AI_SOURCE_DEFAULTS,
        "transcripts": True,
    }


@pytest.mark.asyncio
async def test_min_notes_gate_measures_the_chosen_sources(monkeypatch):
    # Przegląd PR 4: wstępna bramka minimum notatek liczyła domyślne źródła,
    # więc włączone transkrypty nie ratowały CV z krótkimi notatkami.
    seen: list = []

    async def collect(db, *, candidate_id, stage, job, sources=None, **_):
        seen.append(sources)
        return "x" * (700 if (sources or {}).get("transcripts") else 30)

    stage = SimpleNamespace(candidate_id=1, job=SimpleNamespace(id=2))
    db = AsyncMock()
    db.scalars.return_value = SimpleNamespace(first=lambda: stage)
    monkeypatch.setattr(svc, "collect_screening_notes_text", collect)
    assert await svc.screening_notes_char_count(db, candidate_id=1, stage_id=3) == 30
    assert (
        await svc.screening_notes_char_count(
            db, candidate_id=1, stage_id=3, sources={"transcripts": True}
        )
        == 700
    )
    assert seen == [None, {"transcripts": True}]
