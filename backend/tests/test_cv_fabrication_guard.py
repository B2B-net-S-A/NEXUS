"""Bezpiecznik anty-konfabulacyjny na wolnym tekście CV.

Do tej pory `_fabrication_warnings` sprawdzał WYŁĄCZNIE technologie i certyfikaty,
czyli słownik zamknięty. Rozdmuchiwanie żyje gdzie indziej — w opisach obowiązków
i w why_points, gdzie model dopisuje skalę i liczby, których źródło nie podaje
(#627: zwykły frontend-dev w React dostał „integrację z wieloma usługami
backendowymi dla różnych klientów i domen").

Najważniejszy test w tym pliku to `test_ordinary_rephrasing_is_not_flagged`.
Bezpiecznik, który krzyczy przy zwykłym przeredagowaniu, zostanie odklikany —
i wtedy nie chroni niczego. Dlatego sprawdzamy TWIERDZENIA (liczby, deklarowaną
skalę), a nie słowa.
"""

from datetime import datetime
from typing import Any

import pytest

from app.services.cv_generator_b2b.standalone_service import _fabrication_warnings

_HIGH = "BRAK POKRYCIA"
_MED = "WERYFIKUJ"


def _data(
    *,
    why: list[str] | None = None,
    duties: list[str] | None = None,
    dates: str = "01.2019 – 12.2023",
    technologies: list[str] | None = None,
    skills: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "name": "Jan Kowalski",
        "why_points": why or [],
        "certifications": [],
        "skills": skills or [],
        "experience": [
            {
                "dates": dates,
                "company": "Acme",
                "position": "Backend Developer",
                "responsibilities": duties or [],
                "technologies": technologies or [],
            }
        ],
    }


def _run(data: dict[str, Any], source: str, language: str = "pl") -> list[str]:
    return _fabrication_warnings(data, source, language)


def _high(issues: list[str]) -> list[str]:
    return [i for i in issues if i.startswith(_HIGH)]


def _med(issues: list[str]) -> list[str]:
    return [i for i in issues if i.startswith(_MED)]


# ── Anty-fałszywe-alarmy: to decyduje, czy bezpiecznik przeżyje w praktyce ──


def test_ordinary_rephrasing_is_not_flagged() -> None:
    """Redakcja wolno przeredagować — i to NIE może zapalać ostrzeżeń.

    Te same fakty, inne słowa, zero nowych twierdzeń. Gdyby to trafiało na
    listę uwag, rekruter nauczyłby się ją ignorować w tydzień.
    """
    source = (
        "Utrzymywałem API w Pythonie. Pisałem testy. Robiłem code review "
        "i wdrażałem na produkcję."
    )
    data = _data(
        duties=[
            "Rozwój i utrzymanie usług backendowych w języku Python",
            "Zapewnienie jakości poprzez testy automatyczne",
            "Przeglądy kodu oraz wdrożenia produkcyjne",
        ]
    )
    assert _run(data, source) == []


def test_version_numbers_are_not_scale_claims() -> None:
    """„Python 3.11" to wersja, nie deklaracja skali — nie ruszamy."""
    data = _data(duties=["Migracja na Python 3.11 i PostgreSQL 16"])
    assert _run(data, "Praca z Pythonem i PostgreSQL") == []


def test_years_derived_from_dates_are_not_flagged() -> None:
    """Staż liczy sam pipeline z dat, więc nie musi być w źródle dosłownie.

    `_fix_experience_years` przepisuje nagłówek why_points na podstawie
    zakresów dat. Bez tej tolerancji bezpiecznik flagowałby własną arytmetykę.
    """
    start_year = datetime.now().year - 6
    data = _data(
        why=["6 lat jako Backend Developer"],
        dates=f"01.{start_year} – obecnie",
    )
    assert _high(_run(data, "Backend Developer w Acme")) == []


# ── Liczby ────────────────────────────────────────────────────────────────


def test_invented_team_size_is_flagged_high() -> None:
    data = _data(duties=["Kierowanie zespołem 12 osób"])
    issues = _run(data, "Pracowałem w zespole nad projektem")
    assert len(_high(issues)) == 1
    assert "12 osob" in _high(issues)[0]


def test_team_size_present_in_source_is_clean() -> None:
    data = _data(duties=["Kierowanie zespołem 12 osób"])
    assert _run(data, "Prowadziłem zespół 12 osób w Acme") == []


def test_invented_sla_percentage_is_flagged() -> None:
    data = _data(why=["Utrzymanie SLA 99,9% dla systemów produkcyjnych"])
    assert len(_high(_run(data, "Utrzymanie systemów produkcyjnych"))) == 1


def test_percentage_present_in_source_is_clean() -> None:
    data = _data(why=["Utrzymanie SLA 99,9%"])
    assert _high(_run(data, "SLA na poziomie 99,9 % w umowie")) == []


def test_years_not_derivable_and_absent_from_source_are_flagged() -> None:
    """15 lat u kandydata z 5-letnim zakresem dat i bez takiej liczby w CV."""
    data = _data(why=["15 lat doświadczenia w branży"], dates="01.2019 – 12.2023")
    assert len(_high(_run(data, "Backend Developer w Acme"))) == 1


# ── Rozdmuchanie skali (klasa błędu z #627) ───────────────────────────────


def test_invented_plurality_is_flagged_medium() -> None:
    """Dokładny przypadek z #627."""
    data = _data(
        duties=[
            "Integracja frontendu z wieloma usługami backendowymi "
            "i API dla różnych klientów i domen"
        ]
    )
    issues = _run(data, "Tworzenie interfejsu w React i integracja z API")
    assert len(_med(issues)) == 1


def test_plurality_present_in_source_is_clean() -> None:
    data = _data(duties=["Integracja z wieloma usługami backendowymi"])
    assert _run(data, "Integrowałem aplikację z wieloma serwisami") == []


def test_one_scale_flag_per_sentence() -> None:
    """Kilka markerów w jednym zdaniu to nadal jedno zdanie do sprawdzenia."""
    data = _data(duties=["Wdrożenia dla wielu klientów w różnych domenach"])
    assert len(_med(_run(data, "Wdrożenie u klienta"))) == 1


# ── Umiejętności ──────────────────────────────────────────────────────────


def test_skill_absent_from_source_is_flagged() -> None:
    data = _data(skills=[{"label": "Backend", "content": "Python, Kubernetes"}])
    issues = _run(data, "Programowałem w Pythonie")
    assert any("Kubernetes" in i for i in issues)


def test_skills_present_in_source_are_clean() -> None:
    data = _data(skills=[{"label": "Backend", "content": "Python, PostgreSQL"}])
    assert _run(data, "Python i PostgreSQL na co dzień") == []


# ── Kolejność i przycinanie ───────────────────────────────────────────────


def test_certain_findings_survive_truncation() -> None:
    """Pewne trafienia nie mogą wypaść na rzecz miękkich podpowiedzi.

    Lista jest ucinana do 8 pozycji; gdyby sortowanie nie stawiało „BRAK
    POKRYCIA" na przodzie, wymyślona liczba mogłaby zniknąć pod dziesiątkami
    „WERYFIKUJ".
    """
    data = _data(
        duties=[f"Zadanie z wieloma elementami numer {i}" for i in range(12)]
        + ["Zarządzanie zespołem 47 osób"],
    )
    issues = _run(data, "Praca nad zadaniami")
    assert issues[0].startswith(_HIGH)
    assert "47 osob" in issues[0]


@pytest.mark.parametrize("language", ["pl", "en"])
def test_guard_speaks_the_document_language(language: str) -> None:
    data = _data(duties=["Kierowanie zespołem 12 osób"])
    issues = _run(data, "Praca w zespole", language)
    expected = "NOT IN SOURCE" if language == "en" else "BRAK POKRYCIA"
    assert issues and issues[0].startswith(expected)


# ── Regresja: stare kontrole nadal działają ───────────────────────────────


def test_existing_technology_check_still_works() -> None:
    data = _data(technologies=["Kubernetes"])
    assert any("Kubernetes" in i for i in _run(data, "Programowałem w Pythonie"))


def test_clean_cv_produces_no_warnings() -> None:
    data = _data(
        why=["Backend Developer z doświadczeniem w Pythonie"],
        duties=["Utrzymanie API w Pythonie"],
        technologies=["Python"],
        skills=[{"label": "Backend", "content": "Python"}],
    )
    source = "Backend Developer. Utrzymanie API w Pythonie. Technologie: Python."
    assert _run(data, source) == []
