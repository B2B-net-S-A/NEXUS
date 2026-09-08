"""Bramka must-have nie może ukrywać na PUNKTACH WYMAGAŃ przepisanych z ogłoszenia.

Regresja produkcyjna wykryta 08.09.2026, kilka godzin po wdrożeniu trzech
rubryk. `must_skills` miało być listą technologii, ale w produkcji **70%
opublikowanych ofert** ma tam punkty wymagań przepisane z ogłoszenia:
„apache kafka – minimum 4 lata komercyjnego doświadczenia", „gotowość do pracy
hybrydowej w warszawie – 50% onsite", „skuteczność w działaniu i
odpowiedzialność biznesowa".

Bramka porównuje wpis z umiejętnościami kandydata jako CAŁY STRING, więc żaden
kandydat nigdy takiego wpisu nie ma — a reguła „nieznane przechodzi" ratuje
wyłącznie kandydatów BEZ ŻADNYCH umiejętności. Skutek: ukrywani byli dokładnie
ci, o których chodzi. Zmierzone na produkcji: **10 z 10 sprawdzonych ofert
zwracało ZERO kandydatów**, przy 61–100 ukrytych z powodu `missing_must`.
"""

from __future__ import annotations

import itertools
from types import SimpleNamespace

from app.services.dealbreaker_filters import (
    apply_dealbreakers,
    gate_eligible_must_skills,
    is_gate_eligible_must,
)


# Ciągi WPROST z produkcji (oferta 404747 „Kafka Engineer", Credit Agricole).
PROZA_Z_PRODUKCJI = [
    "apache kafka – minimum 4 lata komercyjnego doświadczenia",
    "confluent platform enterprise i confluent cloud",
    "migracja/replikacja klastrów kafka – mirrormaker 2, cluster linking lub confluent replicator",
    "aws – vpc, iam, ec2, eks, msk, s3, kms, secrets manager",
    "python i bash",
    "gotowość do pracy hybrydowej w warszawie – 50% onsite",
    "skuteczność w działaniu i odpowiedzialność biznesowa",
    "język angielski na poziomie minimum średniozaawansowanym (b1/b2)",
    "Minimum 3 lata doświadczenia na stanowisku Testera IT",
    "doświadczenie w architekturze it – aplikacyjnej, korporacyjnej lub systemowej",
    # Alternatywy z ukośnikiem — zmierzone na 24 ofertach produkcyjnych. Nikt
    # nie ma ich dosłownie jako umiejętności, więc bramkowanie nimi opróżnia
    # listę tak samo jak proza.
    "Docker/Kubernetes",
    "Pytest/Jest/Cypress",
    "Flask/FastAPI",
    "Jenkins/Gitlab/Github Actions",
    "KYC / AML",
    "Portfolio/backlog management",
    # Frazy CZYNNOŚCIOWE — zmierzone po pierwszej naprawie: wciąż bramkowały
    # na 20 ofertach. Krótkie i bez separatorów, więc przechodziły; opisują
    # czynność albo wymóg formalny, nie technologię.
    "pisanie zapytań sql",
    "tworzenie dokumentacji technicznej",
    "rozwój aplikacji backendowych",
    "budowa aplikacji webowych",
    "zarządzanie ryzykiem",
    "zarządzanie harmonogramem",
    "uzgadnianie wymagań",
    "wykształcenie wyższe",
    "wsparcie UAT",
    "zasady SOLID",
]

# Nazwy technologii, które MUSZĄ dalej bramkować — inaczej naprawa wyłącza
# rubrykę, zamiast ją naprawiać.
TECHNOLOGIE = [
    "Java",
    "Python",
    "Apache Kafka",
    "SQL Server",
    "Node.js",
    "C#",
    "C++",
    "React",
    "Spring Boot",
    "Amazon Web Services",
    "Microsoft SQL Server",
    "Kubernetes",
    "PostgreSQL",
    "Terraform",
]


_next_id = itertools.count(1)


def _kandydat(skills):
    # Rozróżnialne id: asercja `[c.id for c in kept] == [ma.id]` przy dwóch
    # kandydatach o tym samym id przechodziłaby także wtedy, gdyby bramka
    # zostawiła TEGO NIEWŁAŚCIWEGO — byle zostawiła dokładnie jednego.
    return SimpleNamespace(
        id=next(_next_id),
        skills=[{"name": s} for s in skills],
        verified_tech=None,
        cv_extracted_data=None,
        tags=None,
        expected_rate_hourly=None,
        max_onsite_days_per_week=None,
        location=None,
        city=None,
        preferences=None,
    )


def test_prose_from_production_never_reaches_the_gate():
    """Ani jeden punkt wymagań z produkcji nie może bramkować."""
    przepuszczone = [p for p in PROZA_Z_PRODUKCJI if is_gate_eligible_must(p)]
    assert przepuszczone == [], (
        "punkt wymagań trafił na twardą bramkę — ukryje każdego kandydata, "
        f"który ma jakiekolwiek umiejętności: {przepuszczone}"
    )


def test_real_technology_names_still_gate():
    """Naprawa nie może wyłączyć rubryki — nazwy technologii bramkują dalej."""
    zgubione = [t for t in TECHNOLOGIE if not is_gate_eligible_must(t)]
    assert zgubione == [], (
        f"nazwa technologii przestała bramkować — rubryka przestaje działać: {zgubione}"
    )


def test_single_word_verbal_noun_still_gates():
    """Wymóg ≥2 słów jest celowy: jednowyrazowe „Programowanie" bywa realną
    deklaracją kandydata, więc go nie wycinamy. Wycinamy dopiero FRAZĘ, której
    głowa jest rzeczownikiem odczasownikowym („programowanie w java")."""
    assert is_gate_eligible_must("Programowanie") is True
    assert is_gate_eligible_must("Testowanie") is True
    assert is_gate_eligible_must("tworzenie dokumentacji") is False


def test_mixed_list_keeps_only_the_technologies():
    mieszane = ["Apache Kafka", "python i bash", "Terraform", *PROZA_Z_PRODUKCJI[:3]]
    assert gate_eligible_must_skills(mieszane) == ["Apache Kafka", "Terraform"]


def test_job_whose_musts_are_all_prose_hides_nobody():
    """Odtworzenie awarii: oferta 404747 ukrywała 100/100 kandydatów z puli."""
    from app.services.dealbreaker_filters import DealbreakerInputs

    kandydaci = [_kandydat(["Apache Kafka", "AWS"]), _kandydat(["Java", "Spring"])]
    inputs = DealbreakerInputs(must_skills=tuple(gate_eligible_must_skills(PROZA_Z_PRODUKCJI)))
    wynik = apply_dealbreakers(kandydaci, inputs=inputs)
    assert len(wynik.kept) == 2, "proza nadal opróżnia listę"
    assert wynik.hidden_meta()["missing_must"] == 0


def test_a_genuine_missing_technology_is_still_hidden():
    """Druga strona: prawdziwy brak must-have nadal ukrywa — inaczej to nie
    naprawa, tylko wyłączenie bramki."""
    from app.services.dealbreaker_filters import DealbreakerInputs

    ma = _kandydat(["Apache Kafka", "Terraform"])
    nie_ma = _kandydat(["Java", "Spring Boot"])
    inputs = DealbreakerInputs(must_skills=("Apache Kafka",))
    wynik = apply_dealbreakers([ma, nie_ma], inputs=inputs)
    assert [c.id for c in wynik.kept] == [ma.id]
    assert wynik.hidden_meta()["missing_must"] == 1


def test_inputs_expose_what_the_gate_ignored():
    """Bramka, która po cichu nie działa, jest tym samym błędem co ciche
    ukrywanie — odpowiedź musi nieść, czego nie użyto."""
    from app.services.dealbreaker_filters import dealbreaker_inputs_for_job

    job = SimpleNamespace(
        id=1,
        must_skills=[{"name": "Apache Kafka"}, {"name": "python i bash"}],
        rate_budget_hourly=None,
        onsite_days_per_week=None,
        location=None,
        remote_policy=None,
        champion_profile=None,
        nice_skills=None,
    )
    inputs = dealbreaker_inputs_for_job(job)
    assert "apache kafka" in [m.lower() for m in inputs.must_skills]
    assert any("python" in m.lower() for m in inputs.must_skills_ignored)
