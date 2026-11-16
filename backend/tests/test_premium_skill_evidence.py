"""Propozycja „zna / korzysta” dla technologii premium (F3). Dane fikcyjne."""

from app.services.premium_skill_evidence import (
    PersonSkills,
    UsageRow,
    evidence,
    mentions,
    skill_names,
)


def test_mentions_uses_word_boundaries_and_aliases():
    assert mentions("Kubernetes", "Docker, K8s, Helm")
    assert mentions("Kubernetes", "OpenShift 4")
    assert mentions("T24 (Temenos Transact)", "Temenos T24 R20")
    assert mentions("Spark", "PySpark")
    assert not mentions("Scala", "Scalable systems")
    assert not mentions("Spark", "Sparkling")
    assert not mentions("Kafka", None)


def test_skill_names_accept_dicts_and_strings():
    assert skill_names(
        [{"name": "Kafka", "level": "senior"}, "Java", {"name": " "}, 3]
    ) == ("Kafka", "Java")
    assert skill_names(None) == ()


def test_card_on_project_means_uses_and_cv_only_means_knows():
    person = PersonSkills(
        cv_skills=("Kafka", "Snowflake"),
        usage=(UsageRow("Snowflake", 30, False),),
        tech_card=("Apache Kafka",),
    )
    out = evidence([("Kafka", "20"), ("Snowflake", "20"), ("PEGA", "10")], person)
    assert [(e.technology, e.knows, e.uses) for e in out] == [
        ("Kafka", True, True),
        ("Snowflake", True, False),
    ]
    assert out[0].sources == ("CV", "karta techniczna projektu (opieka)")
    assert out[1].sources == ("CV", "oś czasu CV: 30 mies.")


def test_current_usage_on_cv_timeline_proposes_uses():
    person = PersonSkills(
        usage=(UsageRow("Kubernetes", 14, True),), verified=("Kubernetes",)
    )
    (row,) = evidence([("Kubernetes", "20")], person)
    assert (row.knows, row.uses) == (True, True)
    assert row.sources == (
        "oś czasu CV: 14 mies., obecnie",
        "zweryfikowane na screeningu",
    )


def test_uses_first_then_higher_percent():
    person = PersonSkills(cv_skills=("PEGA", "Hadoop"), tech_card=("PEGA",))
    assert [
        e.technology for e in evidence([("Hadoop", "20"), ("PEGA", "10")], person)
    ] == ["PEGA", "Hadoop"]
