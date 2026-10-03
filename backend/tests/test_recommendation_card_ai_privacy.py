"""Karta rekomendacji w notatce a wejście modeli (0413). Dane fikcyjne.

Narodowości nie czyta żaden model; generator CV nie czyta też stawki, red
flags ani motywacji — to ustalenia handlowe, nie treść CV dla klienta.
"""

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import notes_insights_extractor
from app.services.cv_generator_b2b import standalone_service as svc

_BACKEND = Path(__file__).resolve().parents[1]

_CARD = (
    "<p>Stawka: 135 zł/h</p><p>Dostępność: 1 miesiąc</p>"
    "<p>Narodowość: polska</p><p>Red flags: długo bez projektu</p>"
    "<p>Notatka: mocny w Springu</p><p>Motywacja: szuka większego projektu</p>"
)


def _db(notes: list, card=None, process=None) -> AsyncMock:
    db = AsyncMock()
    # Kolejność odczytów: karta, proces (tylko gdy karta ma rekomendację),
    # pierwszy ruch pary.
    db.scalar.side_effect = [card, process, None] if card else [card, None]
    rows = [[], notes, []]
    db.scalars.side_effect = [SimpleNamespace(all=lambda row=row: row) for row in rows]
    return db


@pytest.mark.asyncio
async def test_cv_generator_reads_the_card_without_commercial_fields():
    text = await svc.collect_screening_notes_text(
        _db([SimpleNamespace(content=_CARD)]),
        candidate_id=1,
        stage=SimpleNamespace(screening_answers={}, notes=None),
        job=SimpleNamespace(id=2, champion_profile={}),
    )

    assert "Notatka: mocny w Springu" in text
    assert "Dostępność: 1 miesiąc" in text
    for hidden in ("135", "polska", "długo bez projektu", "większego projektu"):
        assert hidden not in text


@pytest.mark.asyncio
async def test_cv_generator_gets_the_recommendation_typed_on_the_card():
    card = SimpleNamespace(
        fields_manual={
            "recommendation": {"raw": "5 lat w bankowości, zna domenę płatności"},
            "nationality": {"raw": "polska"},
            "rate": {"raw": "150 zł/h"},
        }
    )
    text = await svc.collect_screening_notes_text(
        _db([], card=card),
        candidate_id=1,
        stage=SimpleNamespace(screening_answers={}, notes=None),
        job=SimpleNamespace(id=2, champion_profile={}),
    )

    assert text == "[Rekomendacja rekrutera]\n5 lat w bankowości, zna domenę płatności"


def test_notes_fact_extraction_keeps_the_rate_but_not_the_nationality():
    blob = notes_insights_extractor.build_notes_blob(
        [(1, None, date(2026, 9, 30), _CARD)]
    )

    assert "Stawka: 135 zł/h" in blob
    assert "polska" not in blob and "Narodowość" not in blob


def test_every_model_reader_of_notes_redacts_the_card():
    """Nowy czytelnik notatek dla modelu ma wycinać pola karty tą samą funkcją."""
    readers = (
        "app/services/cv_generator_b2b/standalone_service.py",
        "app/services/notes_insights_extractor.py",
        "app/services/candidate_activity_summary_service.py",
        "app/services/cv_qc.py",
        "app/services/champion_draft_service.py",
        "app/services/jarvis/tools.py",
    )
    for path in readers:
        source = (_BACKEND / path).read_text(encoding="utf-8")
        assert "redact_card_text(" in source, path


@pytest.mark.asyncio
async def test_recommendation_from_an_earlier_attempt_does_not_reach_the_cv():
    from datetime import datetime, timezone

    card = SimpleNamespace(
        fields_manual={
            "recommendation": {
                "raw": "mocny kandydat z poprzedniego podejścia",
                "at": "2026-08-01T10:00:00+00:00",
            }
        }
    )
    process = SimpleNamespace(
        attempt_no=2,
        opened_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        created_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
    )
    text = await svc.collect_screening_notes_text(
        _db([], card=card, process=process),
        candidate_id=1,
        stage=SimpleNamespace(screening_answers={}, notes=None),
        job=SimpleNamespace(id=2, champion_profile={}),
    )

    assert text == ""


def test_jarvis_candidate_tools_do_not_carry_the_nationality():
    from app.services.jarvis import tools

    shaped = tools._shape_candidate_text(
        {"items": [{"type": "note", "content": _CARD, "id": 7}], "total": 1}, {}
    )

    assert "polska" not in str(shaped)
    assert "Stawka: 135 zł/h" in str(shaped)
    by_name = {tool.name: tool for tool in tools.ALL_TOOLS}
    for name in ("get_candidate", "get_candidate_timeline"):
        assert by_name[name].shape is tools._shape_candidate_text


def test_jarvis_card_tool_never_passes_the_nationality_to_the_model():
    from app.services.jarvis import tools

    card = {
        "exists": True,
        "labels": {
            "rate": "Stawka",
            "nationality": "Narodowość",
            "english": "Angielski",
        },
        "fields": {
            "rate": {"raw": "135 zł/h", "value": 135.0, "source": "note"},
            "nationality": {"raw": "polska", "source": "note"},
        },
        "previous": {"nationality": {"raw": "polska", "source": "note"}},
        "suggestions": {"nationality": "polska"},
        "questions": [
            {
                "number": 1,
                "question": "Java 17+?",
                "answer": "Java 21.",
                "source": "note",
            }
        ],
        "completeness": {
            "status": "partial",
            "filled": 2,
            "total": 10,
            "missing": ["english", "nationality"],
        },
        "legacy_text": "Stawka: 135 zł/h\nNarodowość: polska",
    }

    by_name = {tool.name: tool for tool in tools.ALL_TOOLS}
    shaped = by_name["get_recommendation_card"].shape(card, {})

    assert "polska" not in str(shaped)
    assert "Narodowość" not in str(shaped)
    assert shaped["fields"] == {"Stawka": "135 zł/h"}
    assert shaped["missing"] == ["Angielski"]
    assert shaped["questions"][0]["answer"] == "Java 21."
