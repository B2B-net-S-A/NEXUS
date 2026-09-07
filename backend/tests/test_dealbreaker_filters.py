"""Dealbreaker-switche — kontrakty „nieznany przechodzi" i twardego sufitu.

Każda asercja o przechodzeniu nieznanych jest tu ŻELAZNA: filtr stażu przy
pokryciu 1,2% zredukował kiedyś lejek 11 091 → 45. Sufit budżetu jest TWARDY
i bez marginesu z decyzji produktowej 19.08 — pomiar z 18.08 (0% marginesu
ukrywa 44% realnie dowiezionych, bo stawki negocjuje się w dół) został przy
tej decyzji świadomie zaakceptowany; NIE przywracaj marginesu bez decyzji
właściciela produktu.
"""

from types import SimpleNamespace

from app.services.dealbreaker_filters import (
    DealbreakerInputs,
    apply_dealbreakers,
    budget_excludes,
    dealbreaker_inputs_for_job,
    missing_must_skills,
    office_city_mismatch,
    office_days_exceeded,
    remote_only_refuses_office,
    resolve_effective_remote_policy,
    resolve_job_budget_hourly,
)
from app.services.location_utils import candidate_location_tokens, candidate_office_tokens


def _cand(**kw):
    base = dict(
        expected_rate_hourly=None,
        expected_rate_currency=None,
        cv_extracted_data=None,
        location=None,
        city=None,
        skills=None,
        verified_tech=None,
        tags=None,
        max_onsite_days_per_week=None,
        raw_cv_text=None,
        preferences=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _notes(**prefs_kw):
    prefs = {
        "other": None,
        "locations": [],
        "remote_only": None,
        "sectors_avoid": [],
        "sectors_prefer": [],
    }
    prefs.update(prefs_kw)
    return {"_notes_insights": {"preferences": prefs}}


# ── budżet ───────────────────────────────────────────────────────────────────


def test_unknown_rate_always_passes():
    assert budget_excludes(_cand(), 100.0) is False
    # Niekanoniczna waluta = „nie wiemy", nie „za drogo".
    eur = _cand(expected_rate_hourly=500, expected_rate_currency="EUR")
    assert budget_excludes(eur, 100.0) is False


def test_hard_cap_is_strict_and_equal_passes():
    """Wpisana stawka = twardy sufit: powyżej ukryty, RÓWNY przechodzi."""
    over = _cand(expected_rate_hourly=101, expected_rate_currency="PLN")
    assert budget_excludes(over, 100.0) is True
    equal = _cand(expected_rate_hourly=100, expected_rate_currency="PLN")
    assert budget_excludes(equal, 100.0) is False
    under = _cand(expected_rate_hourly=99, expected_rate_currency="PLN")
    assert budget_excludes(under, 100.0) is False


def test_no_margin_is_ever_applied():
    """130 przy budżecie 100 jest UKRYTY — dawny margines +30% nie wraca."""
    cand = _cand(expected_rate_hourly=130, expected_rate_currency="PLN")
    assert budget_excludes(cand, 100.0) is True


def test_resolve_budget_prefers_explicit_field(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True, raising=False)
    job = SimpleNamespace(rate_budget_hourly=140, champion_profile={"rate_value": 999})
    assert resolve_job_budget_hourly(job) == 140.0
    fallback = SimpleNamespace(
        rate_budget_hourly=None, champion_profile={"rate_value": 120}
    )
    assert resolve_job_budget_hourly(fallback) == 120.0


def test_budget_filter_is_automatic_by_default():
    """Sama obecność budżetu aktywuje sufit — bez osobnego uzbrajania."""
    over = _cand(expected_rate_hourly=200, expected_rate_currency="PLN")
    res = apply_dealbreakers([over], budget_hourly=100.0)
    assert res.kept == [] and res.hidden_over_budget == 1


def test_apply_without_budget_is_noop():
    """Brak znanego budżetu oferty nie ukrywa nikogo (brak danych ≠ powód)."""
    cand = _cand(expected_rate_hourly=999, expected_rate_currency="PLN")
    res = apply_dealbreakers([cand], budget_hourly=None)
    assert res.kept == [cand] and res.hidden_over_budget == 0


def test_explicit_opt_out_shows_over_budget():
    """Konsument może jawnie wyłączyć sufit (widok „pokaż wszystkich")."""
    over = _cand(expected_rate_hourly=999, expected_rate_currency="PLN")
    res = apply_dealbreakers([over], exclude_over_budget=False, budget_hourly=100.0)
    assert res.kept == [over]


# ── biuro (remote_only z notatek) ────────────────────────────────────────────


def test_remote_only_true_excludes_false_and_none_pass():
    assert remote_only_refuses_office(_cand(cv_extracted_data=_notes(remote_only=True)))
    assert not remote_only_refuses_office(
        _cand(cv_extracted_data=_notes(remote_only=False))
    )
    assert not remote_only_refuses_office(_cand(cv_extracted_data=_notes()))
    assert not remote_only_refuses_office(_cand())  # brak notatek
    # cv_extracted_data bywa LISTĄ na prodzie — nie może się wywrócić.
    assert not remote_only_refuses_office(_cand(cv_extracted_data=["legacy"]))


def test_apply_counts_and_order_are_deterministic():
    over = _cand(
        expected_rate_hourly=200,
        expected_rate_currency="PLN",
        cv_extracted_data=_notes(remote_only=True),  # łapie OBA powody
    )
    remote = _cand(cv_extracted_data=_notes(remote_only=True))
    ok = _cand(expected_rate_hourly=90, expected_rate_currency="PLN")
    res = apply_dealbreakers(
        [over, remote, ok],
        budget_hourly=100.0,
        exclude_remote_only=True,
    )
    assert res.kept == [ok]
    # Budżet liczony PRZED biurem — kandydat z oboma powodami nie migruje.
    assert res.hidden_over_budget == 1
    assert res.hidden_remote_only == 1
    assert res.hidden_meta() == {
        "over_budget": 1,
        "missing_must": 0,
        "office_days_exceeded": 0,
        "office_city_mismatch": 0,
        "remote_only": 1,
    }


# ── źródła lokalizacji ───────────────────────────────────────────────────────


def test_location_sources_cv_notes_all():
    cand = _cand(
        city="Kraków",
        location="Kraków, małopolskie",
        cv_extracted_data={
            "_notes_insights": {
                "preferences": {"locations": ["Poznań"], "remote_only": None},
                "relocation": {"willing": True, "targets": ["Wrocław"]},
            }
        },
    )
    cv = candidate_location_tokens(cand, "cv")
    notes = candidate_location_tokens(cand, "notes")
    both = candidate_location_tokens(cand, "all")
    assert "kraków" in cv and "poznań" not in cv
    assert {"poznań", "wrocław"} <= notes and "kraków" not in notes
    assert {"kraków", "poznań", "wrocław"} <= both


def test_office_cities_override_notes_locations():
    """Ludzkie `preferences.office_cities` (0278) nadpisują notatkowe
    lokalizacje w kubełku `all` — `relocation.targets` mimo to dokłada się
    zawsze (inny fakt: dokąd kandydat CHCE się przeprowadzić)."""
    cand = _cand(
        preferences={"office_cities": ["Gdańsk"]},
        cv_extracted_data={
            "_notes_insights": {
                "preferences": {"locations": ["Poznań"], "remote_only": None},
                "relocation": {"willing": True, "targets": ["Wrocław"]},
            }
        },
    )
    both = candidate_location_tokens(cand, "all")
    assert "gdańsk" in both
    assert "poznań" not in both
    assert "wrocław" in both


def test_office_cities_in_cv_bucket_not_notes():
    """`office_cities` żyje w kubełku `cv`/`all`; `notes` w izolacji zostaje
    czysto-AI — `office_cities` nigdy nie jest tam czytane, więc nie przesłania
    notatkowych lokalizacji, gdy ktoś pyta o samo źródło `notes`."""
    cand = _cand(
        preferences={"office_cities": ["Gdańsk"]},
        cv_extracted_data=_notes(locations=["Poznań"]),
    )
    assert "gdańsk" in candidate_location_tokens(cand, "cv")
    notes = candidate_location_tokens(cand, "notes")
    assert "gdańsk" not in notes
    assert "poznań" in notes


def test_relocation_unwilling_targets_are_not_locations():
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {
                "preferences": {"locations": []},
                "relocation": {"willing": False, "targets": ["Berlin"]},
            }
        }
    )
    assert "berlin" not in candidate_location_tokens(cand, "notes")


def test_location_sources_survive_list_shaped_extracted_data():
    cand = _cand(city="Łódź", cv_extracted_data=["legacy", "list"])
    assert "łódź" in candidate_location_tokens(cand, "all")
    assert candidate_location_tokens(cand, "notes") == set()


# ── kontrakt API radaru: budżet aktywuje się sam, margines nie istnieje ──────


def test_radar_budget_presence_is_the_whole_contract():
    from app.api.talent_radar import TalentRadarSearchRequest

    req = TalentRadarSearchRequest(client_id=1, text="x", budget_hourly_max=150)
    assert req.budget_hourly_max == 150.0
    # Decyzja 19.08: bez marginesu i bez osobnego przełącznika — pola nie
    # mogą wrócić do modelu cichym refaktorem.
    assert "budget_margin_pct" not in TalentRadarSearchRequest.model_fields
    assert "exclude_over_budget" not in TalentRadarSearchRequest.model_fields


# ── rubryki 0278: must-have / dni w biurze / miasto biura ───────────────────


def test_missing_must_hides_only_with_positive_skill_signal():
    """Kandydat z UMIEJĘTNOŚCIAMI, ale bez jednego must, jest ukryty i policzony.

    Kandydat bez ŻADNEGO sygnału umiejętności przechodzi — „nieznany przechodzi"
    dotyczy tej rubryki dokładnie tak samo jak budżetu.
    """
    has_java_only = _cand(skills=[{"name": "Java"}])
    assert missing_must_skills(has_java_only, ["java", "kafka"]) == ["kafka"]

    no_signal = _cand()
    assert missing_must_skills(no_signal, ["java", "kafka"]) == []


def test_missing_must_is_noop_without_explicit_must():
    cand = _cand(skills=[{"name": "Python"}])
    assert missing_must_skills(cand, []) == []
    assert missing_must_skills(cand, ()) == []


def test_missing_must_honours_alias_family():
    """`MSSQL` (kandydat) spełnia must `SQL Server` — rodzina aliasów."""
    from app.services import scoring_service as ss

    saved = dict(ss.ALIAS_MAP)
    try:
        ss.set_alias_map({"mssql": "sql server"})
        cand = _cand(skills=[{"name": "MSSQL"}])
        must = ss.canonical_skill_names(["SQL Server"])
        assert missing_must_skills(cand, must) == []
    finally:
        ss.set_alias_map(saved)


def test_missing_must_skills_returns_the_gap_list():
    cand = _cand(skills=[{"name": "Python"}, {"name": "Django"}])
    gaps = missing_must_skills(cand, ["python", "kafka", "kubernetes"])
    assert gaps == ["kafka", "kubernetes"]


def test_office_days_exceeded_is_strict_and_unknown_passes():
    below = _cand(max_onsite_days_per_week=2)
    at_threshold = _cand(max_onsite_days_per_week=3)
    unknown = _cand(max_onsite_days_per_week=None)

    assert office_days_exceeded(below, 3) is True
    assert office_days_exceeded(at_threshold, 3) is False
    assert office_days_exceeded(unknown, 3) is False
    # Brak wymogu (None albo 0) = no-op, niezależnie od deklaracji kandydata.
    assert office_days_exceeded(below, None) is False
    assert office_days_exceeded(below, 0) is False


def test_office_city_mismatch_needs_days_and_office():
    office_tokens = frozenset({"warszawa"})
    cand_match = _cand(location="Warszawa, mazowieckie")
    cand_mismatch = _cand(location="Kraków")
    cand_remote_only = _cand(location="Remote")  # tokeny nie-miejsc, przechodzi

    # Bez wymaganych dni — no-op, mimo realnego rozjazdu miast.
    assert office_city_mismatch(cand_mismatch, office_tokens, required_days=0) is False
    assert (
        office_city_mismatch(cand_mismatch, office_tokens, required_days=None) is False
    )
    # Bez zadeklarowanego miasta oferty — no-op.
    assert office_city_mismatch(cand_mismatch, frozenset(), required_days=3) is False
    # Kandydat bez ŻADNEGO znanego miejsca — nieznany przechodzi.
    assert (
        office_city_mismatch(cand_remote_only, office_tokens, required_days=3) is False
    )
    # Prawdziwe dopasowanie i prawdziwy rozjazd.
    assert office_city_mismatch(cand_match, office_tokens, required_days=3) is False
    assert office_city_mismatch(cand_mismatch, office_tokens, required_days=3) is True


def test_office_city_accepts_notes_locations_and_willing_relocation():
    office_tokens = frozenset({"warszawa"})
    from_notes = _cand(
        location="Kraków",
        cv_extracted_data=_notes(locations=["Warszawa"]),
    )
    assert office_city_mismatch(from_notes, office_tokens, required_days=3) is False

    # `relocation.willing=False` NIE liczy się jako lokalizacja kandydata —
    # kierunek, na który się nie godzi, nie jest jego miejscem.
    unwilling = _cand(
        location="Kraków",
        cv_extracted_data={
            "_notes_insights": {
                "preferences": {"locations": [], "remote_only": None},
                "relocation": {"willing": False, "targets": ["Warszawa"]},
            }
        },
    )
    assert office_city_mismatch(unwilling, office_tokens, required_days=3) is True


def test_remote_only_auto_arms_on_wants_office():
    remote_only_cand = _cand(cv_extracted_data=_notes(remote_only=True))

    wants_office = DealbreakerInputs(wants_office=True)
    res = apply_dealbreakers([remote_only_cand], inputs=wants_office)
    assert res.kept == [] and res.hidden_remote_only == 1

    no_office = DealbreakerInputs(wants_office=False)
    res = apply_dealbreakers([remote_only_cand], inputs=no_office)
    assert res.kept == [remote_only_cand] and res.hidden_remote_only == 0

    # Jawne `exclude_remote_only` nadpisuje AUTO w obie strony.
    res = apply_dealbreakers(
        [remote_only_cand], inputs=no_office, exclude_remote_only=True
    )
    assert res.kept == [] and res.hidden_remote_only == 1


def test_hidden_meta_always_has_five_int_keys():
    from app.services.dealbreaker_filters import DealbreakerResult

    meta = DealbreakerResult().hidden_meta()
    assert meta == {
        "over_budget": 0,
        "missing_must": 0,
        "office_days_exceeded": 0,
        "office_city_mismatch": 0,
        "remote_only": 0,
    }
    assert all(isinstance(v, int) for v in meta.values())


def test_reason_order_budget_must_days_city_remote():
    """Kandydat łapiący WSZYSTKIE pięć powodów jest liczony raz — pod budżetem."""
    catches_everything = _cand(
        expected_rate_hourly=999,
        expected_rate_currency="PLN",
        skills=[{"name": "Java"}],  # ma sygnał, ale nie ma wymaganego "python"
        max_onsite_days_per_week=0,
        location="Kraków",
        cv_extracted_data=_notes(remote_only=True),
    )
    inputs = DealbreakerInputs(
        budget_hourly=100.0,
        must_skills=("python",),
        onsite_days_per_week=3,
        office_tokens=frozenset({"warszawa"}),
        wants_office=True,
    )
    res = apply_dealbreakers([catches_everything], inputs=inputs)
    assert res.kept == []
    assert res.hidden_meta() == {
        "over_budget": 1,
        "missing_must": 0,
        "office_days_exceeded": 0,
        "office_city_mismatch": 0,
        "remote_only": 0,
    }


def test_dealbreaker_inputs_for_job_reads_columns_then_champion(monkeypatch):
    from app.core.config import settings

    # Kolumny wygrywają zawsze, niezależnie od treści Championa.
    job_with_columns = SimpleNamespace(
        rate_budget_hourly=150,
        must_skills=[{"name": "Python"}],
        onsite_days_per_week=2,
        location="Warszawa",
        remote_policy=SimpleNamespace(value="hybrid"),
        champion_profile={
            "basics": {
                "rate_value": 999,
                "onsite_days_per_week": 5,
                "work_mode": "zdalnie",
                "candidate_location_pref": "Kraków",
            }
        },
    )
    inputs = dealbreaker_inputs_for_job(job_with_columns)
    assert inputs.budget_hourly == 150.0
    assert inputs.must_skills == ("python",)
    assert inputs.onsite_days_per_week == 2
    assert "warszawa" in inputs.office_tokens
    assert inputs.wants_office is True

    # Bez kolumn, flaga WYŁĄCZONA (domyślnie w testach) — Champion nietknięty
    # dla budżetu/dni/lokalizacji (must-have Tier 0 zostaje bezwarunkowe).
    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", False, raising=False)
    job_champion_only = SimpleNamespace(
        rate_budget_hourly=None,
        must_skills=None,
        onsite_days_per_week=None,
        location=None,
        remote_policy=None,
        champion_profile={
            "basics": {
                "rate_value": 200,
                "onsite_days_per_week": 3,
                "work_mode": "hybrydowo",
                "candidate_location_pref": "Poznań",
            }
        },
    )
    inputs = dealbreaker_inputs_for_job(job_champion_only)
    assert inputs.budget_hourly is None
    assert inputs.onsite_days_per_week is None
    assert inputs.office_tokens == frozenset()
    assert inputs.wants_office is False

    # Flaga WŁĄCZONA — Champion wypełnia braki.
    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True, raising=False)
    inputs = dealbreaker_inputs_for_job(job_champion_only)
    assert inputs.budget_hourly == 200.0
    assert inputs.onsite_days_per_week == 3
    assert "poznań" in inputs.office_tokens
    assert inputs.wants_office is True

    # Obiekt bez ŻADNYCH atrybutów rubryk — same None/puste, bez AttributeError.
    bare = SimpleNamespace()
    inputs = dealbreaker_inputs_for_job(bare)
    assert inputs.budget_hourly is None
    assert inputs.must_skills == ()
    assert inputs.onsite_days_per_week is None
    assert inputs.office_tokens == frozenset()
    assert inputs.wants_office is False
    assert resolve_effective_remote_policy(bare) is None


def test_kill_switch_restores_pre_rubric_behaviour(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUBRIC_DEALBREAKERS_ENABLED", False, raising=False)

    missing_must_and_over_budget = _cand(
        expected_rate_hourly=200,
        expected_rate_currency="PLN",
        skills=[{"name": "Java"}],
    )
    inputs = DealbreakerInputs(
        budget_hourly=100.0,
        must_skills=("python",),
        onsite_days_per_week=3,
        office_tokens=frozenset({"warszawa"}),
        wants_office=True,
    )
    res = apply_dealbreakers([missing_must_and_over_budget], inputs=inputs)
    # Tylko budżet — jedyny dealbreaker sprzed 0278 — pozostaje aktywny.
    assert res.kept == [] and res.hidden_over_budget == 1
    assert res.hidden_missing_must == 0

    # Kandydat bez must-have, ale W budżecie: rubryka must jest no-opem, więc
    # przechodzi, mimo `wants_office=True` w inputs (AUTO remote_only też
    # jest wygaszone).
    remote_only_missing_must = _cand(
        expected_rate_hourly=50,
        expected_rate_currency="PLN",
        skills=[{"name": "Java"}],
        cv_extracted_data=_notes(remote_only=True),
    )
    res = apply_dealbreakers([remote_only_missing_must], inputs=inputs)
    assert res.kept == [remote_only_missing_must]
    assert res.hidden_meta() == {
        "over_budget": 0,
        "missing_must": 0,
        "office_days_exceeded": 0,
        "office_city_mismatch": 0,
        "remote_only": 0,
    }


def test_legacy_kwargs_unchanged():
    """Wywołanie sprzed 0278 (bez `inputs`) daje IDENTYCZNY wynik jak dziś."""
    over = _cand(expected_rate_hourly=999, expected_rate_currency="PLN")
    ok = _cand(expected_rate_hourly=50, expected_rate_currency="PLN")
    remote = _cand(cv_extracted_data=_notes(remote_only=True))

    res = apply_dealbreakers(
        [over, ok, remote], budget_hourly=100.0, exclude_remote_only=True
    )
    assert res.kept == [ok]
    assert res.hidden_over_budget == 1
    assert res.hidden_remote_only == 1
    assert res.hidden_missing_must == 0
    assert res.hidden_office_days_exceeded == 0
    assert res.hidden_office_city_mismatch == 0


def test_candidate_office_tokens_strips_non_places():
    mixed = _cand(location="Kraków / remote")
    assert candidate_office_tokens(mixed) == {"kraków"}

    remote_only = _cand(location="remote")
    assert candidate_office_tokens(remote_only) == set()
