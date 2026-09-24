"""Fakty z telefonu praktykanta (0374) w bramce dealbreakerów — bez bazy.

`expected_rate_hourly` jest MINIMUM kandydata, więc sufit budżetu znaczy
„budżet poniżej minimum". Zgoda na telefon z taką ofertą (albo z większą liczbą
dni w biurze) zostawia kandydata widocznym z osobnym statusem; „tylko umowa
o pracę" ukrywa. Sprzeczny wymiar pracy od 24.09.2026 tylko ostrzega (decyzja
Artura: plakietka, nie ukrycie). Brak odpowiedzi nigdy nie ukrywa.
"""

from types import SimpleNamespace

from app.services.dealbreaker_filters import (
    DealbreakerInputs,
    DealbreakerResult,
    apply_dealbreakers,
    dealbreaker_inputs_for_job,
    office_fit_status,
    rate_fit_status,
    work_time_fit_status,
    work_time_mismatch,
)


def _cand(cid=1, **kw):
    base = dict(
        id=cid,
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
        b2b_willingness=None,
        accepts_below_min_rate=None,
        accepts_more_office_days=None,
        work_time_preference=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ── tylko umowa o pracę ──────────────────────────────────────────────────────


def test_employment_only_is_hidden_with_its_own_reason():
    cand = _cand(b2b_willingness="employment_only")
    res = apply_dealbreakers([cand], inputs=DealbreakerInputs())
    assert res.kept == []
    assert res.hidden_employment_only == 1
    assert res.exclusion_reasons == {1: "employment_only"}
    assert res.hidden_meta()["employment_only"] == 1


def test_employment_only_wins_over_budget_and_survives_rubric_kill_switch(
    monkeypatch,
):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RUBRIC_DEALBREAKERS_ENABLED", False)
    cand = _cand(
        b2b_willingness="employment_only",
        expected_rate_hourly=999,
        expected_rate_currency="PLN",
    )
    res = apply_dealbreakers(
        [cand], inputs=DealbreakerInputs(budget_hourly=100.0), exclude_over_budget=False
    )
    assert res.kept == []
    assert res.hidden_employment_only == 1 and res.hidden_over_budget == 0


def test_b2b_and_would_switch_pass():
    kept = apply_dealbreakers(
        [_cand(1, b2b_willingness="b2b"), _cand(2, b2b_willingness="would_switch")],
        inputs=DealbreakerInputs(),
    ).kept
    assert [c.id for c in kept] == [1, 2]


# ── minimum stawki i zgoda ───────────────────────────────────────────────────


def test_below_min_with_consent_stays_visible():
    inputs = DealbreakerInputs(budget_hourly=120.0)
    cand = _cand(
        expected_rate_hourly=150,
        expected_rate_currency="PLN",
        accepts_below_min_rate=True,
    )
    res = apply_dealbreakers([cand], inputs=inputs)
    assert res.kept == [cand] and res.hidden_over_budget == 0
    assert rate_fit_status(cand, inputs) == "below_min_consented"


def test_below_min_without_consent_is_hidden():
    inputs = DealbreakerInputs(budget_hourly=120.0)
    refused = _cand(
        1,
        expected_rate_hourly=150,
        expected_rate_currency="PLN",
        accepts_below_min_rate=False,
    )
    unknown = _cand(2, expected_rate_hourly=150, expected_rate_currency="PLN")
    res = apply_dealbreakers([refused, unknown], inputs=inputs)
    assert res.kept == []
    assert res.hidden_over_budget == 2
    assert rate_fit_status(refused, inputs) == "over_budget"
    assert rate_fit_status(unknown, inputs) == "over_budget"


def test_consent_does_not_change_in_budget_status():
    inputs = DealbreakerInputs(budget_hourly=120.0)
    cand = _cand(
        expected_rate_hourly=100,
        expected_rate_currency="PLN",
        accepts_below_min_rate=True,
    )
    assert rate_fit_status(cand, inputs) == "ok"


# ── dni w biurze i zgoda ─────────────────────────────────────────────────────


def test_more_office_days_with_consent_stays_visible():
    inputs = DealbreakerInputs(onsite_days_per_week=3)
    cand = _cand(max_onsite_days_per_week=1, accepts_more_office_days=True)
    res = apply_dealbreakers([cand], inputs=inputs)
    assert res.kept == [cand] and res.hidden_office_days_exceeded == 0
    assert office_fit_status(cand, inputs) == "over_consented"


def test_more_office_days_without_consent_is_hidden():
    inputs = DealbreakerInputs(onsite_days_per_week=3)
    cand = _cand(max_onsite_days_per_week=1, accepts_more_office_days=False)
    res = apply_dealbreakers([cand], inputs=inputs)
    assert res.kept == [] and res.hidden_office_days_exceeded == 1
    assert office_fit_status(cand, inputs) == "days_exceeded"


# ── wymiar pracy ─────────────────────────────────────────────────────────────


def test_part_time_only_stays_visible_with_a_badge_on_fulltime_job():
    """Decyzja Artura 24.09.2026: „tylko part-time" to plakietka, nie ukrycie.

    Każda rekrutacja ma dziś `work_mode = fulltime` (nic w repo nie ustawia
    `parttime`), więc ukrywanie wycinało te osoby z KAŻDEGO dopasowania.
    """
    inputs = DealbreakerInputs(job_work_mode="fulltime")
    cand = _cand(work_time_preference="part_time_only")
    res = apply_dealbreakers([cand], inputs=inputs)
    assert res.kept == [cand]
    assert res.hidden_work_time_mismatch == 0
    assert res.exclusion_reasons == {}
    assert work_time_fit_status(cand, inputs) == "part_time_only"


def test_full_time_only_stays_visible_with_a_badge_on_parttime_job():
    inputs = DealbreakerInputs(job_work_mode="parttime")
    cand = _cand(work_time_preference="full_time_only")
    res = apply_dealbreakers([cand], inputs=inputs)
    assert res.kept == [cand] and res.hidden_work_time_mismatch == 0
    assert work_time_fit_status(cand, inputs) == "full_time_only"


def test_work_time_fit_status_values():
    full = DealbreakerInputs(job_work_mode="fulltime")
    assert (
        work_time_fit_status(_cand(work_time_preference="also_part_time"), full) == "ok"
    )
    assert (
        work_time_fit_status(_cand(work_time_preference="full_time_only"), full) == "ok"
    )
    assert work_time_fit_status(_cand(), full) == "unknown"
    assert (
        work_time_fit_status(
            _cand(work_time_preference="part_time_only"),
            DealbreakerInputs(job_work_mode="contract"),
        )
        == "not_applicable"
    )
    assert (
        work_time_fit_status(
            _cand(work_time_preference="part_time_only"), DealbreakerInputs()
        )
        == "not_applicable"
    )


def test_compatible_work_time_passes():
    assert not work_time_mismatch(
        _cand(work_time_preference="also_part_time"), "fulltime"
    )
    assert not work_time_mismatch(
        _cand(work_time_preference="also_part_time"), "parttime"
    )
    assert not work_time_mismatch(
        _cand(work_time_preference="full_time_only"), "fulltime"
    )
    assert not work_time_mismatch(
        _cand(work_time_preference="part_time_only"), "parttime"
    )
    # Projekt (`contract`) i brak wymiaru (Talent Radar) nie bramkują.
    assert not work_time_mismatch(
        _cand(work_time_preference="part_time_only"), "contract"
    )
    assert not work_time_mismatch(_cand(work_time_preference="part_time_only"), None)


def test_work_time_never_hides_even_alongside_other_reasons():
    inputs = DealbreakerInputs(budget_hourly=100.0, job_work_mode="fulltime")
    over = _cand(
        expected_rate_hourly=999,
        expected_rate_currency="PLN",
        work_time_preference="part_time_only",
    )
    ok = _cand(2, work_time_preference="part_time_only")
    res = apply_dealbreakers([over, ok], inputs=inputs)
    assert res.hidden_over_budget == 1 and res.hidden_work_time_mismatch == 0
    assert res.kept == [ok]


def test_inputs_for_job_read_work_mode_enum_and_string():
    enum_job = SimpleNamespace(work_mode=SimpleNamespace(value="parttime"))
    string_job = SimpleNamespace(work_mode="fulltime")
    assert dealbreaker_inputs_for_job(enum_job).job_work_mode == "parttime"
    assert dealbreaker_inputs_for_job(string_job).job_work_mode == "fulltime"
    assert dealbreaker_inputs_for_job(SimpleNamespace()).job_work_mode is None


# ── brak danych przechodzi ───────────────────────────────────────────────────


def test_missing_trainee_facts_never_hide():
    inputs = DealbreakerInputs(
        budget_hourly=120.0, onsite_days_per_week=3, job_work_mode="fulltime"
    )
    blank = SimpleNamespace(
        id=1,
        expected_rate_hourly=None,
        expected_rate_currency=None,
        cv_extracted_data=None,
        skills=None,
        verified_tech=None,
        tags=None,
        max_onsite_days_per_week=None,
        raw_cv_text=None,
    )  # stary obiekt bez kolumn 0374 — getattr zwraca None
    res = apply_dealbreakers([blank, _cand(2)], inputs=inputs)
    assert [c.id for c in res.kept] == [1, 2]
    assert sum(res.hidden_meta().values()) == 0


def test_hidden_meta_carries_new_reasons():
    meta = DealbreakerResult().hidden_meta()
    assert meta["employment_only"] == 0
    assert meta["work_time_mismatch"] == 0
