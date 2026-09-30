"""Które pozycje must bramkują i w jakiej postaci (decyzja Artura 27.09.2026).

Bramka działa tylko na nazwach technologii: wersje odcięte, przykłady klienta
jako „którakolwiek”, język/branża/metodyki/miękkie/role nie ukrywają nikogo.
Przypadki wprost z maili klientów z 25.09.2026.
"""

import pytest

from app.services.must_gate_terms import gate_requirement, ignored_reason
from app.services.skill_normalize import strip_version


@pytest.mark.parametrize(
    "label, options",
    [
        ("Java 8+", ("Java",)),
        ("React.js (v18 or higher)", ("React.js",)),
        ("Windows Server 2019", ("Windows Server",)),
        (".NET 6", (".NET",)),
        ("CI/CD tools like Bitbucket, Jenkins", ("CI/CD", "Bitbucket", "Jenkins")),
        ("Bazy danych (Oracle, PostgreSQL)", ("Oracle", "PostgreSQL")),
        ("Senior Java Developer", ("Java",)),
        ("Kafka lub RabbitMQ", ("Kafka", "RabbitMQ")),
        ("Temenos T24 / Temenos Transact", ("Temenos T24", "Temenos Transact")),
        ("Spring Boot", ("Spring Boot",)),
        ("C#", ("C#",)),
        ("Node.js", ("Node.js",)),
        ("oracle/pl/sql", ("oracle", "pl/sql")),
    ],
)
def test_technology_labels_gate_with_normalized_options(label, options):
    requirement = gate_requirement(label)
    assert requirement is not None and requirement.options == options
    assert requirement.label == label


@pytest.mark.parametrize(
    "label, reason",
    [
        ("język angielski", "language"),
        ("English B2", "language"),
        ("bankowość", "domain"),
        ("KYC / AML", "domain"),
        ("GDPR", "domain"),
        ("Agile", "category"),
        ("Hybrid cloud architecture", "category"),
        ("narzędzie CASE", "category"),
        ("Good communication skills", "soft"),
        ("Developer", "role"),
        ("python i bash", "prose"),
        # Komentarz po myślniku i wstęp „znajomość …” zostają prozą: odcięte
        # dawały odmiany („Kafki”) i zdania jako fałszywe technologie.
        ("apache kafka – minimum 4 lata komercyjnego doświadczenia", "prose"),
        ("bardzo dobra znajomość Kafki", "prose"),
        ("3 lata w technologiach Java/Spring/Groovy", "prose"),
        ("qTest lub podobne narzędzie do zarządzania testami", "category"),
    ],
)
def test_non_technology_labels_do_not_gate(label, reason):
    assert gate_requirement(label) is None
    assert ignored_reason(label) == reason


@pytest.mark.parametrize(
    "name, base, version",
    [
        ("Java 8+", "Java", "8+"),
        ("Python 3.x", "Python", "3.x"),
        ("Java 7/8", "Java", "7/8"),
        ("Java 11 or higher", "Java", "11 or higher"),
        ("ES6", "ES6", None),
        ("OAuth2", "OAuth2", None),
        ("Log4j", "Log4j", None),
    ],
)
def test_strip_version(name, base, version):
    assert strip_version(name) == (base, version)


# ── Reguła ze słownikiem (audyt 30.09.2026, B2) ──────────────────────────────
from tests.taxonomy_fixture import hydrated_taxonomy  # noqa: E402
from app.services.must_gate_terms import critical_eligible  # noqa: E402


@pytest.mark.parametrize(
    "label, reason",
    [
        # Nazwy ze słownika, które są rolą albo metodyką — do 30.09 skrót
        # `in ALIAS_MAP` przepuszczał je jako technologię.
        ("QA", "role"),
        ("quality assurance", "role"),
        ("software developer", "role"),
        ("backend developer", "role"),
        ("IT analysis", "role"),
        ("release manager", "role"),
        ("Scrum", "category"),
        # Przykłady z nawiasu po ZDANIU nie są wymogiem.
        ("Doświadczenie z integracją systemów (on-premise, hybrid, cloud)", "prose"),
        (
            "Umiejętność pracy w dynamicznym środowisku IT (DevOps / Application Operations)",
            "prose",
        ),
        ("Wykształcenie wyższe kierunkowe (informatyka, matematyka)", "prose"),
    ],
)
def test_taxonomy_roles_methodologies_and_prose_heads_do_not_gate(label, reason):
    with hydrated_taxonomy():
        assert gate_requirement(label) is None
        assert ignored_reason(label) == reason


@pytest.mark.parametrize(
    "label, options",
    [
        ("Java 11+", ("Java",)),
        ("Bazy danych (Oracle, PostgreSQL)", ("Oracle", "PostgreSQL")),
        ("Znajomość baz danych (np. Oracle, PostgreSQL)", ("Oracle", "PostgreSQL")),
        # CI/CD jest w słowniku metodyką — nie opcją, ale głowa przykładów zostaje.
        ("CI/CD tools like Bitbucket, Jenkins", ("Bitbucket", "Jenkins")),
        ("Pega", ("Pega",)),
        ("UML", ("UML",)),
    ],
)
def test_taxonomy_technologies_still_gate(label, options):
    with hydrated_taxonomy():
        requirement = gate_requirement(label)
        assert requirement is not None and requirement.options == options


@pytest.mark.parametrize(
    "label, eligible",
    [
        ("Java 11+", True),
        ("Angular", True),
        ("React.js (v18 or higher)", True),
        ("Kafka lub RabbitMQ", False),  # RabbitMQ spoza słownika
        ("Docker/Kubernetes", True),
        ("Pega", True),  # narzędzie — technologia w sensie bramki
        ("BPMN", True),  # standard
        ("Temenos T24", False),  # bramkuje w punktach, słownik go nie zna
        ("QA", False),
        ("Scrum", False),
        ("team player", False),
        ("dostępność asap / maksymalnie 1 miesiąc", False),
    ],
)
def test_critical_eligibility_requires_every_option_in_taxonomy(label, eligible):
    with hydrated_taxonomy():
        assert critical_eligible(label) is eligible


def test_critical_eligibility_is_false_without_taxonomy():
    assert critical_eligible("Java") is False
