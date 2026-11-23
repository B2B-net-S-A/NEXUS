"""Masowa wysyłka nowej umowy B2B (E5b): kto dostanie umowę i z jakimi danymi.

Czyste reguły ``services/b2b_mass_send/readiness.py`` — bez bazy. Dane
fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.services.b2b_mass_send import readiness
from app.services.b2b_mass_send.readiness import Person, Source

TODAY = date(2026, 11, 23)


def _person(**overrides: Any) -> Person:
    values: dict[str, Any] = {
        "contract_id": 10,
        "candidate_id": 20,
        "candidate_name": "Jan Testowy",
        "client_id": 30,
        "client_name": "Klient Fikcyjny",
        "job_id": 40,
        "start_date": date(2025, 3, 1),
        "rate": Decimal("120"),
        "rate_unit": "hourly",
        "currency": "PLN",
        "candidate_email": "jan.testowy@example.com",
    }
    values.update(overrides)
    return Person(**values)


def _payload(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "candidate_id": 20,
        "job_id": 40,
        "role_id": 5,
        "language": "pl",
        "gender": "m",
        "partner_name": "Jan Testowy",
        "partner_instrumental": "Janem Testowym",
        "partner_legal_name": "Jan Testowy Usługi IT",
        "partner_nip": "1234563218",
        "partner_regon": "123456785",
        "partner_business_address": "ul. Przykładowa 1, 00-001 Warszawa",
        "partner_email": "jan.testowy@example.com",
        "partner_phone": "+48 600 000 000",
        "client_name": "Klient Fikcyjny S.A.",
        "project_city": "Warszawa",
        "project_description": "Rozwój systemu.",
        "contract_number": "1500/2025",
        "signing_date": "2025-02-20",
        "start_date": "2025-03-01",
        "rate_candidate": 120.0,
        "currency": "PLN",
        "is_replacement": False,
        "fte": "1",
        "_clause_override": {"key": None},
        "_notices_email": "umowy@example.com",
    }
    values.update(overrides)
    return values


def _source(**overrides: Any) -> Source:
    values: dict[str, Any] = {"id": 7, "payload": _payload(), "client_id": 30}
    values.update(overrides)
    return Source(**values)


def _assess(person: Person | None = None, **kwargs: Any) -> readiness.Assessment:
    kwargs.setdefault("skip_ending", True)
    kwargs.setdefault("known_role_ids", frozenset({5}))
    return readiness.assess(person or _person(), today=TODAY, **kwargs)


def test_signed_generator_contract_with_full_data_is_ready_for_a_new_number():
    result = _assess(source=_source())
    assert result.status == "ready", result
    assert result.payload is not None
    # Nowa umowa dostaje numer z Generatora i dzisiejszą datę podpisania.
    assert result.payload["contract_number"] is None
    assert result.payload["signing_date"] == TODAY.isoformat()
    # Metadane wydania starej umowy nie przechodzą do nowej.
    assert "_clause_override" not in result.payload
    assert "_notices_email" not in result.payload
    assert result.contractor_email == "jan.testowy@example.com"
    assert result.data_source == "generator"


def test_contract_ending_within_thirty_days_is_skipped_only_when_asked():
    ending = _person(end_date=date(2026, 12, 20))
    assert _assess(ending, source=_source()).reason == readiness.REASON_ENDING
    kept = _assess(ending, source=_source(), skip_ending=False)
    assert kept.status == "ready"


def test_notice_last_day_counts_as_the_end_of_the_contract():
    noticed = _person(end_date=None, agreement_last_day=date(2026, 12, 1))
    assert _assess(noticed, source=_source()).reason == readiness.REASON_ENDING
    later = _person(end_date=date(2027, 6, 30))
    assert _assess(later, source=_source()).status == "ready"


def test_day_thirty_is_still_ending_and_day_thirty_one_is_not():
    assert readiness.ends_soon(_person(end_date=date(2026, 12, 23)), TODAY)
    assert not readiness.ends_soon(_person(end_date=date(2026, 12, 24)), TODAY)


def test_no_email_anywhere_is_skipped_with_the_name_to_fix():
    payload = _payload(partner_email=None)
    result = _assess(_person(candidate_email=None), source=_source(payload=payload))
    assert result.status == "skipped"
    assert result.reason == readiness.REASON_NO_EMAIL
    assert "E-mail" in result.missing


def test_profile_email_is_the_address_when_the_contract_has_none():
    payload = _payload(partner_email="")
    result = _assess(source=_source(payload=payload))
    # Adres jest (profil), ale pole w umowie puste — umowa do sprawdzenia.
    assert result.contractor_email == "jan.testowy@example.com"
    assert result.status == "needs_review"
    assert "E-mail" in result.missing


def test_open_esign_request_for_the_person_is_skipped():
    result = _assess(source=_source(), open_request=True)
    assert (result.status, result.reason) == ("skipped", readiness.REASON_OPEN_REQUEST)


def test_person_already_in_a_mass_send_is_skipped():
    result = _assess(source=_source(), live_batch_id=3)
    assert (result.status, result.reason) == ("skipped", readiness.REASON_IN_BATCH)


def test_no_generator_row_and_no_confirmed_data_is_skipped():
    result = _assess()
    assert (result.status, result.reason) == (
        "skipped",
        readiness.REASON_NO_PARTNER_DATA,
    )


def test_reasons_have_a_fixed_order():
    # Koniec umowy wygrywa z wnioskiem w toku, wniosek z brakiem danych.
    ending = _person(end_date=date(2026, 12, 1))
    assert _assess(ending, open_request=True).reason == readiness.REASON_ENDING
    assert _assess(open_request=True).reason == readiness.REASON_OPEN_REQUEST


def test_missing_generator_fields_mean_needs_review_with_the_field_names():
    payload = _payload(project_city="", partner_regon=None, fte=None)
    result = _assess(source=_source(payload=payload))
    assert result.status == "needs_review"
    assert result.reason == readiness.REASON_MISSING
    assert set(result.missing) == {"Miasto Klienta", "REGON", "Wymiar FTE"}


def test_company_variant_needs_the_company_fields_not_the_instrumental():
    payload = _payload(
        contract_variant="company",
        partner_instrumental=None,
        partner_krs="0000123456",
        partner_seat_locative="w Warszawie",
        partner_registry_court="Sąd Rejonowy, XII Wydział Gospodarczy KRS",
        partner_share_capital="5 000 zł",
        partner_representative_name="Anna Fikcyjna",
        partner_representative_function="Prezes Zarządu",
        partner_representation=None,
    )
    result = _assess(source=_source(payload=payload))
    assert result.missing == ("Reprezentacja w komparycji",)


def test_confirmed_partner_data_without_contract_terms_needs_review():
    confirmed = {
        "fields": {
            "gender": "k",
            "partner_name": "Anna Przykładowa",
            "partner_legal_name": "Anna Przykładowa Consulting",
            "partner_nip": "1234563218",
            "partner_regon": "123456785",
            "partner_business_address": "ul. Fikcyjna 2, 00-002 Kraków",
            "partner_email": "anna.przykladowa@example.com",
            "partner_phone": "+48 600 000 001",
        },
        "contract_variant": "jdg",
    }
    result = _assess(
        _person(is_replacement=False, fte=Decimal("1")), confirmed=confirmed
    )
    assert result.status == "needs_review"
    assert result.data_source == "confirmed"
    # Kontrakt nie zna nazwy Klienta, miasta, opisu ani obszaru usług.
    for label in (
        "Pełna nazwa Klienta",
        "Miasto Klienta",
        "Opis projektu",
        "Obszar usług",
        "Imię i nazwisko (narzędnik)",
    ):
        assert label in result.missing
    payload = result.payload or {}
    assert payload["rate_candidate"] == 120.0
    assert payload["start_date"] == "2025-03-01"
    assert payload["gender"] == "k"


def test_confirmed_data_without_gender_does_not_assume_male_forms():
    confirmed = {"fields": {"partner_name": "Anna Przykładowa"}}
    result = _assess(confirmed=confirmed)
    assert "Forma w umowie" in result.missing


def test_daily_contract_rate_matching_eight_hours_is_not_a_difference():
    person = _person(rate=Decimal("960"), rate_unit="daily")
    assert _assess(person, source=_source()).status == "ready"


def test_contract_rate_different_from_the_last_agreement_needs_review():
    result = _assess(_person(rate=Decimal("130")), source=_source())
    assert result.status == "needs_review"
    assert readiness.ISSUE_RATE_DIFFERS in result.issues
    # Bez kwot w komunikacie: widzą go też osoby bez wglądu w stawki.
    assert "130" not in readiness.describe(result.missing, result.issues)


def test_annex_other_client_pending_draft_and_progressive_rate_need_review():
    payload = _payload(
        rate_candidate=None,
        rate_stages=[
            {"rate": 120, "effective_from": None, "effective_to": "2026-01-31"},
            {"rate": 130, "effective_from": "2026-02-01", "effective_to": None},
        ],
    )
    result = _assess(
        source=_source(payload=payload, has_annex=True, client_id=99),
        pending_draft=True,
    )
    assert result.status == "needs_review"
    assert set(result.issues) >= {
        readiness.ISSUE_PROGRESSIVE,
        readiness.ISSUE_ANNEX,
        readiness.ISSUE_OTHER_CLIENT,
        readiness.ISSUE_PENDING_DRAFT,
    }


def test_role_removed_from_the_catalog_needs_review():
    result = _assess(source=_source(), known_role_ids=frozenset({6}))
    assert readiness.ISSUE_ROLE_GONE in result.issues


def test_several_active_contracts_of_one_person_need_review():
    result = _assess(_person(active_b2b_contracts=2), source=_source())
    assert (result.status, result.reason) == (
        "needs_review",
        readiness.REASON_SEVERAL_CONTRACTS,
    )


def test_job_from_the_contract_fills_an_agreement_without_recruitment():
    payload = _payload(job_id=None)
    result = _assess(source=_source(payload=payload))
    assert (result.payload or {})["job_id"] == 40
