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
    started = time.perf_counter()
    rate_quote_context_conflict("150 zł/h", text)
    assert time.perf_counter() - started < 0.05


# ── R8-N12-3: samo imię + wspólna skrzynka ────────────────────────────────


def _contact(id_: int, name: str, email: str):
    from app.models.contact import Contact

    return Contact(id=id_, client_id=1, name=name, email=email)


def test_first_name_alone_does_not_pick_another_person_by_shared_mailbox():
    from app.services.job_hiring_manager import pick_matching_contact

    contacts = [_contact(1, "Jan Kowalski", "rekrutacja@bank.pl")]
    assert (
        pick_matching_contact(contacts, name="Anna", email="rekrutacja@bank.pl")
        is None
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
    assert pick_matching_contact(contacts, name=None, email="rekrutacja@bank.pl").id == 1
