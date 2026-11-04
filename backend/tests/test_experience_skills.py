"""„Rekruter sprawdza w rozmowie” — `experience.skills` (13.10.2026).

Czyste testy, bez bazy. Lista zbiera zdania, poziom i umiejętności miękkie,
których nie da się wyszukać w CV. Pilnujemy, że:

* schemat, formularz screeningu i odpowiedź profilu kandydata znają rodzaj
  `skills` (inaczej 422 przy zapisie arkusza albo 500 przy odczycie profilu);
* edycja listy nie kasuje kontraktu wymagań — to nie jest wymaganie roli;
* zdania z listy nie znikają z tekstów, które dotąd czytały je z must
  (generator CV, strona kariery i ogłoszenie, tekst wektora rekrutacji);
* rekrutacja bez listy ma tekst wektora bajt w bajt jak dotąd.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.schemas.candidate_profile_facts import ScreeningConversationCheck
from app.schemas.champion import (
    EXPERIENCE_KINDS,
    ChampionProfile,
    ExperienceCheck,
    ScreeningAnswers,
)
from app.services import champion_view
from app.services.champion_intake import EXPERIENCE_LISTS, user_edit
from app.services.embedding_service import _build_job_text_v1
from app.services.requirement_contract import invalidate_changed_requirements

BASE = {
    "stack": {"must": [{"name": "Azure"}], "nice": []},
    "experience": {"domains": [{"name": "sektor publiczny"}]},
}
TALK = {
    "skills": [
        {"name": "przygotowanie dokumentacji przetargowej (OPZ, SWZ)"},
        {"name": "komunikacja z klientem", "level": "nice"},
    ]
}


def _job(profile: dict, **extra) -> SimpleNamespace:
    return SimpleNamespace(
        title="Architekt chmury",
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
        **extra,
    )


def test_kinds_are_one_list_for_schema_and_save_normaliser() -> None:
    assert EXPERIENCE_LISTS == EXPERIENCE_KINDS
    assert "skills" in EXPERIENCE_KINDS


def test_skills_items_survive_save_with_normalised_shape() -> None:
    saved = user_edit(BASE, {"experience": {**BASE["experience"], **TALK}}, 5)
    skills = champion_view.experience(saved)["skills"]
    assert [s["name"] for s in skills] == [
        "przygotowanie dokumentacji przetargowej (OPZ, SWZ)",
        "komunikacja z klientem",
    ]
    assert [s["level"] for s in skills] == ["must", "nice"]
    assert all(s["min_years"] is None for s in skills)
    # Profil przechodzi walidację schematu w całości.
    ChampionProfile.model_validate(saved)


def test_screening_check_and_profile_response_accept_skills_kind() -> None:
    check = ExperienceCheck(kind="skills", name="komunikacja z klientem")
    answers = ScreeningAnswers(experience_checks=[check])
    assert answers.experience_checks[0].kind == "skills"
    assert ScreeningConversationCheck(kind="skills", name="x").kind == "skills"


def test_editing_talk_list_keeps_reviewed_requirement_contract() -> None:
    stored = ChampionProfile.model_validate(BASE).model_dump(mode="json")
    job = _job(stored, matching_requirements={"reviewed": True, "all_of": []})
    edited = user_edit(stored, {"experience": {**stored["experience"], **TALK}}, 5)
    updates = {"champion_profile": edited}
    invalidate_changed_requirements(job, updates)
    assert "matching_requirements" not in updates
    assert champion_view.requirement_source(edited) == champion_view.requirement_source(
        stored
    )


def test_cv_generator_still_sees_talk_items_as_requirements() -> None:
    from app.services.cv_generator_b2b.champion_builder import from_nexus_job

    profile = user_edit(BASE, {"experience": {**BASE["experience"], **TALK}}, 5)
    dto = from_nexus_job(None, None, profile)
    assert "przygotowanie dokumentacji przetargowej (OPZ, SWZ)" in dto.must_have
    assert "komunikacja z klientem" in dto.nice_to_have
    assert "komunikacja z klientem" not in dto.must_have


def test_career_page_and_ad_keep_talk_items_in_requirements() -> None:
    from app.services.job_public_profile import stack_names

    profile = user_edit(BASE, {"experience": {**BASE["experience"], **TALK}}, 5)
    job = _job(profile)
    assert stack_names(job, "must") == [
        "Azure",
        "przygotowanie dokumentacji przetargowej (OPZ, SWZ)",
    ]
    assert stack_names(job, "nice") == ["komunikacja z klientem"]


def test_job_vector_text_reads_talk_items_only_when_present() -> None:
    profile = ChampionProfile.model_validate(BASE).model_dump(mode="json")
    before = _build_job_text_v1(_job(profile))
    with_talk = user_edit(profile, {"experience": {**profile["experience"], **TALK}}, 5)
    after = _build_job_text_v1(_job(with_talk))
    assert "przygotowanie dokumentacji przetargowej" in after
    # Ponowny zapis bez listy nie zmienia tekstu ani o bajt.
    resaved = ChampionProfile.model_validate(profile).model_dump(mode="json")
    assert _build_job_text_v1(_job(resaved)) == before
