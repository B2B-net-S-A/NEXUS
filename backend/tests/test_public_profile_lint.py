"""Kontrola publicznego opisu rekrutacji i slugi strony kariery (czyste funkcje).

Bez bazy: reguły, które decydują, czy nazwa klienta albo stawka trafi na
publiczny LinkedIn, muszą być sprawdzalne wprost.
"""

from __future__ import annotations

import pytest

from app.services import career_slugs
from app.services.career_consent import CONSENT_TEXT, CONSENT_TEXT_VERSION
from app.services.public_apply import parse_optional_fields
from app.services.public_profile_lint import lint_public_texts


def _codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_client_name_is_found_case_and_diacritics_insensitive():
    findings = lint_public_texts(
        ["Projekt dla ŁÓDZKIEGO banku", "Praca w zespole pko bank polski nad CRM."],
        client_names=["PKO Bank Polski S.A."],
    )
    assert _codes(findings) == ["client_name"]
    assert "pko bank polski" in findings[0].excerpt.lower()


def test_client_alias_is_found():
    findings = lint_public_texts(
        ["Rozwój platformy mBanku dla klientów detalicznych."],
        client_names=["mBank S.A.", "mBanku"],
    )
    assert "client_name" in _codes(findings)


def test_client_name_needs_whole_words():
    # „ing" jako fragment słowa („marketing") nie jest nazwą ING.
    findings = lint_public_texts(
        ["Zespół marketingowy i testing automatyczny."], client_names=["ING"]
    )
    assert findings == []


@pytest.mark.parametrize(
    "text",
    [
        "Budżet do 180 zł/h",
        "Stawka 150 PLN netto",
        "25 000 PLN miesięcznie",
        "do 20k PLN",
        "180/h B2B",
        "1200 / MD",
        "stawka do negocjacji w okolicach 170",
        "PLN 140",
        "oferujemy 15 tys. zł",
    ],
)
def test_money_is_found(text: str):
    findings = lint_public_texts([text])
    assert _codes(findings) == ["money"], text
    assert findings[0].message.startswith("Wykryto kwotę")


@pytest.mark.parametrize(
    "text",
    [
        "Java 17+ i Spring Boot 3",
        "Start 10.2026, projekt na 12+ miesięcy",
        "2 dni w tygodniu w biurze w Warszawie",
        "Kubernetes, Kafka, PostgreSQL 16",
    ],
)
def test_ordinary_technical_text_is_clean(text: str):
    assert lint_public_texts([text]) == []


def test_contact_and_person_names_are_found():
    findings = lint_public_texts(
        [
            "Pisz na marta.nowak@b2bnetwork.pl albo dzwoń 600 111 222.",
            "Proces prowadzi Marta Nowak.",
        ],
        person_names=["Marta Nowak"],
    )
    assert "contact" in _codes(findings)
    assert "person_name" in _codes(findings)


def test_money_message_matches_contract_shape():
    (finding,) = lint_public_texts(["Budżet do 180 zł/h"])
    assert finding.as_dict() == {
        "code": "money",
        "message": "Wykryto kwotę: „Budżet do 180 zł/h” — stawek nie publikujemy.",
        "excerpt": "Budżet do 180 zł/h",
    }


# ── Slugi ──────────────────────────────────────────────────────────────────


def test_slugify_transliterates_polish():
    assert career_slugs.slugify("Główny Księgowy — Łódź") == "glowny-ksiegowy-lodz"


def test_job_slug_base_falls_back_for_empty_title():
    assert career_slugs.job_slug_base("") == "rekrutacja"
    assert career_slugs.job_slug_base("Senior Java Developer") == (
        "senior-java-developer"
    )


def test_random_suffix_is_four_lowercase_alnum():
    suffix = career_slugs.random_suffix()
    assert len(suffix) == 4 and suffix.isalnum() and suffix == suffix.lower()


@pytest.mark.parametrize(
    "slug,ok",
    [
        ("marta-n", True),
        ("abc", True),
        ("ab", False),
        ("-marta", False),
        ("marta-", False),
        ("Marta", False),
        ("marta--n", False),
        ("marta_n", False),
        ("r", False),
        ("rodo", False),
        ("api", False),
        ("kariera", False),
        ("x" * 41, False),
    ],
)
def test_recruiter_slug_validation(slug: str, ok: bool):
    assert (career_slugs.recruiter_slug_problem(slug) is None) is ok


def test_suggested_slug_is_valid():
    slug = career_slugs.suggest_recruiter_slug("Marta Nowak")
    assert slug == "marta-n"
    assert career_slugs.recruiter_slug_problem(slug) is None


def test_career_url_falls_back_to_kariera_path_on_app_host(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "CAREER_PUBLIC_BASE_URL", "")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://nexus.example/")
    # Bez osobnej domeny strona żyje pod /kariera na hoście aplikacji —
    # tylko tam middleware ją przepuszcza.
    assert career_slugs.job_link_url("a-1b2c") == (
        "https://nexus.example/kariera/r/a-1b2c"
    )
    # Na hoście aplikacji strona rekrutera leży pod /kariera/p/<slug> —
    # /kariera/<slug> to 404 (błąd z testu na produkcji 22.09).
    assert career_slugs.recruiter_link_url("marta-n") == (
        "https://nexus.example/kariera/p/marta-n"
    )
    assert career_slugs.recruiter_base_url() == "https://nexus.example/kariera/p/"
    monkeypatch.setattr(
        settings, "CAREER_PUBLIC_BASE_URL", "https://kariera.dynaminds.pl"
    )
    assert career_slugs.recruiter_link_url("marta-n") == (
        "https://kariera.dynaminds.pl/marta-n"
    )
    assert career_slugs.recruiter_base_url() == "https://kariera.dynaminds.pl/"
    assert career_slugs.job_link_url("a-1b2c") == (
        "https://kariera.dynaminds.pl/r/a-1b2c"
    )


# ── Zgoda i pola opcjonalne ────────────────────────────────────────────────


def test_consent_text_names_the_controller():
    assert "B2B.NET S.A." in CONSENT_TEXT
    assert CONSENT_TEXT_VERSION == "2026-09-26"


def test_optional_fields_accept_blank_strings():
    out = parse_optional_fields(
        expected_rate_hourly="", availability_date="", city="  ", work_mode=""
    )
    assert out == {
        "expected_rate_hourly": None,
        "availability_date": None,
        "city": None,
        "work_mode": None,
    }


@pytest.mark.parametrize(
    "kwargs,field",
    [
        ({"expected_rate_hourly": "0"}, "expected_rate_hourly"),
        ({"expected_rate_hourly": "abc"}, "expected_rate_hourly"),
        ({"expected_rate_hourly": "10001"}, "expected_rate_hourly"),
        ({"availability_date": "01.10.2026"}, "availability_date"),
        ({"work_mode": "office"}, "work_mode"),
        ({"city": "x" * 121}, "city"),
    ],
)
def test_optional_fields_reject_with_field_loc(kwargs, field):
    from fastapi import HTTPException

    base = {
        "expected_rate_hourly": None,
        "availability_date": None,
        "city": None,
        "work_mode": None,
    }
    with pytest.raises(HTTPException) as exc:
        parse_optional_fields(**{**base, **kwargs})
    assert exc.value.status_code == 422
    assert exc.value.detail[0]["loc"] == ["body", field]


# ── Tytuł publiczny (0340) ─────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("title", "clients", "expected"),
    [
        (
            "Nordea: ESG Regulatory Reporting Pillar 3 (42835)",
            ["Nordea Bank Abp"],
            "ESG Regulatory Reporting Pillar 3",
        ),
        (
            "Nordea: ESG Regulatory Reporting Pillar 3 (42835)",
            ["Nordea Bank Abp", "Nordea"],
            "ESG Regulatory Reporting Pillar 3",
        ),
        ("Tester Manualny (ZOB-3003)", [], "Tester Manualny"),
        ("Test Automation Engineer RITM0857078", [], "Test Automation Engineer"),
        ("Java Developer - REQ12345", [], "Java Developer"),
        (
            "PL - CBP - Solution Architecture - SENIOR T24 ARCHITECT, Pep: 4979 (42827)",
            [],
            "PL - CBP - Solution Architecture - SENIOR T24 ARCHITECT",
        ),
        ("Senior Data Architect", ["Nordea Bank Abp"], "Senior Data Architect"),
        ("NORDEA BANK ABP – Java Dev", ["Nordea Bank Abp"], "Java Dev"),
        ("mBank | Analityk Biznesowy", ["mBank S.A.", "mBank"], "Analityk Biznesowy"),
        # Pierwsze słowo nazwy klienta krótsze niż 4 litery nie jest prefiksem.
        ("ING: Tester", ["ING Bank Śląski"], "ING: Tester"),
        ("ING: Tester", ["ING Bank Śląski", "ING"], "Tester"),
        ("Tester (m/k)", [], "Tester (m/k)"),
        ("  Java   17   Developer  ", [], "Java 17 Developer"),
    ],
)
def test_default_public_title(title, clients, expected):
    from app.services.job_public_profile import default_public_title

    assert default_public_title(title, clients) == expected


def test_default_public_title_never_empty():
    from app.services.job_public_profile import default_public_title

    assert default_public_title("(42835)", []) == "(42835)"
    assert default_public_title("Nordea:", ["Nordea Bank Abp"]) == "Nordea"
    assert default_public_title("RITM0857078", []) == "RITM0857078"
    assert default_public_title("", []) == ""
    assert default_public_title(None, []) == ""


def test_client_prefix_needs_a_separator_and_whole_words():
    from app.services.job_public_profile import default_public_title

    # Bez separatora to może być zwykłe słowo tytułu — zostaje.
    assert default_public_title("Nordea Java Developer", ["Nordea Bank Abp"]) == (
        "Nordea Java Developer"
    )
    assert default_public_title("Nordeax: Tester", ["Nordea Bank Abp"]) == (
        "Nordeax: Tester"
    )


def test_trim_subtitle_cuts_on_word_boundary_without_period():
    from app.services.job_public_profile import DRAFT_SUBTITLE_MAX, trim_subtitle

    long = (
        "rozwój platformy płatności w sektorze bankowym dla dużej organizacji "
        "z wieloma zespołami rozproszonymi po Europie i Azji."
    )
    out = trim_subtitle(long)
    assert len(out) <= DRAFT_SUBTITLE_MAX
    assert long.startswith(out)
    assert not out.endswith(" ") and not out.endswith(".")
    assert trim_subtitle("rozwój platformy płatności.") == "rozwój platformy płatności"


def test_content_hash_includes_the_title():
    from app.services.job_public_profile import content_hash

    a = content_hash("s", "a", None, "Tytuł A")
    assert a != content_hash("s", "a", None, "Tytuł B")
    assert a != content_hash("s", "a", None)


def test_job_is_open_means_published_regardless_of_handoff():
    from types import SimpleNamespace

    from app.models.job import JobStatus
    from app.services.job_public_profile import job_is_open

    assert job_is_open(SimpleNamespace(status=JobStatus.published, is_open=False))
    assert not job_is_open(SimpleNamespace(status=JobStatus.closed, is_open=True))
    assert not job_is_open(SimpleNamespace(status=JobStatus.draft, is_open=True))
    assert not job_is_open(None)


def test_draft_material_uses_given_title_and_falls_back_to_description():
    from types import SimpleNamespace

    from app.services.job_public_profile import draft_material

    job = SimpleNamespace(
        title="Nordea: Data Engineer (42835)",
        champion_profile={},
        description="Budowa hurtowni danych w chmurze.",
        requirements="3 lata z Pythonem.",
        must_skills=None,
        nice_skills=None,
        remote_policy=None,
        onsite_days_per_week=None,
        location=None,
        seniority=None,
        recruitment_type=None,
    )
    out = draft_material(job, "Data Engineer")
    assert out["title"] == "Data Engineer"
    assert out["description"] == "Budowa hurtowni danych w chmurze."
    assert out["requirements"] == "3 lata z Pythonem."
    job.champion_profile = {"project": {"about": "Hurtownia", "responsibilities": ""}}
    out = draft_material(job)
    assert out["description"] == "brak" and out["requirements"] == "brak"
    # Bez podanego tytułu: domyślny bez znajomości klienta (kody zdjęte).
    assert out["title"] == "Nordea: Data Engineer"


# ── Runda 8 (R8-N4-1): sekcje ukryte przełącznikiem też są publiczne ───────


def test_hidden_sections_are_still_linted():
    from app.services.job_public_profile import _payload_texts

    payload = {
        "title": "Java Developer",
        "subtitle": None,
        "about": None,
        "must": [{"name": "Znajomość systemów PKO BP", "note": None}],
        "nice": ["Praca w pko bp"],
        "params": {"city": "Centrala PKO BP", "start": None, "duration": None},
        "show": {"must": False, "nice": False, "params": False, "process": True},
    }
    findings = lint_public_texts(_payload_texts(payload), client_names=["PKO BP"])
    assert _codes(findings) == ["client_name"] * 3


# ── Runda 8 (decyzja Artura 27.09.2026): ukryta sekcja znika z danych ───────


def _hidden_job():
    from types import SimpleNamespace

    return SimpleNamespace(
        champion_profile={
            "basics": {"start_date": "10.2026", "contract_length": "12 mies."},
            "stack": {"must": [{"name": "Java 17"}], "nice": [{"name": "Kafka"}]},
        },
        must_skills=None,
        nice_skills=None,
        location="Warszawa",
        remote_policy=None,
        onsite_days_per_week=2,
        seniority=None,
    )


def _public(sections, **kwargs):
    from app.services.job_public_profile import public_job_payload

    return public_job_payload(
        _hidden_job(),
        title="Java Developer",
        link_slug="java-dev",
        subtitle="Rozwój platformy",
        about="Opis",
        sections=sections,
        **kwargs,
    )


_HIDDEN = {"must": False, "nice": False, "params": False, "process": True}


def test_hidden_sections_vanish_from_the_public_projection():
    payload = _public(_HIDDEN)
    assert payload["must"] == [] and payload["nice"] == []
    params = payload["params"]
    for key in ("city", "remote_policy", "onsite_days_per_week", "seniority"):
        assert params[key] is None, key
    assert params["start"] is None and params["duration"] is None
    # Stała firmy, nie dana rekrutacji — czyta ją sekcja „proces”.
    assert params["contract"] == "B2B"
    assert payload["show"] == _HIDDEN


def test_shown_sections_stay_in_the_public_projection():
    payload = _public(None)
    assert payload["must"] == [{"name": "Java 17", "note": None}]
    assert payload["nice"] == ["Kafka"]
    assert payload["params"]["city"] == "Warszawa"
    assert payload["params"]["start"] == "10.2026"


def test_hidden_sections_from_the_approval_snapshot_also_vanish():
    from app.services import job_public_profile as jpp

    full = _public(_HIDDEN, respect_show=False)
    assert full["must"] == [{"name": "Java 17", "note": None}]
    stored = jpp.sections_with_approved_content(_HIDDEN, jpp.approved_content(full))
    # Migawka niesie pełne pola (inaczej edytor widziałby fałszywą „zmianę”)…
    assert jpp.stored_approved_content(stored)["must"] == ["Java 17"]
    assert not jpp.approved_content_stale(_hidden_job(), stored)
    # …ale strona i portale dostają okrojoną projekcję.
    served = _public(stored)
    assert served["must"] == [] and served["params"]["city"] is None
    assert jpp.visible_params(_hidden_job(), stored)["city"] is None
    assert jpp.visible_params(_hidden_job(), None)["city"] == "Warszawa"


def test_portal_refuses_hidden_must_with_a_clear_reason():
    from app.services.job_portals import jjit_payload

    options = jjit_payload.normalize_options(
        {
            "category": "java",
            "experience_level": "senior",
            "working_time": "full_time",
            "workplace_type": "remote",
            "city": "Warszawa",
        }
    )
    payload = _public(_HIDDEN)
    assert jjit_payload.skill_split("rocketjobs", payload) == ([], [])
    problems = jjit_payload.validate("rocketjobs", payload, options)
    assert any("ukryta" in p for p in problems), problems
    assert "Szczegóły" not in jjit_payload.build_body(payload)
    assert jjit_payload.validate("rocketjobs", _public(None), options) == []
