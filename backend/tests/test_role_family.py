"""Rodzina roli osoby i rekrutacji (`services/role_family.py`) — bez bazy.

Tytuły wzięte z kopii produkcji (staging 22.10.2026): tak naprawdę wyglądają
stanowiska w CV i nazwy rekrutacji z zamówień klientów.
"""

from types import SimpleNamespace

import pytest

from app.services import role_family as rf


@pytest.mark.parametrize(
    "title,family",
    [
        # Testerzy — także z technologią programisty w nazwie.
        ("Senior QA Automation Engineer", "qa"),
        ("Tester Automatyzujący / Tester Danych Senior (ZOB-2949)", "qa"),
        (
            "QA Test Engineer Senior (automation) - Consumer Finance - Poland (40627)",
            "qa",
        ),
        ("Software Developer in Test", "qa"),
        ("Software Engineer II — Test", "qa"),
        ("Specjalista ds. Testów", "qa"),
        ("Koordynator Testów – aplikacje Biura Maklerskiego (ZOB-2996)", "qa"),
        # Programiści.
        ("Full Stack Developer (Java, Angular)", "developer"),
        ("Junior Full Stack Developer", "developer"),
        ("Senior IT developer GCOP", "developer"),
        (
            "Nordea: BE developer with experience in testing and openness (42448)",
            "developer",
        ),
        ("Projektant Programista ds. Utrzymania Hurtowni Danych", "developer"),
        ("Fullstack Developer & UX/UI Designer", "developer"),
        ("Full-Stack Developer / Product Owner", None),
        ("Data Platform Developer-Analyst", "developer"),
        # Pozostałe rodziny.
        ("Analityk Systemowy SENIOR (ZOB-2852)", "analyst"),
        ("Business and Systems Analyst", "analyst"),
        ("ZOB-3092 usługa analizy systemowej", "analyst"),
        ("Nordea: Data Analyst for Individual Rights Workflow Tool (42700)", "data"),
        ("Data Engineer (GCP / BigQuery) (ZOB-3033)", "data"),
        ("Senior Data / ML Engineer / Product Owner", None),
        ("Nordea: IT Project Manager for MFA (43030)", "pm"),
        ("Scrum Master | Agile Coach", "pm"),
        ("Product Owner & Engineering Manager", "pm"),
        ("Product Owner D4A (DevOps for Applications)", None),
        ("DevOps - Market Risk (replacement) (43075)", "devops"),
        ("Admin ds. sieci teleinformatycznych", "devops"),
        ("UI Designer (6426)", "design"),
        # Nieznane — lepiej brak znaku niż zły znak.
        ("Poland - Warsaw/Gdansk/Gdynia IT Analyst", None),
        ("Programista / Analityk Systemowy", None),
        ("Architekt środowisk chmurowych", None),
        ("Application Designer", None),
        ("Team Leader", None),
        ("", None),
        (None, None),
    ],
)
def test_family_of(title, family):
    assert rf.family_of(title) == family


def test_tester_on_a_developer_job_is_another_role():
    """Zgłoszenie z 27.10.2026: Senior QA Automation przy Full Stack Developer."""
    found = rf.role_mismatch("developer", "Senior QA Automation Engineer")
    assert found is not None
    assert found.family == "qa"
    assert found.label == "tester"
    assert found.detail == "obecnie Senior QA Automation Engineer"


def test_clear_history_beats_an_old_cv():
    """CV z 2023 mówi „Junior Full Stack Developer”, a każda rekrutacja w NEXUSIE
    była testerska — liczy się historia, a opis pokazuje oba źródła."""
    titles = ["Tester automatyczny", "QA Automation Engineer", "Tester Automatyzujący"]
    found = rf.role_mismatch("developer", "Junior Full Stack Developer", titles)
    assert found is not None
    assert found.family == "qa"
    assert (
        found.detail
        == "u nas 3 z 3 rekrutacji: tester · w CV „Junior Full Stack Developer”"
    )


def test_unclear_history_falls_back_to_the_cv():
    # Za mało rekrutacji, żeby historia przesądzała.
    assert (
        rf.role_mismatch("developer", "Java Developer", ["Tester", "QA Engineer"])
        is None
    )
    # Historia rozdzielona po równo — też nie przesądza.
    mixed = ["Tester", "QA Engineer", "Java Developer", "Backend Developer"]
    assert rf.history_family(mixed) == (None, 2, 4)
    assert rf.role_mismatch("developer", "Java Developer", mixed) is None


@pytest.mark.parametrize(
    "job_family,position",
    [
        ("developer", "Java Developer"),  # ta sama rola
        ("developer", "Senior DevOps Engineer"),  # pokrewna
        ("developer", "Data Engineer"),  # pokrewna
        ("analyst", "Product Owner"),  # pokrewna
        ("developer", "Team Leader"),  # rola osoby nieznana
        (None, "Senior QA Automation Engineer"),  # rola rekrutacji nieznana
        ("developer", None),
    ],
)
def test_no_mark_for_the_same_related_or_unknown_role(job_family, position):
    assert rf.role_mismatch(job_family, position) is None


def test_long_position_is_shortened_in_the_detail():
    found = rf.role_mismatch("developer", "Senior QA Automation Engineer " + "x" * 80)
    assert found is not None
    assert len(found.detail) <= len("obecnie ") + rf._POSITION_MAX
    assert found.detail.endswith("…")


def test_keeps_despite_role_needs_most_must_haves():
    def reqs(met: int, total: int, nice: int = 3) -> list[dict]:
        must = [
            {"level": "must", "status": "met" if i < met else "unknown"}
            for i in range(total)
        ]
        return must + [{"level": "nice", "status": "met"}] * nice

    assert rf.keeps_despite_role(reqs(8, 10)) is True
    assert rf.keeps_despite_role(reqs(5, 10)) is False
    # Same „nice” bez „musi mieć” niczego nie ratują.
    assert rf.keeps_despite_role(reqs(0, 0)) is False
    assert rf.keeps_despite_role([]) is False


def test_current_position_prefers_the_cv_reading_then_the_row_title():
    from_cv = SimpleNamespace(
        cv_extracted_data={"current_position": " Senior QA Automation Engineer "},
        linkedin_current_title="Java Developer",
        linkedin_current_company=None,
        experience=[],
    )
    assert rf.current_position(from_cv) == "Senior QA Automation Engineer"
    from_row = SimpleNamespace(
        cv_extracted_data={"current_position": ""},
        linkedin_current_title=None,
        linkedin_current_company=None,
        experience=[{"role": "QA Engineer", "company": "Bank"}],
    )
    assert rf.current_position(from_row) == "QA Engineer"
