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
