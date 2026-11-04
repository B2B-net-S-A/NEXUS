"""Runda 10 (F25): „Generuj z szablonu” → „Umowa B2B (EN)” mówi po angielsku.

Kontrakt 675 na produkcji (26.09.2026): w angielskim §6 „Remuneration” kwoty
stawek progresywnych były poprawne, ale opis słowny i daty wejścia zostały po
polsku („słownie: sto dwadzieścia…”, „od dnia 01.10.2026”) — język klauzuli
brał się z danych B2B umowy, nie z wybranego szablonu.
"""

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.api.contract_templates import _contract_vars


def _contract(*, detail_language="pl", rate_in_words="sto dwadzieścia złotych"):
    detail = SimpleNamespace(
        role=None,
        language=detail_language,
        role_scope_override=None,
        rate_in_words=rate_in_words,
        contract_number="1/2026",
        signing_date=None,
        project_city=None,
        project_description=None,
        correspondence_address=None,
    )
    return SimpleNamespace(
        candidate=None,
        client=None,
        job=None,
        b2b_detail=detail,
        candidate_rate_schedule=[],
        rate_candidate=Decimal("120.50"),
        resolved_rate_candidate_currency="PLN",
        id=675,
        start_date=date(2026, 10, 1),
        end_date=None,
        rate_client=None,
        rate_unit=SimpleNamespace(value="hourly"),
        billing_hours_per_month=168,
        contract_type=SimpleNamespace(value="b2b"),
        project_name=None,
        team_name=None,
        office_location=None,
        work_mode=None,
        client_pm_name=None,
        client_pm_email=None,
    )


def _progressive(contract):
    contract.candidate_rate_schedule = [
        SimpleNamespace(
            rate=Decimal("120.50"),
            effective_from=date(2026, 10, 1),
            effective_to=date(2026, 10, 31),
        ),
        SimpleNamespace(
            rate=Decimal("125.75"), effective_from=date(2026, 11, 1), effective_to=None
        ),
    ]
    return contract


def test_english_template_gets_english_words_and_dates_for_progressive_rates():
    clause = _contract_vars(_progressive(_contract()), language="en")["b2b"][
        "rate_clause"
    ]
    assert "słownie" not in clause
    assert "od dnia" not in clause
    assert "do dnia" not in clause
    assert "in words" in clause
    assert "from 01.11.2026" in clause
    assert clause.count("PLN") == 2


def test_english_template_does_not_reuse_polish_manual_words():
    clause = _contract_vars(_contract(), language="en")["b2b"]["rate_clause"]
    assert "sto dwadzieścia" not in clause
    assert "in words" in clause


def test_polish_template_stays_polish():
    clause = _contract_vars(_progressive(_contract()), language="pl")["b2b"][
        "rate_clause"
    ]
    assert "słownie" in clause and "od dnia 01.11.2026" in clause
    single = _contract_vars(_contract(), language="pl")["b2b"]["rate_clause"]
    assert "sto dwadzieścia złotych" in single


def test_template_without_language_keeps_the_contract_language():
    assert "słownie" in _contract_vars(_contract())["b2b"]["rate_clause"]
    english = _contract_vars(_contract(detail_language="en", rate_in_words=None))
    assert "in words" in english["b2b"]["rate_clause"]
