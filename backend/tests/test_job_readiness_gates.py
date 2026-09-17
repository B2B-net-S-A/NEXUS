"""Bramka gotowości do handoffu (0278): trzy rubryki rekrutacji.

`job_handoff_blockers` (brief + rubryki) jest czystą, synchroniczną funkcją — testy budują
`SimpleNamespace` zamiast realnego ORM `Job`, bo bramka czyta WYŁĄCZNIE to,
co `dealbreaker_inputs_for_job`/`resolve_effective_remote_policy` faktycznie
odczytują przez `getattr`. Kolejność blokerów jest STAŁA: tytuł → klient →
kontekst projektu → pytania screeningowe → must-have → budżet → tryb pracy →
dni w biurze → miasto biura.

Budżet jest ZAWSZE wymagany (decyzja produktowa 07.09), niezależnie od trybu
pracy. Dni w biurze i miasto biura są wymagane TYLKO przy `onsite`/`hybrid`.
"""

from types import SimpleNamespace

from app.services.job_readiness import (
    job_handoff_blockers,
    job_readiness_blockers,
    job_rubric_blockers,
)

_MUST_HAVE_MSG = (
    "Dodaj co najmniej jedną technologię must-have (pole oferty lub "
    "sekcja „Stack technologiczny” w Profilu Championa)."
)
_BUDGET_MSG = (
    "Uzupełnij budżet stawki kandydata w PLN/h (pole oferty lub "
    "stawka w Profilu Championa)."
)
_WORK_MODE_MSG = "Określ tryb pracy: zdalnie, hybrydowo albo stacjonarnie."
_DAYS_MSG = "Podaj liczbę dni w biurze w tygodniu (tryb hybrydowy/stacjonarny)."
_CITY_MSG = "Podaj miasto biura w lokalizacji oferty (tryb hybrydowy/stacjonarny)."

_READY_CHAMPION = {
    "project_context": {
        "about": "Platforma płatności B2B",
        "responsibilities": "Rozwój usług backendowych",
    },
    "screening_questions": [
        {"id": "q1", "question": "Doświadczenie z Pythonem?"},
        {"id": "q2", "question": "Doświadczenie z Postgres?"},
    ],
}


def _job(**kw) -> SimpleNamespace:
    """Oferta „gotowa" — każdy test nadpisuje TYLKO to, co bada."""
    base = dict(
        title="Senior Python Developer",
        client_id=1,
        champion_profile=_READY_CHAMPION,
        must_skills=[{"name": "Python"}],
        rate_budget_hourly=150,
        remote_policy="remote",
        onsite_days_per_week=None,
        location=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_ready_job_has_no_blockers():
    assert job_handoff_blockers(_job()) == []


def test_missing_must_blocks_with_exact_polish_string():
    blockers = job_handoff_blockers(_job(must_skills=None))
    assert _MUST_HAVE_MSG in blockers


def test_prose_only_must_haves_satisfy_the_must_rule():
    """~70% ofert ma w `must_skills` punkty wymagań prozą. Nie bramkują one
    rankingu (`must_skills_ignored`), ale Delivery Lead je PODAŁ — handoff nie
    może odsyłać go po technologię, którą już wpisał zdaniem."""
    from app.services.dealbreaker_filters import dealbreaker_inputs_for_job

    job = _job(
        must_skills=[
            {"name": "apache kafka – minimum 4 lata komercyjnego doświadczenia"},
            {"name": "gotowość do pracy hybrydowej w warszawie"},
        ]
    )
    inputs = dealbreaker_inputs_for_job(job)
    assert inputs.must_skills == () and inputs.must_skills_ignored
    assert _MUST_HAVE_MSG not in job_handoff_blockers(job)
    assert _MUST_HAVE_MSG not in job_rubric_blockers(job)


def test_champion_stack_must_satisfies_the_must_rule():
    """Bez kolumny `must_skills`, Tier 0 Championa (sekcja 3) wystarcza —
    bezwarunkowo, bez flagi: `job_explicit_must_skills` NIE jest gated przez
    `CHAMPION_MATCH_SIGNALS_ENABLED` (scoring czyta Tier 0 tak samo)."""
    champion = {**_READY_CHAMPION, "stack": {"must": [{"name": "Kubernetes"}]}}
    blockers = job_handoff_blockers(_job(must_skills=None, champion_profile=champion))
    assert _MUST_HAVE_MSG not in blockers


def test_missing_budget_blocks_and_champion_rate_fills_it_only_when_flag_on(
    monkeypatch,
):
    from app.core.config import settings

    champion = {**_READY_CHAMPION, "basics": {"rate_value": 180}}
    job = _job(rate_budget_hourly=None, champion_profile=champion)

    monkeypatch.setattr(
        settings, "CHAMPION_MATCH_SIGNALS_ENABLED", False, raising=False
    )
    assert _BUDGET_MSG in job_handoff_blockers(job)

    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True, raising=False)
    assert _BUDGET_MSG not in job_handoff_blockers(job)


def test_unknown_work_mode_blocks():
    blockers = job_handoff_blockers(_job(remote_policy=None))
    assert _WORK_MODE_MSG in blockers


def test_champion_work_mode_resolves_policy(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True, raising=False)
    champion = {**_READY_CHAMPION, "basics": {"work_mode": "zdalnie"}}
    blockers = job_handoff_blockers(_job(remote_policy=None, champion_profile=champion))
    assert _WORK_MODE_MSG not in blockers
    # Zdalna oferta NIGDY nie pyta o dni/miasto biura.
    assert _DAYS_MSG not in blockers
    assert _CITY_MSG not in blockers


def test_hybrid_requires_days_and_office_city():
    both_missing = job_handoff_blockers(
        _job(remote_policy="hybrid", onsite_days_per_week=None, location=None)
    )
    assert _DAYS_MSG in both_missing
    assert _CITY_MSG in both_missing

    # Każdy bloker czyszczony NIEZALEŻNIE od drugiego.
    only_days_missing = job_handoff_blockers(
        _job(remote_policy="hybrid", onsite_days_per_week=3, location=None)
    )
    assert _DAYS_MSG not in only_days_missing
    assert _CITY_MSG in only_days_missing

    only_city_missing = job_handoff_blockers(
        _job(remote_policy="hybrid", onsite_days_per_week=None, location="Warszawa")
    )
    assert _DAYS_MSG in only_city_missing
    assert _CITY_MSG not in only_city_missing


def test_zero_onsite_days_is_known_not_missing():
    """`onsite_days_per_week == 0` jest ZNANĄ wartością (hybrydowo, zero dni w
    biurze ustalonych z góry) — nie blokuje, dokładnie jak dealbreaker dni,
    dla którego `requires_office_days` jest `False` przy zerze. Miasto biura
    zostaje OSOBNYM, niezależnym wymogiem — zero dni go nie zastępuje."""
    blockers = job_handoff_blockers(
        _job(remote_policy="hybrid", onsite_days_per_week=0, location="Warszawa")
    )
    assert _DAYS_MSG not in blockers
    assert _CITY_MSG not in blockers


def test_remote_job_never_asks_for_office_details():
    blockers = job_handoff_blockers(
        _job(remote_policy="remote", onsite_days_per_week=None, location=None)
    )
    assert _DAYS_MSG not in blockers
    assert _CITY_MSG not in blockers


def test_existing_champion_blockers_still_come_first():
    """Kontekst projektu i pytania screeningowe (P0-A) poprzedzają trzy nowe
    blokery rubryk — bramka jest ROZBUDOWANA, nie przepisana od nowa."""
    job = _job(
        champion_profile=None,
        must_skills=None,
        rate_budget_hourly=None,
        remote_policy=None,
    )
    blockers = job_handoff_blockers(job)
    context_idx = next(i for i, b in enumerate(blockers) if "kontekst projektu" in b)
    questions_idx = next(
        i for i, b in enumerate(blockers) if "pytania screeningowe" in b
    )
    must_idx = blockers.index(_MUST_HAVE_MSG)
    assert context_idx < must_idx
    assert questions_idx < must_idx


def test_allocation_gate_stays_free_of_the_rubrics():
    """Rubryki NIE mogą wjechać do bramki, którą czyta automatyczna alokacja.

    `recruitment_allocation` parkuje żądanie jako `brief_not_ready`, gdy
    `job_readiness_blockers` cokolwiek zwróci. Dorzucenie tam rubryk zatrzymałoby
    przydzielanie rekruterów dla każdej rekrutacji bez must-have/budżetu/trybu —
    czyli po cichu wyłączyłoby cudzą, świeżo wdrożoną funkcję. Objaw byłby
    niewidoczny (żądania czekają z powodem „brief_not_ready"), więc granica musi
    być zamrożona testem, nie tylko komentarzem.
    """
    # Brief kompletny, rubryki puste — dokładnie stan, w którym alokacja MUSI
    # działać, a handoff MUSI odmówić.
    job = _job(must_skills=None, rate_budget_hourly=None, remote_policy=None)

    assert job_readiness_blockers(job) == [], (
        "bramka briefu widzi rubryki — alokacja przestanie przydzielać rekruterów"
    )
    assert job_rubric_blockers(job), "rubryki miały tu być puste"
    assert job_handoff_blockers(job) == (
        job_readiness_blockers(job) + job_rubric_blockers(job)
    )


def test_allocation_still_parks_an_incomplete_brief():
    """Odwrotna strona granicy: brief bez Championa nadal parkuje alokację."""
    job = _job(champion_profile=None)

    assert job_readiness_blockers(job), (
        "pusty Champion musi nadal blokować — inaczej rozdzielenie bramek "
        "rozbroiło tę, która chroni alokację"
    )


def test_handoff_list_names_each_gap_once_when_the_intake_gate_is_on(monkeypatch):
    """`_MIRRORED_VALIDATION_CODES` drops the Champion-draft phrasing of a gap
    already named by the brief/rubric gates. Visible only with the gate on —
    with it off `validation()` never puts `handoff` in `blocked_operations`,
    so the mirrored issue was never appended here in the first place."""
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", "true")
    champion = {
        **_READY_CHAMPION,
        "stack": {"must": [], "nice": []},
        "intake": {"policy_version": 1},
    }
    job = _job(must_skills=None, rate_budget_hourly=None, champion_profile=champion)

    blockers = job_handoff_blockers(job)

    assert blockers.count(_MUST_HAVE_MSG) == 1
    assert blockers.count(_BUDGET_MSG) == 1
    assert not any("rzeczywiste wymagania MUST" in b for b in blockers)
    assert not any("Podaj jedną dodatnią stawkę" in b for b in blockers)


def test_handoff_list_keeps_validation_gaps_the_rubrics_cannot_see(monkeypatch):
    """A REAL addition (`column_conflict`) is not in `_MIRRORED_VALIDATION_CODES`
    and still surfaces — the filter drops duplicate phrasing, not the gate."""
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", "true")
    champion = {
        **_READY_CHAMPION,
        "basics": {"rate_value": 180},
        "intake": {"policy_version": 1},
    }
    job = _job(champion_profile=champion, rate_budget_hourly=200)

    blockers = job_handoff_blockers(job)

    assert "Profil i pola rekrutacji mają różne wartości. Uzgodnij je." in blockers


def test_handoff_list_keeps_a_champion_gap_the_rubric_does_not_name(monkeypatch):
    """Rozjazd bramek zostaje widoczny: hybryda z ZEREM dni to dla rubryki znana
    wartość (brak blokera), a dla walidacji Championa brak dodatniej liczby dni.
    Issue nie może zniknąć tylko dlatego, że jego kod jest „lustrzany" — pusta
    lista braków przy przycisku, który po kliknięciu dostaje 422 z
    ``enforce_operation``, byłaby kłamstwem."""
    monkeypatch.setenv("CHAMPION_INTAKE_GATE_ENABLED", "true")
    champion = {
        **_READY_CHAMPION,
        "stack": {"must": [{"name": "Python"}], "nice": []},
        "intake": {"policy_version": 1},
    }
    job = _job(
        champion_profile=champion,
        remote_policy="hybrid",
        onsite_days_per_week=0,
        location="Warszawa",
    )

    blockers = job_handoff_blockers(job)

    assert _DAYS_MSG not in blockers
    assert "Dla obecności w biurze podaj dodatnią liczbę dni." in blockers
