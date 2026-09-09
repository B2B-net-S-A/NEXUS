from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.services.cv_generator_b2b import standalone_service as svc
from app.services.cv_generator_b2b.client_rules import CvRuleSnapshot


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
    )
    assert text == "[Transkrypt rozmowy]\nNie posiadam certyfikatu AWS."
    assert warnings == []


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
    monkeypatch, minimum
):
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
    pipeline = Mock(return_value=SimpleNamespace(warnings=[]))
    monkeypatch.setattr(svc, "_run_generation_pipeline", pipeline)
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
        assert "podsumowań rozmów AI bez transkryptu" in result.warnings[0]
