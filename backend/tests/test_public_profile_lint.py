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
    monkeypatch.setattr(
        settings, "CAREER_PUBLIC_BASE_URL", "https://kariera.dynaminds.pl"
    )
    assert career_slugs.recruiter_link_url("marta-n") == (
        "https://kariera.dynaminds.pl/marta-n"
    )


# ── Zgoda i pola opcjonalne ────────────────────────────────────────────────


def test_consent_text_names_the_controller():
    assert "B2B.NET S.A." in CONSENT_TEXT
    assert CONSENT_TEXT_VERSION == "2026-09-21"


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
