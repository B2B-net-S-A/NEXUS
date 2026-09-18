"""Zapisany profil Championa nie może wywracać odczytu ani zapisu (audyt 18.09.2026).

Na produkcji 83 rekrutacje (19 opublikowanych, 2 665 kandydatów w pipeline'ach)
zwracały HTTP 500 na `/champion-profile` i `/readiness` — a przez brak
`try/except` na ścieżkach zapisu również na `PATCH /api/jobs/{id}`, klonowaniu
i zapisie profilu. Rekrutacji nie dało się ani otworzyć, ani zapisać.

Mechanizm: `migrate_legacy_champion_shape` hoistuje `client_standards.*` do
`client.*` DOPIERO przy odczycie, czyli PO sanityzacji w `prepare_profile`.
Żaden guard tych wartości nie przycinał, a parser AI z 08.2026 wpisywał tam
prozę. Do tego `prepare_profile` normalizuje wyłącznie pola ZMIENIONE (zbiór
`dirty`), więc nietknięta wartość nie naprawiała się nigdy — stąd „trwale".

Kształty poniżej to realne kształty z produkcji, nie wymyślone: proza
w `cv_language`/`contract_type`/`language` oraz ułamki w polach całkowitych.
"""

import pytest
from pydantic import ValidationError

from app.schemas.champion import ChampionProfile, migrate_legacy_champion_shape
from app.services.champion_intake import prepare_profile, user_edit, validation
from app.services.champion_view import api_response

# Dosłowny kształt sprzed przebudowy: fakty klienta siedzą w `client_standards`,
# a nie w `client`. 102 znaki — produkcja miała do 186.
LEGACY_LONG_CV_LANGUAGE = (
    "CV po polsku oraz po angielsku, nazwa pliku w formacie "
    "nazwisko_imie.docx, wysyłane wyłącznie na adres kontaktowy klienta"
)
LEGACY_LONG_CONTRACT_TYPE = (
    "B2B lub umowa o pracę, do uzgodnienia indywidualnie z konsultantem; "
    "przy B2B wymagana własna działalność i ubezpieczenie OC"
)
LEGACY_LONG_WORK_LANGUAGE = (
    "Polski - ojczysty; angielski minimum B2, swobodna praca z dokumentacją "
    "techniczną i udział w spotkaniach z klientem"
)


def legacy_profile() -> dict:
    """Profil w starym kształcie, z każdą z pięciu wartości, które wywracały odczyt."""
    return {
        "basics": {
            "role_name": "Data Engineer",
            "language": LEGACY_LONG_WORK_LANGUAGE,
            "seniority_min_years": 2.5,
            "onsite_days_per_week": 0.5,
        },
        "client_standards": {
            "cv_language": LEGACY_LONG_CV_LANGUAGE,
            "contract_type": LEGACY_LONG_CONTRACT_TYPE,
            "priority_rules": "Najpierw kandydaci z sektora bankowego.",
        },
        "project_context": {"about": "Hurtownia danych."},
    }


def test_stored_legacy_profile_validates_instead_of_raising():
    """Sedno regresji: odczyt zapisanego profilu nie może rzucać."""
    profile = ChampionProfile.model_validate(legacy_profile())

    assert profile.client.cv_language == LEGACY_LONG_CV_LANGUAGE
    assert profile.client.contract_type == LEGACY_LONG_CONTRACT_TYPE
    assert profile.basics.language == LEGACY_LONG_WORK_LANGUAGE


def test_api_response_serves_the_profile():
    """`champion_view.api_response` to granica odczytu — bez niej zakładka 500."""
    body = api_response(legacy_profile())

    assert body["client"]["cv_language"] == LEGACY_LONG_CV_LANGUAGE
    assert body["basics"]["language"] == LEGACY_LONG_WORK_LANGUAGE


def test_write_paths_accept_a_stored_legacy_profile():
    """PATCH rekrutacji i zapis profilu — obie ścieżki walidują STARY profil.

    `user_edit` zaczyna od `ChampionProfile.model_validate(old)`, więc przed
    poprawką padał nawet wtedy, gdy payload użytkownika był czysty.
    """
    merged = user_edit(
        legacy_profile(), {"project": {"about": "Nowy opis."}}, actor_id=1
    )

    assert merged["project"]["about"] == "Nowy opis."
    assert merged["client"]["cv_language"] == LEGACY_LONG_CV_LANGUAGE


def test_prepare_profile_does_not_raise_on_untouched_long_values():
    """`prepare_profile` normalizuje tylko pola ZMIENIONE — reszta musi przejść.

    To jest powód, dla którego profilu nie dało się naprawić przez edycję:
    fallback w `validation()` woła właśnie tę funkcję, a ta kończyła się tym
    samym `model_validate`, który przed chwilą rzucił.
    """
    prepared = prepare_profile(legacy_profile())

    assert prepared["client"]["cv_language"] == LEGACY_LONG_CV_LANGUAGE


def test_validation_reports_issues_instead_of_crashing():
    """`validation()` stoi przed searchem, handoffem i generacją CV."""
    result = validation(legacy_profile())

    assert isinstance(result, dict)


def test_fractional_integers_are_truncated_not_rejected():
    """Ułamki w polach całkowitych: ucinamy w dół, nie zaokrąglamy.

    Oba pola karmią bramki, które UKRYWAJĄ kandydatów, więc zaokrąglenie
    `0.5 → 1` zaostrzałoby wymaganie na podstawie wartości, której nikt nie
    wpisał świadomie. `int()` najwyżej go nie zaostrza.
    """
    profile = ChampionProfile.model_validate(legacy_profile())

    assert profile.basics.seniority_min_years == 2
    assert profile.basics.onsite_days_per_week == 0


def test_truncation_never_tightens_the_office_gate():
    """Pół dnia w biurze nie może stać się pełnym dniem wymagania."""
    migrated = migrate_legacy_champion_shape({"basics": {"onsite_days_per_week": 2.9}})

    assert migrated["basics"]["onsite_days_per_week"] == 2


def test_migration_stays_idempotent():
    """Re-walidacja już zmigrowanego profilu to no-op — kontrakt migratora."""
    once = ChampionProfile.model_validate(legacy_profile()).model_dump(mode="json")
    twice = ChampionProfile.model_validate(once).model_dump(mode="json")

    assert once == twice


def test_bool_is_not_mistaken_for_a_fractional_number():
    """`isinstance(True, int)` jest prawdziwe — guard musi to rozróżniać."""
    migrated = migrate_legacy_champion_shape({"basics": {"seniority_min_years": True}})

    assert migrated["basics"]["seniority_min_years"] is True


def test_limits_that_guard_real_invariants_stay():
    """Zdjęliśmy TRZY limity, nie wszystkie — reszta nadal broni bazy.

    `role_name` ma w bazie `varchar(255)`, więc tam limit chroni przed błędem
    zapisu, a nie przed prozą z parsera. Gdyby ktoś „uporządkował" schemat
    hurtem, ten test pada.
    """
    with pytest.raises(ValidationError):
        ChampionProfile.model_validate({"basics": {"role_name": "x" * 256}})
