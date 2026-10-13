"""„Wymagania do poprawy” — porządki otwartych rekrutacji (D4, 13.10.2026).

Czyste testy `requirement_cleanup.build_proposal` na kształtach z produkcji:
kolumna z prozą zamiast Championa, nawias przy technologii, zdania w must,
krytyczne spoza bramki, rekrutacja bez słów do szukania. Plus lustro DDL.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import SimpleNamespace

from app.models.user import UserRole
from app.services.requirement_cleanup import (
    apply_payload,
    build_proposal,
    can_decide,
)
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

SKILLS = {
    **PROD_LIKE_SKILLS,
    "SQL": ("database", ()),
    "Azure": ("cloud", ()),
    "Git": ("devops", ()),
}
BACKEND = Path(__file__).resolve().parents[1]


def _job(profile, *, must=None, nice=None, **extra):
    return SimpleNamespace(
        id=7,
        title="Data Engineer",
        champion_profile=profile,
        must_skills=[{"name": m} for m in must] if must else None,
        nice_skills=[{"name": n} for n in nice] if nice else None,
        matching_requirements=None,
        requirements_reviewed=False,
        delivery_lead_id=5,
        created_by=6,
        **extra,
    )


def _build(job):
    with hydrated_taxonomy(SKILLS):
        return build_proposal(job)


def test_clean_profile_needs_no_proposal():
    job = _job({"stack": {"must": [{"name": "Java"}, {"name": "SQL"}]}})
    assert _build(job) is None


def test_prose_column_is_replaced_by_champion_words_and_talk_items():
    job = _job(
        {"stack": {"must": [{"name": "SQL"}, {"name": "Python"}, {"name": "Git"}]}},
        must=[
            "Bardzo dobra znajomość SQL",
            "Python",
            "Git",
            "Minimum 5 lat doświadczenia jako Data Engineer",
        ],
    )
    proposal = _build(job)
    assert proposal is not None
    assert "prose_column" in proposal.reasons
    words = [row["words"][0] for row in proposal.after["rows"]]
    assert words[:3] == ["SQL", "Python", "Git"]
    talk = [t["name"] for t in proposal.after["talk"]]
    assert "Minimum 5 lat doświadczenia jako Data Engineer" in talk
    assert proposal.before["must"][0] == "Bardzo dobra znajomość SQL"
    assert proposal.can_apply


def test_parenthesis_in_rows_is_split():
    job = _job(
        {
            "stack": {
                "rows": [{"words": ["SQL (bardzo dobra znajomość)"], "level": "must"}],
                "must": [{"name": "SQL (bardzo dobra znajomość)"}],
                "nice": [],
            },
            "search": {"requirements": [["SQL (bardzo dobra znajomość)"]]},
        }
    )
    proposal = _build(job)
    assert proposal is not None and "paren" in proposal.reasons
    assert proposal.after["rows"][0]["words"] == ["SQL"]
    assert proposal.after["talk"][0]["name"] == "SQL — bardzo dobra znajomość"


def test_critical_phrase_outside_the_gate_drops_to_must():
    job = _job(
        {
            "stack": {
                "rows": [
                    {"words": ["Azure"], "level": "must"},
                    {"words": ["architektura chmury"], "level": "must"},
                ],
                "must": [{"name": "Azure"}, {"name": "architektura chmury"}],
                "nice": [],
                "critical": ["Azure", "architektura chmury"],
            },
            "search": {"requirements": [["Azure"], ["architektura chmury"]]},
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert proposal.reasons == ("critical_not_searchable",)
    assert proposal.after["critical"] == ["Azure"]
    levels = {row["words"][0]: row["level"] for row in proposal.after["rows"]}
    assert levels == {"Azure": "critical", "architektura chmury": "must"}
    payload = apply_payload(proposal)
    assert payload["stack"]["critical"] == ["Azure"]
    assert "basics" not in payload


def test_only_sentences_means_nothing_to_search_and_no_apply():
    job = _job({"stack": {"must": [{"name": "Praca w zespole"}]}})
    proposal = _build(job)
    assert proposal is not None
    assert "no_search_words" in proposal.reasons
    assert proposal.can_apply is False
    assert proposal.as_dict()["can_apply"] is False


def test_language_in_must_moves_to_the_language_field():
    job = _job(
        {
            "stack": {"must": [{"name": "Java"}, {"name": "Język angielski min. B2"}]},
            "basics": {"language": "polski"},
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert proposal.after["language"] == "polski, Język angielski min. B2"
    assert apply_payload(proposal)["basics"] == {
        "language": "polski, Język angielski min. B2"
    }


def _user(uid, *roles):
    return SimpleNamespace(
        id=uid,
        has_role=lambda role: role in roles,
        has_any_role=lambda *wanted: any(r in roles for r in wanted),
    )


def test_only_the_jobs_delivery_lead_or_hor_decides():
    job = _job({})
    assert can_decide(_user(5, UserRole.delivery_lead), job)
    assert can_decide(_user(6, UserRole.delivery_lead), job)
    assert not can_decide(_user(9, UserRole.delivery_lead), job)
    assert not can_decide(_user(5, UserRole.recruiter), job)
    assert can_decide(_user(1, UserRole.head_of_recruitment), job)
    assert can_decide(_user(2, UserRole.admin), job)


def test_migration_chains_and_entrypoint_imports_the_single_ddl_source():
    path = BACKEND / "alembic" / "versions" / "0438_requirement_cleanup_decisions.py"
    spec = importlib.util.spec_from_file_location("m0438", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    assert module.down_revision == "0437_candidate_source_created_at"
    text = (BACKEND / "entrypoint.sh").read_text()
    assert "from app.services import requirement_cleanup_schema" in text
    assert "*_REQUIREMENT_CLEANUP_DDL," in text

    from app.services.requirement_cleanup_schema import TABLE_DDL

    for statement in TABLE_DDL:
        assert "IF NOT EXISTS" in re.sub(r"\s+", " ", statement)
    assert "'applied','dismissed'" in TABLE_DDL[0]


def _kept(proposal, texts):
    """Pozycje, których nie ma ani w wierszach, ani w rozmowie, ani w języku,
    ani w opisie wymagań po zatwierdzeniu."""
    from app.services.champion_requirement_rows import expand_patch

    stack = expand_patch(apply_payload(proposal))["stack"]
    words = {w.casefold() for r in proposal.after["rows"] for w in r["words"]}
    talk = " | ".join(
        i["name"]
        for kind in ("skills", "domains")
        for i in proposal.after["experience"].get(kind) or []
    ).casefold()
    notes = str(stack.get("notes") or "").casefold()
    language = str(proposal.after["language"] or "").casefold()
    return [
        t
        for t in texts
        if t.casefold() not in words
        and t.casefold() not in talk
        and t.casefold() not in notes
        and t.casefold() not in language
    ]


def test_sentence_read_as_category_goes_to_talk_not_nowhere():
    """Przegląd 13.10.2026, bloker 1: zdanie czytane jako kategoria albo rola
    („… management”, „… business analysis”) znikało po „Zatwierdź”."""
    sentences = [
        "Knowledge of card lifecycle management",
        "Flexible approach to switch between technical development and business analysis",
    ]
    job = _job(
        {"stack": {"must": [{"name": "Java"}, *({"name": s} for s in sentences)]}}
    )
    proposal = _build(job)
    assert proposal is not None
    assert [r["words"] for r in proposal.after["rows"]] == [["Java"]]
    assert _kept(proposal, sentences) == []


def test_rows_over_the_limits_land_in_the_requirement_notes():
    """Przegląd 13.10.2026, bloker 2: ponad 10 „musi mieć” + 20 „mile widziane”
    znikało bez notki „Nie zmieściło się w wymaganiach”."""
    words = [f"system{i:02d}" for i in range(35)]
    job = _job(
        {
            "stack": {
                "must": [{"name": w} for w in words]
                + [{"name": "doświadczenie w przetargach"}],
                "notes": "Projekt dla banku.",
            }
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert len(proposal.after["rows"]) == 30
    assert _kept(proposal, [*words, "doświadczenie w przetargach"]) == []
    notes = apply_payload(proposal)["stack"]["notes"]
    assert notes.startswith("Projekt dla banku.")
    assert "Nie zmieściło się w wymaganiach" in notes


def test_all_criticals_demoted_keep_the_decision_as_none_chosen():
    """Przegląd 13.10.2026, bloker 3: gdy każda krytyczna schodzi do „musi mieć”,
    decyzja DL stawała się „brak decyzji” → 422 `handoff_regression`."""
    from app.services.champion_requirement_rows import expand_patch

    job = _job(
        {
            "stack": {
                "rows": [
                    {"words": ["Java"], "level": "must"},
                    {"words": ["architektura chmury"], "level": "must"},
                ],
                "must": [{"name": "Java"}, {"name": "architektura chmury"}],
                "nice": [],
                "critical": ["architektura chmury"],
            },
            "search": {"requirements": [["Java"], ["architektura chmury"]]},
        }
    )
    proposal = _build(job)
    assert proposal is not None
    assert "critical_not_searchable" in proposal.reasons
    assert proposal.after["critical"] == []
    with hydrated_taxonomy(SKILLS):
        assert expand_patch(apply_payload(proposal))["stack"]["critical"] == []


def test_talk_items_over_the_section_limit_stay_in_the_notes():
    """Zrzut produkcji 13.10.2026 (324353, 404749): lista „Rekruter sprawdza
    w rozmowie” ma limit 20 — kolejne zdania trafiają do opisu wymagań."""
    sentences = [f"Doświadczenie w projekcie numer {i} dla klienta" for i in range(25)]
    job = _job(
        {"stack": {"must": [{"name": "Java"}, *({"name": s} for s in sentences)]}}
    )
    proposal = _build(job)
    assert proposal is not None
    assert len(proposal.after["experience"]["skills"]) == 20
    assert _kept(proposal, sentences) == []
    assert "Do sprawdzenia w rozmowie:" in apply_payload(proposal)["stack"]["notes"]
