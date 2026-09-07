"""`champion_job_sync` — Champion → kolumny oferty, FILL_EMPTY (0278).

Testy operują na obiektach `Job()` NIEPODŁĄCZONYCH do sesji/bazy —
`fill_job_columns_from_champion` jest czystą funkcją (mutuje atrybuty
Pythona, zwraca listę nazw zapisanych kolumn), więc nie potrzebuje ani
Postgresa, ani async. Testy behawioru wpiętego w zapis Championa
(`update_champion_profile`, `champion_profile_ingest`) dochodzą w commicie 3
tej fali, do TEGO SAMEGO pliku.
"""

from __future__ import annotations

from app.models.job import Job, RemotePolicy
from app.services.champion_job_sync import (
    WORK_MODE_PREFIXES,
    champion_work_mode_to_remote,
    fill_job_columns_from_champion,
)


def _bare_job(**overrides) -> Job:
    """`Job()` odłączony od sesji — testuje wyłącznie mutację atrybutów."""
    defaults = dict(
        title="pytest job",
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        remote_policy=None,
        location=None,
    )
    defaults.update(overrides)
    return Job(**defaults)


def test_fill_empty_never_overwrites():
    job = _bare_job(
        rate_budget_hourly=100,
        onsite_days_per_week=1,
        remote_policy=RemotePolicy.onsite,
        location="Kraków",
    )
    basics = {
        "rate_value": 250,
        "onsite_days_per_week": 5,
        "work_mode": "zdalnie",
        "candidate_location_pref": "Warszawa",
    }

    filled = fill_job_columns_from_champion(job, basics)

    assert filled == []
    assert job.rate_budget_hourly == 100
    assert job.onsite_days_per_week == 1
    assert job.remote_policy == RemotePolicy.onsite
    assert job.location == "Kraków"


def test_fills_all_four_from_basics():
    job = _bare_job()
    basics = {
        "rate_value": 250,
        "onsite_days_per_week": 5,
        "work_mode": "zdalnie",
        "candidate_location_pref": "Warszawa",
    }

    filled = fill_job_columns_from_champion(job, basics)

    assert set(filled) == {
        "rate_budget_hourly",
        "onsite_days_per_week",
        "remote_policy",
        "location",
    }
    assert job.rate_budget_hourly == 250
    assert job.onsite_days_per_week == 5
    assert job.remote_policy == RemotePolicy.remote
    assert job.location == "Warszawa"


def test_fills_only_the_columns_present_in_basics():
    """Częściowy profil (np. tylko stawka) wypełnia WYŁĄCZNIE tę kolumnę."""
    job = _bare_job()
    filled = fill_job_columns_from_champion(job, {"rate_value": 150})

    assert filled == ["rate_budget_hourly"]
    assert job.rate_budget_hourly == 150
    assert job.onsite_days_per_week is None
    assert job.remote_policy is None
    assert job.location is None


def test_non_dict_basics_is_a_noop():
    job = _bare_job()
    assert fill_job_columns_from_champion(job, None) == []  # type: ignore[arg-type]
    assert fill_job_columns_from_champion(job, []) == []  # type: ignore[arg-type]


def test_work_mode_prefix_tolerance():
    # Wolny tekst z prawdziwych profili — nie enum, dopasowanie po prefiksie.
    assert champion_work_mode_to_remote("Hybrydowo (2 dni w biurze)") == "hybrid"
    assert champion_work_mode_to_remote("Zdalnie") == "remote"
    assert champion_work_mode_to_remote("Stacjonarnie, biuro Warszawa") == "onsite"
    assert champion_work_mode_to_remote("") is None
    assert champion_work_mode_to_remote(None) is None
    assert champion_work_mode_to_remote(123) is None
    assert champion_work_mode_to_remote("Elastycznie") is None

    # Lustro SQL-owe (migracja 0278 + entrypoint.sh) używa dokładnie tych
    # samych trzech prefiksów — patrz test_office_presence_rubric_mirror.py.
    assert WORK_MODE_PREFIXES == {
        "zdaln": "remote",
        "hybryd": "hybrid",
        "stacjonar": "onsite",
    }


def test_rate_out_of_range_and_days_bool_ignored():
    # Stawka poza (0, 2000] — nie wypełnia.
    job = _bare_job()
    assert fill_job_columns_from_champion(job, {"rate_value": 3000}) == []
    assert job.rate_budget_hourly is None
    assert fill_job_columns_from_champion(job, {"rate_value": 0}) == []
    assert job.rate_budget_hourly is None
    assert fill_job_columns_from_champion(job, {"rate_value": -5}) == []
    assert job.rate_budget_hourly is None

    # bool jest podtypem int w Pythonie — musi być jawnie wykluczony, inaczej
    # `"onsite_days_per_week": true` z JSON-a zapisałoby się jako `1`.
    assert fill_job_columns_from_champion(job, {"rate_value": True}) == []
    assert job.rate_budget_hourly is None

    job2 = _bare_job()
    assert fill_job_columns_from_champion(job2, {"onsite_days_per_week": True}) == []
    assert job2.onsite_days_per_week is None
    assert fill_job_columns_from_champion(job2, {"onsite_days_per_week": 8}) == []
    assert job2.onsite_days_per_week is None
    assert fill_job_columns_from_champion(job2, {"onsite_days_per_week": -1}) == []
    assert job2.onsite_days_per_week is None

    # Brzegi zakresu przechodzą.
    job3 = _bare_job()
    assert fill_job_columns_from_champion(job3, {"onsite_days_per_week": 0}) == [
        "onsite_days_per_week"
    ]
    assert job3.onsite_days_per_week == 0


def test_location_truncated_to_255():
    job = _bare_job()
    long_value = "Warszawa " * 40  # > 255 znaków
    filled = fill_job_columns_from_champion(job, {"candidate_location_pref": long_value})

    assert filled == ["location"]
    assert job.location == long_value.strip()[:255]
    assert len(job.location) == 255

    # Sam biały znak nie jest lokalizacją — nie wypełnia.
    job2 = _bare_job()
    assert fill_job_columns_from_champion(job2, {"candidate_location_pref": "   "}) == []
    assert job2.location is None


def test_numeric_strings_from_jsonb_are_accepted_like_in_sql():
    """Historyczny profil trzyma stawkę jako TEKST — obie ścieżki muszą ją brać.

    `champion_view.basics()` czyta surowy JSONB (ingest z pliku), więc
    `rate_value` bywa stringiem. Backfill SQL w 0278 kwalifikuje takie wartości
    regexem `^[0-9]+(\.[0-9]+)?$`; gdyby Python ich nie brał, ta sama oferta
    dostawałaby budżet z migracji, ale NIE z zapisu profilu — cichy rozjazd
    dwóch ścieżek, które mają robić to samo.
    """
    job = _bare_job()
    filled = fill_job_columns_from_champion(
        job, {"rate_value": "122.50", "onsite_days_per_week": "3"}
    )

    assert float(job.rate_budget_hourly) == 122.5
    assert job.onsite_days_per_week == 3
    assert set(filled) == {"rate_budget_hourly", "onsite_days_per_week"}


def test_non_numeric_and_fractional_strings_are_rejected():
    """Ten sam zbiór odrzuceń co SQL — nie szerszy.

    `"ok. 120"` nie przechodzi regexa (SQL też go odrzuca), a ułamkowe dni
    („2.5”) odpadają, bo `candidates.max_onsite_days_per_week` jest `int`
    i porównanie „mniej dni niż wymaga oferta” musi być całkowitoliczbowe.
    Ujemna stawka odpada na sufitcie `0 < x <= 2000`.
    """
    job = _bare_job()
    filled = fill_job_columns_from_champion(
        job,
        {
            "rate_value": "ok. 120",
            "onsite_days_per_week": "2.5",
        },
    )

    assert job.rate_budget_hourly is None
    assert job.onsite_days_per_week is None
    assert filled == []


def test_boolean_is_never_a_rate_even_though_bool_is_an_int():
    """`True` jest instancją `int` w Pythonie — „tryb włączony” to nie stawka."""
    job = _bare_job()

    assert fill_job_columns_from_champion(job, {"rate_value": True}) == []
    assert job.rate_budget_hourly is None
