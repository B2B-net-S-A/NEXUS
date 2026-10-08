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
        ("Java (minimalna 11)", ("Java",)),
        ("Oracle (min. 19c)", ("Oracle",)),
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
        # Produkcja 30.09.2026: słowna wersja w nawiasie wyłączała całą
        # pozycję z bramki i z wyboru krytycznych („Java (minimalna 11)”).
        ("Java (minimalna 11)", "Java", "minimalna 11"),
        ("Java (min. 11)", "Java", "min. 11"),
        ("Oracle (min. 19c)", "Oracle", "min. 19c"),
        ("Java (minimum 17)", "Java", "minimum 17"),
        ("Java (od 11)", "Java", "od 11"),
        ("Java (wersja 17+)", "Java", "wersja 17+"),
        ("Java min. 11", "Java", "min. 11"),
        ("Angular (version 16 or higher)", "Angular", "version 16 or higher"),
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


# ── Wybór Delivery Leada (08.10.2026): także nazwy spoza słownika ───────────
@pytest.mark.parametrize(
    "label, selectable",
    [
        ("Java 11+", True),
        ("Temenos T24", True),  # narzędzie, którego słownik nie zna
        ("Kafka lub RabbitMQ", True),  # RabbitMQ spoza słownika
        ("Temenos T24 / Temenos Transact", True),
        ("QA", False),  # rola ze słownika
        ("Scrum", False),
        ("bankowość", False),
        ("English B2", False),
        ("Good communication skills", False),
        ("bardzo dobra znajomość Kafki", False),
    ],
)
def test_dl_may_pick_any_technology_name_as_critical(label, selectable):
    from app.services.must_gate_terms import critical_selectable

    with hydrated_taxonomy():
        assert critical_selectable(label) is selectable


def test_selectable_does_not_need_the_dictionary():
    from app.services.must_gate_terms import critical_selectable

    # Bez wczytanego słownika podpowiedź milczy, ale wybór człowieka działa.
    assert critical_selectable("Temenos T24") is True
    assert critical_eligible("Temenos T24") is False


@pytest.mark.parametrize(
    "label, fragment",
    [
        ("bankowość", "To branża"),
        ("English B2", "To język"),
        ("Good communication skills", "umiejętność miękka"),
        ("Hybrid cloud architecture", "To kategoria"),
        ("Developer", "To rola"),
        ("bardzo dobra znajomość Kafki", "To opis"),
    ],
)
def test_blocked_position_gets_a_polish_reason(label, fragment):
    from app.services.must_gate_terms import not_selectable_sentence

    sentence = not_selectable_sentence(label)
    assert sentence is not None and fragment in sentence


def test_selectable_position_has_no_blocking_reason():
    from app.services.must_gate_terms import not_selectable_sentence

    assert not_selectable_sentence("Temenos T24") is None


@pytest.mark.parametrize(
    "label",
    [
        "QA",
        "IT analysis",
        "Data engineering",
        "IT operations",
        "Test automation",
        "IT consulting",
        "Quality assurance",
        "PMO",
        "System administration",
    ],
)
def test_practices_outside_the_dictionary_do_not_gate(label):
    """30.09.2026: praktyki i role spoza słownika przechodziły regułę
    składniową; wysłani „mieli” je w 0–37% przypadków (audyt B2)."""
    assert gate_requirement(label) is None
