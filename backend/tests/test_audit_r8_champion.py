"""Runda 8 audytu (26.09.2026) — Champion i rekrutacja z maila klienta (N12)."""

import time

import pytest

from app.services.job_request_intake import (
    normalize_model_output,
    rate_quote_context_conflict,
)


# ── R8-N12-2: cytat stawki ucięty przez model ─────────────────────────────


@pytest.mark.parametrize(
    "text, quote",
    [
        ("Stawka: 150 zł/h brutto, UoP, start ASAP.", "150 zł/h"),
        ("Budżet do 150 zł/h lub 1200 zł/MD, zdalnie.", "do 150 zł/h"),
        ("Stawka brutto: 150 zł/h dla UoP.", "150 zł/h"),
        ("Budżet 150 zł/h (klient płaci w EUR).", "150 zł/h"),
    ],
)
def test_rate_quote_cut_before_a_contradicting_word_is_not_a_budget(text, quote):
    result = normalize_model_output({"rate_quote": quote}, text)
    assert result.rate_budget_hourly is None
    assert result.rate_note and "Wpisz budżet ręcznie" in result.rate_note
    assert result.provenance.get("rate") is None


@pytest.mark.parametrize(
    "text, quote, budget",
    [
        (
            "Budżet do 170 zł/h netto, start za miesiąc, 2 dni w biurze.",
            "do 170 zł/h netto",
            170,
        ),
        # Inna linia maila nie jest sąsiedztwem cytatu.
        ("Stawka: 150 zł/h\nWynagrodzenie brutto dla UoP inne.", "150 zł/h", 150),
        ("Stawka 150 PLN/h + VAT, B2B.", "150 PLN/h + VAT", 150),
    ],
)
def test_harmless_neighbourhood_keeps_the_budget(text, quote, budget):
    result = normalize_model_output({"rate_quote": quote}, text)
    assert result.rate_budget_hourly == budget


def test_draft_rate_twin_checks_the_neighbourhood_too():
    from app.services.champion_draft_service import _ground_basics_rate

    basics = {"rate_value": 150, "rate_raw": "150 zł/h"}
    note = _ground_basics_rate(basics, "Kandydat chce 150 zł/h brutto na UoP.")
    assert basics["rate_value"] is None and basics["rate_raw"] is None
    assert note and "brutto" in note


def test_rate_context_check_is_fast_on_a_long_line():
    text = ("x 1 " * 4000) + "150 zł/h"
    timings = []
    for _ in range(3):
        started = time.perf_counter()
        rate_quote_context_conflict("150 zł/h", text)
        timings.append(time.perf_counter() - started)
    assert min(timings) < 0.05


# ── R8-N12-3: samo imię + wspólna skrzynka ────────────────────────────────


def _contact(id_: int, name: str, email: str):
    from app.models.contact import Contact

    return Contact(id=id_, client_id=1, name=name, email=email)


def test_first_name_alone_does_not_pick_another_person_by_shared_mailbox():
    from app.services.job_hiring_manager import pick_matching_contact

    contacts = [_contact(1, "Jan Kowalski", "rekrutacja@bank.pl")]
    assert (
        pick_matching_contact(contacts, name="Anna", email="rekrutacja@bank.pl") is None
    )


def test_first_name_of_the_same_person_still_matches_by_mail():
    from app.services.job_hiring_manager import pick_matching_contact

    contacts = [
        _contact(1, "Jan Kowalski", "rekrutacja@bank.pl"),
        _contact(2, "Anna Nowak", "rekrutacja@bank.pl"),
    ]
    picked = pick_matching_contact(contacts, name="Anna", email="rekrutacja@bank.pl")
    assert picked is not None and picked.id == 2
    # Bez imienia — jak dotąd, po samym adresie.
    assert (
        pick_matching_contact(contacts, name=None, email="rekrutacja@bank.pl").id == 1
    )


# ── R8-N12-4: arkusz screeningu dla klienta = biała lista ────────────────


def test_client_screening_drops_experience_checks_and_author():
    from app.schemas.champion import client_safe_screening

    raw = {
        "answers": [
            {
                "question_id": "q1",
                "response": "5 lat",
                "deal_breaker_hit": False,
                "origin": "reassign_suggested",
            }
        ],
        "experience_checks": [
            {"name": "ISTQB", "status": "not_confirmed", "note": "raczej nie ma"}
        ],
        "overall_fit": "fit",
        "notes": "Widoczne dla klienta",
        "answered_by": 17,
        "answered_at": "2026-09-26T10:00:00+00:00",
        "future_internal_field": "x",
    }
    safe = client_safe_screening(raw)
    assert set(safe) == {"answers", "overall_fit", "notes"}
    assert safe["answers"] == [
        {"question_id": "q1", "response": "5 lat", "deal_breaker_hit": False}
    ]
    # Wejście (JSONB wiersza) nietknięte.
    assert "experience_checks" in raw and raw["answers"][0]["origin"]


# ── R8-N12-5: pierwszy zapis profilu w starym kształcie ──────────────────


_LEGACY_PROFILE = {
    "project_context": {"about": "Projekt płatności", "responsibilities": "Kafka"},
    "sourcing": {"keywords": "java kafka"},
    "must_skills": ["Java", "Kafka"],
}


def _legacy_job():
    from types import SimpleNamespace

    return SimpleNamespace(
        champion_profile=dict(_LEGACY_PROFILE),
        matching_requirements={"reviewed": True, "must": []},
        requirements_reviewed=True,
    )


def test_notes_only_save_of_a_legacy_profile_keeps_the_reviewed_contract():
    from app.schemas.champion import ChampionProfile
    from app.services.requirement_contract import apply_requirement_source_update

    job = _legacy_job()
    new_profile = ChampionProfile.model_validate(_LEGACY_PROFILE).model_dump()
    new_profile["insights"] = [{"id": "n1", "text": "Klient lubi Kafkę"}]
    apply_requirement_source_update(job, "champion_profile", new_profile)
    assert job.matching_requirements == {"reviewed": True, "must": []}
    assert job.requirements_reviewed is True


def test_real_requirement_change_of_a_legacy_profile_still_invalidates():
    from app.schemas.champion import ChampionProfile
    from app.services.requirement_contract import apply_requirement_source_update

    job = _legacy_job()
    new_profile = ChampionProfile.model_validate(_LEGACY_PROFILE).model_dump()
    new_profile["project"]["about"] = "Zupełnie inny projekt"
    apply_requirement_source_update(job, "champion_profile", new_profile)
    assert job.matching_requirements is None
    assert job.requirements_reviewed is False


# ── R8-N12-6: pochodzenie „z maila” ze sprawdzeniem ──────────────────────


_MAIL = "Szukamy Java developera z doświadczeniem w bankowości, Spring Boot."


def test_technology_added_by_the_model_is_an_ai_proposal_not_a_quote():
    result = normalize_model_output({"must": ["Java", "Kafka"]}, _MAIL)
    assert result.must == ["Java", "Kafka"]
    assert result.provenance["must"] == "ai"
    grounded = normalize_model_output({"must": ["Java", "Spring Boot"]}, _MAIL)
    assert grounded.provenance["must"] == "request"


def test_out_of_range_seniority_is_not_marked_as_from_the_mail():
    result = normalize_model_output({"seniority_min_years": 99}, _MAIL)
    assert result.seniority_min_years is None
    assert "seniority" not in result.provenance


@pytest.mark.parametrize(
    "quote, kept",
    [
        ("a", False),  # jeden znak z maila
        ("Spring Boot", False),  # prawdziwy fragment, ale nie o bankowości
        ("doświadczeniem w bankowości", True),
    ],
)
def test_experience_quote_must_back_the_item_name(quote, kept):
    result = normalize_model_output(
        {"experience": {"domains": [{"name": "Bankowość", "quote": quote}]}}, _MAIL
    )
    assert bool(result.experience["domains"]) is kept
