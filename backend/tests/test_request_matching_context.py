from dataclasses import replace

import pytest

from app.services import scoring_service as scoring
from app.services.request_matching_context import build_request_context
from tests.test_scoring_service import make_candidate, make_job


def test_full_request_tail_is_preserved_and_changes_fingerprint():
    target = make_job(
        description="Administrative introduction. " * 500 + "Required: Django"
    )
    context = build_request_context(target, scoring.DEFAULT_PROFILE)
    assert "Required: Django" in context.query_text
    assert context.as_job().skill_scan_cap is None
    target.description += " Optional: Kubernetes"
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != context.fingerprint
    )


def test_fingerprint_includes_criteria_weights_and_client_context():
    target = make_job(client_id=12)
    original = build_request_context(target, scoring.DEFAULT_PROFILE)
    target.hiring_manager_contact_id = 88
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != original.fingerprint
    )
    target.hiring_manager_contact_id = None
    changed_weights = replace(scoring.DEFAULT_PROFILE, skills=20)
    assert (
        build_request_context(target, changed_weights).fingerprint
        != original.fingerprint
    )
    target.matching_requirements = {"reviewed": True, "all_of": []}
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != original.fingerprint
    )


def test_empty_brief_is_explicitly_preliminary():
    context = build_request_context(make_job(), scoring.DEFAULT_PROFILE)
    assert context.brief_status == "title_only"
    assert context.weights["champion_fit"] == 0
    assert sum(
        context.weights[name]
        for name in ("semantic", "skills", "salary", "location", "availability")
    ) == pytest.approx(100)


def test_workflow_updates_do_not_invalidate_or_enrich_base_fit_context():
    target = make_job(updated_at="yesterday")
    original = build_request_context(target, scoring.DEFAULT_PROFILE)
    target.updated_at = "today"
    target.champion_profile = {
        "verification": {"status": "approved"},
        "recommended_searches": [{"query": "Java"}],
    }
    changed = build_request_context(target, scoring.DEFAULT_PROFILE)
    assert changed.fingerprint == original.fingerprint
    assert changed.query_text == original.query_text
    assert changed.brief_status == "title_only"
    target.champion_profile["stack"] = {"must": ["Django"]}
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != original.fingerprint
    )


def test_search_requirement_rows_do_not_touch_the_ranking_or_the_contract():
    """Wiersze wyszukiwania w bazie (sekcja 2, 25.09.2026) zasilają WYŁĄCZNIE
    „Szukaj ręcznie” — decyzja Artura. Ich edycja nie może zmienić odcisku
    pełnego przeglądu (409) ani skasować zatwierdzonego kontraktu wymagań;
    `keywords` obok nadal są treścią profilu."""
    from app.services import champion_view

    base = {"search": {"keywords": "Java", "requirements": [], "exclude": []}}
    edited = {
        "search": {
            "keywords": "Java",
            "requirements": [["Java"], ["Kafka", "RabbitMQ"]],
            "exclude": ["junior"],
        }
    }
    assert champion_view.requirement_source(base) == champion_view.requirement_source(
        edited
    )
    # Profil sprzed tych pól (bez kluczy) daje ten sam kształt.
    assert champion_view.requirement_source(
        {"search": {"keywords": "Java"}}
    ) == champion_view.requirement_source(edited)

    target = make_job()
    target.champion_profile = base
    original = build_request_context(target, scoring.DEFAULT_PROFILE)
    target.champion_profile = edited
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        == original.fingerprint
    )
    target.champion_profile = {**edited, "search": {**edited["search"], "keywords": "Go"}}
    assert (
        build_request_context(target, scoring.DEFAULT_PROFILE).fingerprint
        != original.fingerprint
    )


def test_champion_search_rows_are_normalised_not_rejected():
    """Schemat normalizuje wiersze zamiast odrzucać (wyjątek walidacji w środku
    zapisu profilu byłby 500): `|` → spacja, puste i powtórki odpadają,
    najwyżej 10 wierszy po 20 słów."""
    from app.schemas.champion import ChampionSearch

    search = ChampionSearch.model_validate(
        {
            "requirements": [["Java", "java", "a|b", " "], [], "Kafka"]
            + [[f"s{i}"] for i in range(12)],
            "exclude": ["junior", "Junior", "x"],
        }
    )
    assert search.requirements[:2] == [["Java", "a b"], ["Kafka"]]
    assert len(search.requirements) == 10
    assert search.exclude == ["junior"]
    assert ChampionSearch.model_validate({"requirements": None}).requirements == []


def test_saving_only_search_rows_keeps_the_ranking_fingerprint():
    """Zapis prawdziwą ścieżką edytora (`user_edit`): same wiersze wyszukiwania
    nie idą przez `prepare_profile`, więc `intake` nie dostaje nowego stempla,
    a odcisk pełnego przeglądu zostaje (inaczej odczyt wyników kończył się 409).
    Pusty wiersz z edytora nie jest zmianą. Frazy obok wierszy nadal są."""
    from app.services import champion_view
    from app.services.champion_intake import user_edit

    def ranking(profile):
        return champion_view.requirement_source(
            profile, ignored=champion_view.RANKING_IGNORED_KEYS
        )

    stored = user_edit({}, {"basics": {"role_name": "Java Developer"}}, 1)
    edited = user_edit(
        stored, {"search": {"requirements": [["Java"]], "exclude": ["junior"]}}, 1
    )
    assert edited["search"]["requirements"] == [["Java"]]
    assert edited["search"]["exclude"] == ["junior"]
    assert edited["intake"] == stored["intake"]
    assert ranking(edited) == ranking(stored)

    again = user_edit(edited, {"search": {"requirements": [["Java"], []]}}, 1)
    assert again == edited

    keywords = user_edit(edited, {"search": {"keywords": "java, kafka"}}, 1)
    assert ranking(keywords) != ranking(edited)


@pytest.mark.asyncio
async def test_same_base_fit_is_independent_of_screening_and_conflicts():
    target = make_job(must_skills=["Python"])
    candidate = make_candidate(skills=["Python"])
    request = build_request_context(target, scoring.DEFAULT_PROFILE)
    empty = scoring.JobScoringContext({}, frozenset())
    process = scoring.JobScoringContext(
        {candidate.id: {"overall_fit": "bad"}}, frozenset({candidate.id})
    )
    one = await scoring.score_candidate_job(
        candidate,
        request.as_job(),
        None,
        semantic_similarity=0.8,
        profile=request.profile(),
        context=empty,
        base_fit=True,
    )
    two = await scoring.score_candidate_job(
        candidate,
        request.as_job(),
        None,
        semantic_similarity=0.8,
        profile=request.profile(),
        context=process,
        base_fit=True,
    )
    assert one.total == two.total
    assert one.penalties == two.penalties == []
    assert one.champion_fit.points == 0
