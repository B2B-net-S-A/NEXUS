from __future__ import annotations

from datetime import date
from types import SimpleNamespace

from app.services.candidate_quick_view import (
    format_cv_highlight_bullets,
    resolve_current_position,
    resolve_cv_highlights,
    resolve_source,
)
from app.services.cv_parser import _normalize_cv_output
from app.services.traffit.importer import _traffit_document_kind


def _candidate(**overrides) -> SimpleNamespace:
    values = {
        "id": 7,
        "name": "Jan",
        "lastname": "Kowalski",
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
    assert resolve_current_position(candidate) == {
        "title": "Senior DevOps Engineer",
        "started_at": "2022-04",
        "precision": "month",
    }

    candidate.experience = []
    assert resolve_current_position(candidate)["title"] == "Cloud Engineer"


def test_source_keeps_acquisition_and_import_transport_separate():
    candidate = _candidate(
        source="traffit",
        external_source="traffit",
        tags=[{"type": "traffit_source", "value": "linkedin"}],
    )
    candidate.creator = SimpleNamespace(name="Anna Kowalska")

    assert resolve_source(candidate) == {
        "added_by_name": "Anna Kowalska",
        "acquisition_source": "LinkedIn",
        "imported_via": "TRAFFIT",
    }


def test_source_uses_system_import_when_creator_is_missing():
    candidate = _candidate(source="pracuj", external_source="manual")
    assert resolve_source(candidate)["added_by_name"] == "System / import"
    assert resolve_source(candidate)["acquisition_source"] == "Pracuj.pl"
    assert resolve_source(candidate)["imported_via"] is None


def test_source_hides_invite_token_prefix():
    candidate = _candidate(
        source="invite_link:abc12345",
        external_source="manual",
    )
    assert resolve_source(candidate)["acquisition_source"] == "Formularz aplikacyjny"


def test_cv_highlights_ignore_unproven_ai_summary():
    candidate = _candidate(
        ai_summary="Opis z Traffita, który nie pochodzi z CV.",
        cv_extracted_data={},
    )
    assert resolve_cv_highlights(candidate)["bullets"] == []


def test_cv_highlights_ignore_unproven_structured_payload():
    candidate = _candidate(
        cv_extracted_data={
            "cv_highlights": {
                "profile": "Niezweryfikowane podsumowanie.",
                "technologies": ["ImaginaryDB"],
            }
        }
    )
    assert resolve_cv_highlights(candidate)["bullets"] == []


def test_cv_highlights_format_four_bounded_factual_bullets():
    candidate = _candidate(
        cv_extracted_data={
            "_source": "claude:cv_enrichment:v5",
            "cv_highlights": {
                "profile": "Senior Java Developer z doświadczeniem w systemach krytycznych.",
                "years_experience": 8,
                "current_role": "Senior Java Developer",
                "current_role_started_at": "2022",
                "current_role_started_at_precision": "year",
                "technologies": [
                    "Java",
                    "Spring Boot",
                    "AWS",
                    "Kubernetes",
                    "SQL",
                ],
                "sectors": ["Bankowość", "Administracja publiczna"],
                "extractor_version": "claude:cv_enrichment:v5",
            },
        }
    )

    resolved = resolve_cv_highlights(candidate)
    assert len(resolved["bullets"]) == 4
    assert resolved["bullets"][1] == "Aktualna rola: Senior Java Developer, od 2022."
    assert resolved["bullets"][2].startswith("Technologie: Java, Spring Boot")
    assert resolved["bullets"][3] == "Sektory: Bankowość, Administracja publiczna."


def test_cv_v5_normalization_caps_and_deduplicates_lists():
    output = _normalize_cv_output(
        {
            "technologies": ["Java", "java", *[f"Tech {i}" for i in range(20)]],
            "sectors": ["Bankowość", "bankowość", "Finanse", "Telekom", "E-commerce"],
            "current_position_started_at": "2021-03",
            "professional_profile": "  Senior   developer  ",
        }
    )
    assert len(output["technologies"]) == 8
    assert len(output["sectors"]) == 4
    assert output["current_position_started_at_precision"] == "month"
    assert output["professional_profile"] == "Senior developer"


def test_cv_v5_normalization_rejects_invalid_dates_and_experience():
    output = _normalize_cv_output(
        {
            "current_position": "  Senior   Developer ",
            "current_position_started_at": "sometime in 2021",
            "years_it_experience": 99,
        }
    )
    assert output["current_position"] == "Senior Developer"
    assert output["current_position_started_at"] is None
    assert output["current_position_started_at_precision"] == "unknown"
    assert output["years_it_experience"] is None


def test_bullet_formatter_omits_unknown_facts():
    bullets = format_cv_highlight_bullets(
        {
            "profile": None,
            "years_experience": None,
            "current_role": None,
            "technologies": ["Python"],
            "sectors": [],
        }
    )
    assert bullets == ["Technologie: Python."]


def test_bullet_formatter_normalizes_common_sector_labels_to_polish():
    bullets = format_cv_highlight_bullets(
        {
            "profile": None,
            "current_role": None,
            "technologies": [],
            "sectors": ["banking", "public administration", "telecom"],
        }
    )
    assert bullets == ["Sektory: Bankowość, Administracja publiczna, Telekomunikacja."]


def test_traffit_attachment_classification_is_conservative():
    assert _traffit_document_kind("Jan-Kowalski-CV.pdf", is_primary=False) == "cv"
    assert _traffit_document_kind("certificate-aws.pdf", is_primary=False) == "other"
    assert _traffit_document_kind("profile.pdf", is_primary=True) == "cv"
