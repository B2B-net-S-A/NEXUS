"""Sekcje 4 „Doświadczenie poza stackiem" i 8 „Wiedza z rozmów" (09.2026).

Czyste testy jednostkowe — bez bazy. Pilnują czterech rzeczy, które łatwo
cofnąć „przy okazji":

* notatkę stempluje serwer (autora z żądania się ignoruje), a wpisy
  z weryfikacji są tylko do odczytu;
* stare pola `client.consultant_insight`/`historical_questions` są edytowane
  jako notatki z zapisem zwrotnym — i zostają w bazie, bo czyta je tekst
  embeddingu v1;
* notatka NIE unieważnia przejrzanego kontraktu wymagań ani odcisku rankingu,
  a zmiana dziedziny — unieważnia;
* notatki „Tylko zespół" nie trafiają do szkicu opisu na stronę kariery.
"""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace

from app.schemas.champion import ChampionProfile
from app.services import champion_view
from app.services.champion_intake import copy_profile, user_edit
from app.services.embedding_service import _build_job_text_v1
from app.services.requirement_contract import invalidate_changed_requirements

LEGACY = {
    "project_context": {"about": "Platforma płatności kartowych."},
    "internal_consultant_insight": "Zespół 6 osób, dużo spotkań",
    "historical_client_questions": "Pytali o PCI DSS",
    "verification": {
        "client": {
            "status": "verified",
            "key_corrections": "Naprawdę szukają kogoś z acquiringu",
            "verified_by_id": 7,
            "verified_by_name": "Delivery Lead",
        }
    },
}


def _view(profile: dict) -> list[dict]:
    return champion_view.api_response(profile)["insights"]


def test_view_composes_legacy_fields_and_verification_as_notes() -> None:
    notes = {n["id"]: n for n in _view(LEGACY)}

    assert notes["verification:client"]["editable"] is False
    assert notes["verification:client"]["text"] == "Naprawdę szukają kogoś z acquiringu"
    assert notes["legacy:client.consultant_insight"]["source"] == "consultant"
    assert notes["legacy:client.historical_questions"]["source"] == "client"
    assert all(n["audience"] == "team" for n in notes.values())


def test_new_note_is_stamped_by_the_server_not_the_payload() -> None:
    patch = {
        "insights": [
            *_view(LEGACY),
            {
                "id": "new-1",
                "text": "Decyduje CTO, rozmowa techniczna 90 min",
                "source": "client",
                "topic": "decision",
                "author_id": 999,
                "author_name": "Podrobiony",
                "created_at": "2000-01-01T00:00:00Z",
                "origin": "verification",
            },
        ]
    }
    saved = user_edit(LEGACY, patch, 5, actor_name="Artur")

    [note] = saved["insights"]
    assert note["author_id"] == 5
    assert note["author_name"] == "Artur"
    assert note["origin"] == "manual"
    assert not note["created_at"].startswith("2000")
    assert note["id"].startswith("n-")
    # Wpis z weryfikacji nie zostaje skopiowany do notatek — jego źródłem
    # jest blok `verification`.
    assert saved["verification"]["client"]["key_corrections"].startswith("Naprawdę")


def test_existing_note_keeps_its_author_after_someone_else_edits_it() -> None:
    first = user_edit(
        {}, {"insights": [{"text": "Klient nie lubi freelancerów"}]}, 5, actor_name="A"
    )
    note = first["insights"][0]
    edited = user_edit(
        first,
        {
            "insights": [
                {
                    **note,
                    "text": "Klient nie lubi freelancerów bez B2B",
                    "author_name": "B",
                }
            ]
        },
        6,
        actor_name="B",
    )
    [after] = edited["insights"]
    assert after["id"] == note["id"]
    assert after["author_name"] == "A"
    assert after["created_at"] == note["created_at"]
    assert after["text"].endswith("bez B2B")


def test_legacy_entries_are_a_view_of_the_old_fields_never_stored_notes() -> None:
    """Wpis `legacy:*` edytuje się przez sekcję `client` — serwer go nie zapisuje.

    Zapis zwrotny po stronie serwera czyściłby stare pola przy każdym zapisie,
    który odsyła zapisany kształt z pustą listą notatek (zapis bez zmian,
    import dokumentu). Dlatego to edytor zmienia `client.*`.
    """
    view = _view(LEGACY)
    saved = user_edit(LEGACY, {"insights": view}, 5, actor_name="A")
    assert saved["insights"] == []
    assert saved["client"]["consultant_insight"] == "Zespół 6 osób, dużo spotkań"

    # Pusta lista notatek NIE rusza starych pól.
    untouched = user_edit(LEGACY, {"insights": []}, 5)
    assert untouched["client"]["historical_questions"] == "Pytali o PCI DSS"

    # Edycja i usunięcie idą przez `client`.
    edited = user_edit(
        LEGACY,
        {"client": {"consultant_insight": "Zespół 8 osób", "historical_questions": ""}},
        5,
    )
    ids = {n["id"] for n in _view(edited)}
    assert "legacy:client.historical_questions" not in ids
    assert [n["text"] for n in _view(edited) if n["id"].startswith("legacy")] == [
        "Zespół 8 osób"
    ]


def test_save_without_insights_key_leaves_the_section_untouched() -> None:
    first = user_edit({}, {"insights": [{"text": "Notatka"}]}, 5, actor_name="A")
    after = user_edit(first, {"project": {"about": "Nowy opis"}}, 6, actor_name="B")
    assert [n["text"] for n in after["insights"]] == ["Notatka"]


def test_experience_is_normalised_deduplicated_and_never_rejected() -> None:
    saved = user_edit(
        {},
        {
            "experience": {
                "domains": [
                    {"name": " payments ", "min_years": "2", "level": "must"},
                    {"name": "Payments"},
                    {"name": "x" * 400, "level": "zle"},
                ],
                "certifications": "ISTQB Foundation; AWS SAA",
                "regulations": [{"name": "PSD2", "level": "nice", "min_years": 5}],
            }
        },
        5,
    )
    exp = saved["experience"]
    assert exp["domains"][0] == {
        "name": "payments",
        "level": "must",
        "min_years": 2,
        "note": "",
    }
    assert len(exp["domains"]) == 2
    assert len(exp["domains"][1]["name"]) == 160
    assert exp["domains"][1]["level"] == "must"
    assert [c["name"] for c in exp["certifications"]] == ["ISTQB Foundation", "AWS SAA"]
    # Lata liczą się tylko przy dziedzinach.
    assert exp["regulations"][0]["min_years"] is None
    assert exp["regulations"][0]["level"] == "nice"


def test_a_note_does_not_invalidate_reviewed_requirements_but_a_domain_does() -> None:
    stored = ChampionProfile.model_validate(LEGACY).model_dump(mode="json")
    job = SimpleNamespace(
        title="QA",
        description=None,
        requirements=None,
        must_skills=None,
        nice_skills=None,
        champion_profile=stored,
        matching_requirements={"reviewed": True, "all_of": []},
    )

    # Edytor odsyła CAŁY widok — wpisy legacy razem z nową notatką.
    with_note = user_edit(
        stored, {"insights": [*_view(stored), {"text": "Nowa notatka"}]}, 5
    )
    updates = {"champion_profile": with_note}
    invalidate_changed_requirements(job, updates)
    assert "matching_requirements" not in updates

    with_domain = user_edit(
        stored, {"experience": {"domains": [{"name": "payments"}]}}, 5
    )
    updates = {"champion_profile": with_domain}
    invalidate_changed_requirements(job, updates)
    assert updates["matching_requirements"] is None


def test_first_save_after_deploy_does_not_invalidate_requirements() -> None:
    """Pusta sekcja `experience` i pusta lista notatek to nie zmiana wymagań."""
    saved_before = ChampionProfile.model_validate(LEGACY).model_dump(mode="json")
    for key in ("experience", "insights", "client_history"):
        saved_before.pop(key)
    job = SimpleNamespace(
        title="QA",
        description=None,
        requirements=None,
        must_skills=None,
        nice_skills=None,
        champion_profile=saved_before,
        matching_requirements={"reviewed": True, "all_of": []},
    )
    resaved = ChampionProfile.model_validate(saved_before).model_dump(mode="json")
    updates = {"champion_profile": resaved}
    invalidate_changed_requirements(job, updates)
    assert "matching_requirements" not in updates


def test_ranking_fingerprint_ignores_notes() -> None:
    base = ChampionProfile.model_validate(LEGACY).model_dump(mode="json")
    noted = user_edit(base, {"insights": [*_view(base), {"text": "Notatka"}]}, 5)
    assert noted["insights"]
    assert champion_view.requirement_source(
        {**noted, "insights": []}, ignored=champion_view.RANKING_IGNORED_KEYS
    ) == champion_view.requirement_source(
        noted, ignored=champion_view.RANKING_IGNORED_KEYS
    )


def _job(profile: dict) -> SimpleNamespace:
    return SimpleNamespace(
        title="Tester",
        description=None,
        requirements=None,
        seniority=None,
        subcategory=None,
        industry=None,
        train_name=None,
        champion_profile=profile,
        must_skills=None,
        nice_skills=None,
        location=None,
        remote_policy=None,
    )


def test_v1_embedding_text_is_unchanged_by_notes_and_experience() -> None:
    """Tekst wektora oferty v1 czyta stare pola — sekcje 4 i 8 go nie ruszają."""
    before = _build_job_text_v1(_job(deepcopy(LEGACY)))
    saved = user_edit(
        LEGACY,
        {
            "insights": [*_view(LEGACY), {"text": "Decyduje CTO"}],
            "experience": {"domains": [{"name": "payments"}]},
        },
        5,
    )
    assert _build_job_text_v1(_job(saved)) == before


def test_template_copy_drops_notes_history_and_verification() -> None:
    stored = user_edit(
        LEGACY,
        {
            "insights": [*_view(LEGACY), {"text": "Tylko dla tej rekrutacji"}],
            "experience": {"domains": [{"name": "payments"}]},
        },
        5,
    )
    copied = copy_profile(stored, 9)
    assert copied["insights"] == []
    assert copied["verification"]["client"]["status"] == "pending"
    assert copied["experience"]["domains"][0]["name"] == "payments"
    # Stare pola są opisem klienta i przechodzą.
    assert copied["client"]["consultant_insight"] == "Zespół 6 osób, dużo spotkań"


def test_public_draft_material_carries_only_candidate_notes() -> None:
    from app.services.job_public_profile import draft_material

    profile = user_edit(
        {},
        {
            "insights": [
                {"text": "Klient odrzucał za słaby angielski", "audience": "team"},
                {
                    "text": "Zespół pracuje w modelu 4 dni zdalnie",
                    "audience": "candidate",
                },
            ],
            "experience": {
                "domains": [{"name": "payments"}],
                "certifications": [{"name": "ISTQB"}],
            },
        },
        5,
    )
    job = SimpleNamespace(
        title="Tester",
        champion_profile=profile,
        description=None,
        requirements=None,
        must_skills=None,
        nice_skills=None,
        remote_policy=None,
        onsite_days_per_week=None,
        recruitment_type=None,
        location=None,
        seniority=None,
    )
    material = draft_material(job, "Tester")
    assert "4 dni zdalnie" in material["pitch"]
    assert "angielski" not in material["pitch"]
    assert material["domains"] == "payments"
    assert material["certifications"] == "ISTQB"
