"""Lata „jako X” liczone z ról tego samego zawodu (decyzja Artura 20.11.2026).

Prompt 14 każe pisać „w tym M lat jako X”, gdzie M to suma dat wszystkich ról
zawodu, a `_fix_scoped_years` zbijał M do ról o dokładnie tej nazwie: „w tym
16 lat jako analityk biznesowo-systemowy” stawało się „ponad 1 rok”.
Reguła: docs/claude/generator-cv/lata-jako-x-rodzina-zawodu.md.
Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from app.services import cv_qc as qc
from app.services import dz_review as dz
from app.services.cv_generator_b2b.legacy_v7 import _helpers
from app.services.cv_generator_b2b.legacy_v7.role_family import same_profession


@pytest.fixture(autouse=True)
def _today(monkeypatch):
    monkeypatch.setattr(_helpers, "local_now", lambda: datetime(2026, 11, 18, 12, 0))


def _data(point: str, *roles: tuple) -> dict:
    return {
        "why_points": [point, "b", "c", "d", "e"],
        "experience": [
            {
                "position": role[0],
                "dates": role[1],
                "company": "Firma Testowa",
                "technologies": list(role[2]) if len(role) > 2 else [],
            }
            for role in roles
        ],
    }


def _fix(data: dict, language: str = "pl") -> list[str]:
    notes: list[str] = []
    _helpers._fix_experience_years(data, language, notes)
    _helpers._fix_scoped_years(data, language, notes)
    return notes


ANALYST = (
    ("Senior Business Analyst", "01.2018 - obecnie"),
    ("Analityk Biznesowo-Systemowy", "03.2016 - 12.2017"),
    ("Analityk systemowy", "08.2014 - 02.2016"),
    ("Analityk systemowy", "01.2014 - 07.2014"),
    ("Analityk systemowo-biznesowy", "02.2013 - 12.2013"),
    ("Analityk biznesowy", "10.2011 - 09.2012"),
    ("Analityk IT", "05.2010 - 09.2011"),
    ("Specjalista ds. wdrożeń", "08.1998 - 02.2003"),
    ("Informatyk", "07.1997 - 08.1998"),
)


@pytest.mark.parametrize("model_figure", ["16 lat", "12 lat", "1 rok"])
def test_role_subfigure_counts_every_role_of_the_profession(model_figure):
    # 05.2010 – 09.2012 (29 mies.) i 02.2013 – 11.2026 (166 mies.) = 16 lat 3 mies.
    data = _data(
        f"21 lat doświadczenia w IT, w tym {model_figure} jako analityk "
        "biznesowo-systemowy",
        *ANALYST,
    )
    _fix(data)
    assert data["why_points"][0] == (
        "21 lat doświadczenia w IT, w tym ponad 16 lat jako analityk "
        "biznesowo-systemowy"
    )


def test_note_lists_the_roles_added_to_the_figure():
    data = _data(
        "21 lat doświadczenia w IT, w tym 1 rok jako analityk biznesowo-systemowy",
        *ANALYST,
    )
    notes = _fix(data)
    assert len(notes) == 1
    assert notes[0].startswith("WERYFIKUJ: lata „jako analityk biznesowo-systemowy”")
    assert "Senior Business Analyst (01.2018 - obecnie)" in notes[0]
    assert "Specjalista ds. wdrożeń" not in notes[0]
    assert "i 2 innych" in notes[0]  # sześć ról, cztery z nazwy


def test_prompt_example_counts_devops_consultant_and_cloud_operations():
    """Przykład z promptu 14: DevOps Engineer, DevOps Consultant i Cloud Operations."""
    data = _data(
        "9 lat doświadczenia w IT, w tym 8 lat jako DevOps Engineer",
        ("DevOps Engineer", "03.2021 - obecnie"),
        ("DevOps Consultant", "01.2019 - 02.2021"),
        ("Cloud Operations Engineer", "01.2018 - 12.2018"),
        ("IT Support Specialist", "01.2017 - 12.2017"),
    )
    _fix(data)
    # 01.2018 – 11.2026 = 107 mies.; support IT nie wchodzi do zawodu.
    assert data["why_points"][0] == (
        "9 lat doświadczenia w IT, w tym ponad 8 lat jako DevOps Engineer"
    )


def test_english_lead_figure_counts_the_profession():
    data = _data(
        "Over 3 years of experience as a QA Automation Engineer",
        ("QA Automation Engineer", "09.2023 - currently"),
        ("Quality Assurance Engineer", "09.2021 - 08.2023"),
        ("Software Tester", "10.2019 - 08.2021"),
    )
    notes = _fix(data, "en")
    # 10.2019 – 11.2026 = 86 mies. = 7 lat 2 mies. (bez „Over”: mniej niż kwartał).
    assert data["why_points"][0] == "7 years of experience as a QA Automation Engineer"
    assert "Software Tester (10.2019 - 08.2021)" in notes[0]


def test_technology_named_in_x_must_be_in_the_role():
    data = _data(
        "15 lat doświadczenia w IT, w tym 3 lata jako Java Developer",
        ("Java Developer", "01.2019 - 12.2024", ["Java", "Spring"]),
        ("Software Developer", "01.2017 - 12.2018", ["Java", "Hibernate"]),
        ("PHP Developer", "01.2010 - 12.2016", ["PHP", "Symfony"]),
    )
    _fix(data)
    # Java: 01.2017 – 12.2024 = 96 mies.; lata PHP to nie „jako Java Developer”.
    assert data["why_points"][0] == (
        "15 lat doświadczenia w IT, w tym 8 lat jako Java Developer"
    )


def test_seniority_named_in_x_must_be_in_the_role():
    data = _data(
        "13 lat doświadczenia w IT, w tym 2 lata jako Senior Python Developer",
        ("Senior Python Developer", "01.2023 - 12.2025"),
        ("Python Developer", "01.2016 - 12.2022"),
    )
    _fix(data)
    assert data["why_points"][0] == (
        "13 lat doświadczenia w IT, w tym 3 lata jako Senior Python Developer"
    )


def test_domain_analyst_is_another_profession():
    data = _data(
        "10 lat doświadczenia w IT, w tym 4 lata jako Business Analyst",
        ("Business Analyst", "01.2021 - 12.2024"),
        ("Cash Management Analyst", "01.2015 - 12.2020"),
    )
    notes = _fix(data)
    assert data["why_points"][0] == (
        "10 lat doświadczenia w IT, w tym 4 lata jako Business Analyst"
    )
    assert notes == []


def test_company_bound_role_years_stay_with_that_role():
    point = (
        "16 lat doświadczenia w IT, w tym 5 lat jako Senior PHP Developer "
        "w Test Company Alfa"
    )
    data = _data(
        point,
        ("Senior PHP Developer", "01.2014 - 12.2018"),
        ("PHP Developer", "01.2010 - 12.2013"),
        ("Senior PHP / Mobile Developer", "01.2019 - obecnie"),
    )
    _fix(data)
    assert data["why_points"][0] == point


def test_point_listing_two_roles_keeps_each_role_separate():
    point = (
        "7 years of experience as a System Analyst and 2 years as a Business Analyst"
    )
    data = _data(
        point,
        ("System Analyst", "05.2019 - 04.2026"),
        ("Business Analyst", "04.2017 - 04.2019"),
    )
    _fix(data, "en")
    assert data["why_points"][0] == point


def test_family_figure_never_goes_above_the_area_figure():
    data = _data(
        "Ponad 5 lat doświadczenia w IT, w tym 1 rok jako tester oprogramowania",
        ("Tester, Analityk", "11.2018 - 04.2023"),
        ("Tester", "10.2017 - 10.2018"),
        ("Tester oprogramowania", "08.2014 - 02.2015"),
    )
    _fix(data)
    # Rodzina: 74 mies., ale liczba obszaru to „ponad 5 lat”.
    assert data["why_points"][0] == (
        "Ponad 5 lat doświadczenia w IT, w tym ponad 5 lat jako tester oprogramowania"
    )


def test_without_a_role_of_that_name_the_model_figure_only_goes_up():
    roles = (
        ("IT System Analyst", "2022 - obecnie"),
        ("Business Analyst / Data Analyst", "2021 - 2022"),
        ("Business Analyst / Product Owner", "2018 - 2021"),
        ("Data Analyst", "2016 - 2017"),
    )
    # Bez roli „analityk biznesowo-systemowy”: rodzina daje 113 mies.
    low = _data(
        "Ponad 10 lat doświadczenia w IT, w tym ponad 7 lat jako analityk "
        "biznesowo-systemowy",
        *roles,
    )
    _fix(low)
    assert "w tym ponad 9 lat jako analityk" in low["why_points"][0]
    high = _data(
        "Ponad 12 lat doświadczenia w IT, w tym 11 lat jako analityk "
        "biznesowo-systemowy",
        *roles,
    )
    _fix(high)
    assert "w tym 11 lat jako analityk" in high["why_points"][0]


def test_another_profession_never_lends_its_years():
    point = "10 lat doświadczenia w IT, w tym 3 lata jako Data Engineer"
    data = _data(
        point,
        ("Data Engineer", "01.2022 - 12.2024"),
        ("Kierownik sklepu", "01.2012 - 12.2021"),
        ("Python Developer", "01.2020 - 12.2021"),
    )
    _fix(data)
    assert data["why_points"][0] == point


# Pomiar przed/po na kopii stagingu (20.11.2026) znalazł miejsca, w których rodzina
# zawodu obniżała albo osłabiała liczbę. Zawód ma ją wyłącznie podnosić.


def test_family_never_softens_the_model_wording():
    # Bez roli o tej nazwie: 62 mies. to „5 lat”, a model napisał „Ponad 5 lat”.
    point = "Ponad 5 lat doświadczenia jako programista backendu"
    data = _data(
        point,
        ("Python Developer", "01.2021 - 02.2026"),
        ("Kelner", "01.2015 - 12.2020"),
    )
    notes = _fix(data)
    assert data["why_points"][0] == point
    assert notes == []


def test_model_fraction_stays_when_the_family_does_not_change_the_wording():
    # Role o tej nazwie: 52 mies. (zgodne z „4,5 roku”); rodzina 59 mies. = też
    # „ponad 4 lata”, więc zostaje to, co dziś: ułamek modelu.
    point = "4,5 roku doświadczenia jako QA Automation Engineer"
    data = _data(
        point,
        ("QA Automation Engineer", "08.2022 - 11.2026"),
        ("Software Tester", "01.2022 - 07.2022"),
    )
    notes = _fix(data)
    assert data["why_points"][0] == point
    assert notes == []


def test_roles_without_dates_do_not_cut_the_model_figure():
    # Dotąd bez roli o tej nazwie liczba zostawała; suma dat (role bez dat) jej nie tnie.
    point = "Over 20 years of experience as a software developer across industries"
    data = _data(
        point,
        ("Senior Java Developer", "01.2020 - 12.2025"),
        ("Programmer", ""),
        ("Developer", ""),
    )
    _fix(data, "en")
    assert data["why_points"][0] == point


def test_short_role_of_that_name_does_not_pull_the_model_figure_down():
    # Rola o tej nazwie ma 3 mies. (poniżej progu), więc liczba modelu zostawała.
    point = "24+ years as a Cybersecurity Expert, including leadership roles"
    data = _data(
        point,
        ("SOC L3 - Cybersecurity Expert", "03.2025 - 05.2025"),
        ("Cybersecurity Lead", "11.2016 - 02.2025"),
    )
    _fix(data, "en")
    assert data["why_points"][0] == point


@pytest.mark.parametrize(
    "phrase, position, technologies, expected",
    [
        ("analityk biznesowo-systemowy", "Senior Business Analyst", (), True),
        ("analityk biznesowo-systemowy", "Analityk IT", (), True),
        ("Business Analyst", "Cash Management Analyst", (), False),
        ("tester oprogramowania", "QA Engineer", (), True),
        ("DevOps Engineer", "Cloud Operations Engineer", (), True),
        ("DevOps Engineer", "IT Support Specialist", (), False),
        ("IT Project Manager", "Kierownik projektu", (), True),
        ("IT Project Manager", "Specjalista ds. Projektowania Systemów", (), False),
        ("Java Developer", "Software Engineer", ("Java 17",), True),
        ("Java Developer", "Software Engineer", ("Go",), False),
        ("Senior Tester", "Tester", (), False),
        ("Data Engineer", "Kierownik sklepu", (), False),
    ],
)
def test_same_profession(phrase, position, technologies, expected):
    assert same_profession(phrase, position, technologies) is expected


# ── Panel „Do poprawy”: ta sama rodzina w uwadze „Lata w punkcie 1” ────────


def _role_html(title: str, dates: str) -> str:
    return (
        f'<p data-cv-section="role"><b>{title}</b> {dates}</p>'
        '<p data-cv-section="employer">Firma Testowa</p>'
        "<ul><li><p>Analiza wymagań.</p></li></ul>"
    )


def _qc_years(point: str, *roles: str) -> dict:
    html = (
        "<h1>Analityk – Kandydat Testowy</h1>"
        '<h2 data-cv-section="why_points">Dlaczego nasz kandydat</h2>'
        f"<ul><li><p>{point}</p></li><li><p>Drugi punkt.</p></li></ul>"
        '<h2 data-cv-section="experience">Doświadczenie</h2>' + "".join(roles)
    )
    data = qc.QcInput(
        must=[],
        nice=[],
        blocks=dz.html_blocks(html),
        has_cv=True,
        bold_known=True,
        original_text="",
        experience=[],
        job_title="Analityk",
        today=date(2026, 11, 18),
    )
    return {c["key"]: c for c in qc.compute_checks(data)}["years_breakdown"]


def test_editor_check_counts_the_same_profession_as_the_generator():
    check = _qc_years(
        "8 lat doświadczenia jako analityk biznesowo-systemowy w bankowości.",
        _role_html("Analityk Biznesowo-Systemowy", "06.2018 – obecnie"),
        _role_html("Analityk Biznesowy", "12.2015 – 06.2018"),
        _role_html("Kierownik sklepu", "01.2010 – 11.2015"),
    )
    item = check["items"][0]
    view = item["tenure"]
    # 12.2015 – 11.2026 = 132 mies.; sklep nie wchodzi do zawodu.
    assert view["matched_months"] == 132
    assert [r["matched"] for r in view["roles"]] == [True, True, False]
    assert item["proposal"] == (
        "Ponad 16 lat w IT, w tym 11 lat jako analityk biznesowo-systemowy"
    )
