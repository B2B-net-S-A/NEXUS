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
from datetime import date, timedelta

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.models.job import Job, RemotePolicy
from app.services.champion_job_sync import (
    WORK_MODE_PREFIXES,
    champion_work_mode_to_remote,
    fill_job_columns_from_champion,
    overwrite_edited_job_columns,
)


# ── „Deadline na kandydatów” → termin rekrutacji (08.10.2026) ───────────────
#
# Bramka przekazania pyta o `jobs.deadline`, a edytor Championa ma własne pole
# terminu. Do 08.10.2026 wpisana tam data zostawała w profilu: brak „Ustaw
# termin” wisiał mimo wypełnionego pola.


def _edit_deadline(job: Job, old: dict, new: dict) -> list[str]:
    return overwrite_edited_job_columns(job, old, new, set_deadline=True)


def _fill_deadline(job: Job, value: str) -> list[str]:
    return fill_job_columns_from_champion(job, {"deadline": value}, set_deadline=True)


def test_edited_champion_deadline_becomes_the_recruitment_term():
    job = _bare_job()
    job.deadline_not_provided = True
    changed = overwrite_edited_job_columns(
        job, {"deadline": None}, {"deadline": "2026-11-15"}, set_deadline=True
    )
    assert changed == ["deadline"]
    assert job.deadline == date(2026, 11, 15)
    # Data zdejmuje decyzję „Klient nie podał”.
    assert job.deadline_not_provided is False


def test_edited_champion_deadline_replaces_an_older_recruitment_term():
    job = _bare_job()
    job.deadline = date(2026, 10, 20)
    changed = overwrite_edited_job_columns(
        job, {"deadline": "2026-10-20"}, {"deadline": "2026-11-15"}, set_deadline=True
    )
    assert changed == ["deadline"]
    assert job.deadline == date(2026, 11, 15)


def test_untouched_or_unreadable_champion_deadline_leaves_the_term_alone():
    job = _bare_job()
    job.deadline = date(2026, 10, 20)
    same = {"deadline": "2026-11-15"}
    # Nietknięte w tym zapisie — starszy rozjazd zostaje.
    assert _edit_deadline(job, same, dict(same)) == []
    # Wyczyszczone pole nie kasuje terminu rekrutacji (byłby to nowy brak).
    assert _edit_deadline(job, same, {"deadline": None}) == []
    # Tekst, którego normalizator nie odczytał jako daty.
    assert _edit_deadline(job, same, {"deadline": "ASAP"}) == []
    assert job.deadline == date(2026, 10, 20)


def test_champion_deadline_stays_in_the_profile_without_full_job_edit():
    """Termin to pole cyklu życia — zapis treści przez rekrutera go nie rusza."""
    upcoming = (business_today() + timedelta(days=30)).isoformat()
    job = _bare_job()
    # Domyślnie wyłączone: import pliku i akceptacja szkicu AI też go nie ruszają.
    assert (
        overwrite_edited_job_columns(job, {"deadline": None}, {"deadline": upcoming})
        == []
    )
    assert fill_job_columns_from_champion(job, {"deadline": upcoming}) == []
    assert job.deadline is None


def test_fill_empty_takes_an_upcoming_champion_deadline():
    upcoming = business_today() + timedelta(days=30)
    job = _bare_job()
    filled = _fill_deadline(job, upcoming.isoformat())
    assert filled == ["deadline"]
    assert job.deadline == upcoming
    assert job.deadline_not_provided is False


def test_fill_empty_deadline_respects_the_term_and_the_decision():
    upcoming = (business_today() + timedelta(days=30)).isoformat()
    # Termin rekrutacji już jest.
    with_term = _bare_job()
    with_term.deadline = date(2026, 10, 20)
    assert _fill_deadline(with_term, upcoming) == []
    assert with_term.deadline == date(2026, 10, 20)
    # „Klient nie podał” to decyzja człowieka — data ze starego profilu jej
    # nie cofa (zmienia ją dopiero edycja pola w tym zapisie).
    decided = _bare_job()
    decided.deadline_not_provided = True
    assert _fill_deadline(decided, upcoming) == []
    assert decided.deadline is None
    # Miniona data ze starego profilu nie robi z rekrutacji „po terminie”.
    past = (business_today() - timedelta(days=1)).isoformat()
    stale = _bare_job()
    assert _fill_deadline(stale, past) == []
    assert stale.deadline is None


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
    filled = fill_job_columns_from_champion(
        job, {"candidate_location_pref": long_value}
    )

    assert filled == ["location"]
    assert job.location == long_value.strip()[:255]
    assert len(job.location) == 255

    # Sam biały znak nie jest lokalizacją — nie wypełnia.
    job2 = _bare_job()
    assert (
        fill_job_columns_from_champion(job2, {"candidate_location_pref": "   "}) == []
    )
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


# ── Ręczna zmiana w edytorze nadpisuje kolumnę (30.09.2026) ─────────────────


def test_edited_rubric_overwrites_filled_column():
    job = _bare_job(onsite_days_per_week=0, remote_policy=RemotePolicy.hybrid)
    changed = overwrite_edited_job_columns(
        job,
        {"onsite_days_per_week": 0, "work_mode": "hybrydowo"},
        {"onsite_days_per_week": 1, "work_mode": "hybrydowo"},
    )
    assert changed == ["onsite_days_per_week"]
    assert job.onsite_days_per_week == 1
    assert job.remote_policy == RemotePolicy.hybrid


def test_weekly_edit_clears_the_monthly_entry():
    """Audyt 05.10.2026: wpis tygodniowy czyści miesięczny, jak w PATCH."""
    job = _bare_job(onsite_days_per_week=1, remote_policy=RemotePolicy.hybrid)
    job.onsite_days_per_month = 2
    changed = overwrite_edited_job_columns(
        job,
        {"onsite_days_per_week": 1, "onsite_days_per_month": 2},
        {"onsite_days_per_week": 3},
    )
    assert sorted(changed) == ["onsite_days_per_month", "onsite_days_per_week"]
    assert job.onsite_days_per_week == 3
    assert job.onsite_days_per_month is None


def test_monthly_edit_reaches_the_recruitment_even_with_the_same_weekly_count():
    job = _bare_job(onsite_days_per_week=1, remote_policy=RemotePolicy.hybrid)
    changed = overwrite_edited_job_columns(
        job,
        {"onsite_days_per_week": 1},
        {"onsite_days_per_week": 1, "onsite_days_per_month": 4},
    )
    assert changed == ["onsite_days_per_month"]
    assert job.onsite_days_per_month == 4
    assert job.onsite_days_per_week == 1


def test_untouched_rubric_keeps_an_older_mismatch():
    # Profil 140, kolumna 150 z formularza zlecenia: zapis innego pola nie
    # rozstrzyga rozjazdu po cichu.
    job = _bare_job(rate_budget_hourly=150)
    basics = {"rate_value": 140, "candidate_location_pref": "Kraków"}
    assert overwrite_edited_job_columns(job, basics, dict(basics)) == []
    assert job.rate_budget_hourly == 150


def test_cleared_or_invalid_edit_leaves_the_column():
    job = _bare_job(
        rate_budget_hourly=150,
        onsite_days_per_week=2,
        remote_policy=RemotePolicy.onsite,
        location="Gdańsk",
    )
    changed = overwrite_edited_job_columns(
        job,
        {
            "rate_value": 150,
            "onsite_days_per_week": 2,
            "work_mode": "stacjonarnie",
            "candidate_location_pref": "Gdańsk",
        },
        {
            "rate_value": 5000,
            "onsite_days_per_week": None,
            "work_mode": "raz tak, raz tak",
            "candidate_location_pref": "",
        },
    )
    assert changed == []
    assert job.rate_budget_hourly == 150
    assert job.onsite_days_per_week == 2
    assert job.remote_policy == RemotePolicy.onsite
    assert job.location == "Gdańsk"


def test_edited_rubrics_overwrite_all_four_columns():
    job = _bare_job(
        rate_budget_hourly=150,
        onsite_days_per_week=0,
        remote_policy=RemotePolicy.onsite,
        location="Gdańsk",
    )
    changed = overwrite_edited_job_columns(
        job,
        {
            "rate_value": 150,
            "onsite_days_per_week": 0,
            "work_mode": "stacjonarnie",
            "candidate_location_pref": "Gdańsk",
        },
        {
            "rate_value": 120,
            "onsite_days_per_week": 2,
            "work_mode": "hybrydowo",
            "candidate_location_pref": "Warszawa",
        },
    )
    assert sorted(changed) == [
        "location",
        "onsite_days_per_week",
        "rate_budget_hourly",
        "remote_policy",
    ]
    assert job.rate_budget_hourly == 120
    assert job.onsite_days_per_week == 2
    assert job.remote_policy == RemotePolicy.hybrid
    assert job.location == "Warszawa"


async def test_editor_fix_of_office_days_reaches_the_recruitment(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zgłoszenie 30.09.2026: rekrutacja powstała z 0 dni przy hybrydzie,
    rekruterka wpisała 1 w edytorze Championa, „Zapisano” — a kolumna została 0
    i walidacja dalej mówiła „podaj dodatnią liczbę dni” (plus konflikt
    profilu z rekrutacją)."""
    import app.services.job_matching_refresh as job_matching_refresh_module

    async def _fake_refresh(job_id: int, db) -> None:
        return None

    monkeypatch.setattr(
        job_matching_refresh_module, "refresh_job_matching", _fake_refresh
    )

    job_id = await _seed_job_for_sync(
        rate_budget_hourly=120,
        onsite_days_per_week=0,
        remote_policy=RemotePolicy.hybrid,
        location="warszawa",
        champion_profile={
            "basics": {
                "role_name": "Senior Software Developer",
                "rate_value": 120,
                "onsite_days_per_week": 0,
                "work_mode": "hybrydowo",
                "candidate_location_pref": "warszawa",
            }
        },
    )

    resp = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        headers=app_auth_headers,
        json={"basics": {"onsite_days_per_week": 1}},
    )
    assert resp.status_code == 200, resp.text
    codes = {
        (issue.get("code"), issue.get("path"))
        for issue in (resp.json().get("validation") or {}).get("issues", [])
    }
    assert ("missing_office_days", "basics.onsite_days_per_week") not in codes
    assert ("column_conflict", "basics.onsite_days_per_week") not in codes

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.onsite_days_per_week == 1
        assert job.rate_budget_hourly == 120
        assert job.remote_policy == RemotePolicy.hybrid


async def test_deadline_typed_in_the_champion_editor_closes_the_term_gap(
    app_client: AsyncClient, app_auth_headers: dict, monkeypatch
):
    """Zgłoszenie 08.10.2026: bramka pytała „Ustaw termin”, a data wpisana
    w „Deadline na kandydatów” zostawała w profilu."""
    import app.services.job_matching_refresh as job_matching_refresh_module

    async def _fake_refresh(job_id: int, db) -> None:
        return None

    monkeypatch.setattr(
        job_matching_refresh_module, "refresh_job_matching", _fake_refresh
    )

    job_id = await _seed_job_for_sync(deadline_not_provided=True)
    upcoming = business_today() + timedelta(days=30)

    resp = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        headers=app_auth_headers,
        json={"basics": {"deadline": upcoming.isoformat()}},
    )
    assert resp.status_code == 200, resp.text

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        assert job.deadline == upcoming
        assert job.deadline_not_provided is False
