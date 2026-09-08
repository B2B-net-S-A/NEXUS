"""`champion_job_sync` — Champion → kolumny oferty, FILL_EMPTY (0278).

Testy operują na obiektach `Job()` NIEPODŁĄCZONYCH do sesji/bazy —
`fill_job_columns_from_champion` jest czystą funkcją (mutuje atrybuty
Pythona, zwraca listę nazw zapisanych kolumn), więc nie potrzebuje ani
Postgresa, ani async. Commit 3: testy behawioru wpiętego w zapis Championa
(`update_champion_profile` przez HTTP, `champion_profile_ingest` bezpośrednio)
— w TYM SAMYM pliku, jak zaplanowano.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
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
# ── wpięcie w zapis Championa (commit 3): update_champion_profile + ingest ──


async def _seed_client() -> int:
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"ChampionSyncClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        return cli.id


async def _seed_job_for_sync(**overrides) -> int:
    """Job z KOLUMNAMI puste (0278) — tak wyglądał każdy wiersz sprzed tej
    migracji, niezależnie od tego, co już leżało w `champion_profile`.
    `overrides` NADPISUJE defaulty (nie dubluje kwargów), jak `_bare_job`."""
    client_id = await _seed_client()
    defaults = dict(
        title=f"ChampionSync-Job-{uuid.uuid4().hex[:6]}",
        client_id=client_id,
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        remote_policy=None,
        location=None,
    )
    defaults.update(overrides)
    async with AsyncSessionLocal() as db:
        job = Job(**defaults)
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def test_champion_save_with_no_profile_diff_still_refreshes_when_columns_filled(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Do tego commitu wczesny return (profil bez zmiany TREŚCI) omijał
    commit kolumn i refresh silnika matchingu — Delivery Lead widział
    wypełnione pola dopiero po DRUGIM, sztucznym zapisie z jakąkolwiek zmianą.

    Scenariusz: profil ma już wypełnioną sekcję `basics` (wiersz sprzed 0278,
    albo po prostu odczyt z ingestu), ale kolumny oferty jeszcze nie. PUT z
    payloadem bez diffu treści (`{}`) musi mimo to je wypełnić I odpalić
    `refresh_job_matching` — DOKŁADNIE raz.
    """
    import app.services.job_matching_refresh as job_matching_refresh_module

    calls: list[int] = []

    async def _fake_refresh(job_id: int, db) -> None:
        calls.append(job_id)

    monkeypatch.setattr(
        job_matching_refresh_module, "refresh_job_matching", _fake_refresh
    )

    job_id = await _seed_job_for_sync(
        champion_profile={
            "basics": {
                "rate_value": 250,
                "onsite_days_per_week": 5,
                "work_mode": "zdalnie",
                "candidate_location_pref": "Warszawa",
            }
        }
    )

    resp = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        headers=app_auth_headers,
        json={},
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.rate_budget_hourly == 250
        assert job.onsite_days_per_week == 5
        assert job.remote_policy == RemotePolicy.remote
        assert job.location == "Warszawa"

    assert calls == [job_id]


async def test_ingest_outcome_reports_columns_filled():
    """`champion_profile_ingest.ingest_parsed_profile` (upload z pliku, nie
    edytor) musi wypełniać te same kolumny co `update_champion_profile` —
    inaczej Champion importowany z Traffita zostaje martwy dla silnika
    matchingu tak samo, jak było to przed 0278."""
    from app.services.champion_profile_ingest import ingest_parsed_profile

    job_id = await _seed_job_for_sync(
        external_source="traffit",
        external_id=str(900_000 + (uuid.uuid4().int % 90_000)),
        # Skille już obecne — must/nice-write mają zostać poza zakresem tego
        # testu, żeby `columns_filled` był JEDYNYM źródłem `changed=True`.
        must_skills=[{"name": "Python", "level": None}],
        nice_skills=[{"name": "SQL", "level": None}],
        champion_profile={
            "basics": {
                "rate_value": 300,
                "onsite_days_per_week": 2,
                "work_mode": "hybrydowo",
                "candidate_location_pref": "Kraków",
            },
            "stack": {"must": [{"name": "Python"}], "nice": []},
        },
    )

    async with AsyncSessionLocal() as db:
        outcome = await ingest_parsed_profile(
            db,
            external_rid=int((await db.get(Job, job_id)).external_id),
            file_id=1,
            parsed={},
        )

    assert outcome["outcome"] == "ok"
    assert set(outcome["columns_filled"]) == {
        "rate_budget_hourly",
        "onsite_days_per_week",
        "remote_policy",
        "location",
    }
    assert outcome["must_written"] is False
    assert outcome["nice_written"] is False

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.rate_budget_hourly == 300
        assert job.onsite_days_per_week == 2
        assert job.remote_policy == RemotePolicy.hybrid
        assert job.location == "Kraków"


async def test_ingest_reports_no_columns_filled_when_nothing_to_fill():
    """Werdykt `champion_skipped_nonempty` (idempotencja collectora — ponowny
    POST tego samego pliku jest tani i bezpieczny) przeżywa dołożenie
    `columns_filled`: gdy kolumny są JUŻ wypełnione, druga próba nie zgłasza
    fałszywej zmiany."""
    from app.services.champion_profile_ingest import ingest_parsed_profile

    job_id = await _seed_job_for_sync(
        external_source="traffit",
        external_id=str(900_000 + (uuid.uuid4().int % 90_000)),
        must_skills=[{"name": "Python", "level": None}],
        nice_skills=[{"name": "SQL", "level": None}],
        rate_budget_hourly=300,
        onsite_days_per_week=2,
        remote_policy=RemotePolicy.hybrid,
        location="Kraków",
        champion_profile={
            "basics": {
                "rate_value": 300,
                "onsite_days_per_week": 2,
                "work_mode": "hybrydowo",
                "candidate_location_pref": "Kraków",
            },
        },
    )

    async with AsyncSessionLocal() as db:
        outcome = await ingest_parsed_profile(
            db,
            external_rid=int((await db.get(Job, job_id)).external_id),
            file_id=1,
            parsed={},
        )

    assert outcome["outcome"] == "champion_skipped_nonempty"
    assert outcome["columns_filled"] == []
