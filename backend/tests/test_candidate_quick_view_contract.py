from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.candidate_quick_view import (
    format_cv_highlight_bullets,
    resolve_current_position,
    resolve_cv_highlights,
    resolve_source,
)


def _candidate(**overrides) -> SimpleNamespace:
    values = {
        "experience": [],
        "tags": [],
        "cv_extracted_data": {},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_current_position_precedence_linkedin_then_experience_then_cv():
    candidate = _candidate(
        linkedin_current_title="Lead Platform Engineer",
        linkedin_current_started_at=date(2024, 2, 1),
        experience=[
            {
                "role": "Senior DevOps Engineer",
                "start": "2022-04",
                "end": None,
            }
        ],
        cv_extracted_data={"current_position": "Cloud Engineer"},
    )

    assert resolve_current_position(candidate) == {
        "title": "Lead Platform Engineer",
        "started_at": "2024-02-01",
        "precision": "date",
    }
    candidate.linkedin_current_title = None
    assert resolve_current_position(candidate)["title"] == "Senior DevOps Engineer"
    candidate.experience = []
    assert resolve_current_position(candidate)["title"] == "Cloud Engineer"


def test_source_separates_acquisition_from_import_transport():
    candidate = _candidate(
        source="traffit",
        external_source="traffit",
        tags=[{"type": "traffit_source", "value": "linkedin"}],
        creator=SimpleNamespace(name="Anna Kowalska"),
    )

    assert resolve_source(candidate) == {
        "added_by_name": "Anna Kowalska",
        "acquisition_source": "LinkedIn",
        "imported_via": "TRAFFIT",
    }


def test_source_uses_system_import_and_hides_invite_token():
    candidate = _candidate(
        source="invite_link:abc12345",
        external_source="manual",
    )

    assert resolve_source(candidate) == {
        "added_by_name": "System / import",
        "acquisition_source": "Formularz aplikacyjny",
        "imported_via": None,
    }


def test_cv_highlights_ignore_unproven_profile_data():
    candidate = _candidate(
        ai_summary="Opis z importu, który nie pochodzi z CV.",
        cv_extracted_data={
            "cv_highlights": {
                "profile": "Niezweryfikowane podsumowanie.",
                "technologies": ["ImaginaryDB"],
            }
        },
    )

    assert resolve_cv_highlights(candidate)["bullets"] == []


def test_cv_highlights_are_bounded_and_factual():
    candidate = _candidate(
        cv_extracted_data={
            "_source": "claude:cv_enrichment:v5",
            "cv_highlights": {
                "profile": "Senior Java Developer.",
                "years_experience": 8,
                "current_role": "Senior Java Developer",
                "current_role_started_at": "2022",
                "technologies": ["Java", "Spring Boot", "AWS"],
                "sectors": ["banking", "public administration"],
                "extractor_version": "claude:cv_enrichment:v5",
            },
        }
    )

    resolved = resolve_cv_highlights(candidate)
    assert len(resolved["bullets"]) == 4
    assert resolved["bullets"][1] == "Aktualna rola: Senior Java Developer, od 2022."
    assert resolved["bullets"][2] == "Technologie: Java, Spring Boot, AWS."
    assert resolved["bullets"][3] == "Sektory: Bankowość, Administracja publiczna."


def test_bullet_formatter_omits_unknown_facts():
    assert format_cv_highlight_bullets(
        {
            "profile": None,
            "years_experience": None,
            "current_role": None,
            "technologies": ["Python"],
            "sectors": [],
        }
    ) == ["Technologie: Python."]
