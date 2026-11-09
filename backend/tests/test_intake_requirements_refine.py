"""Porządki wierszy po odczycie maila (M1, M2, M4, M5, 07.11.2026).

Przypadki z pomiaru na pięciu prawdziwych requestach (789170, 789180,
789198): to, co Delivery Lead poprawiał ręcznie po odczycie. Bez bazy.
"""

from contextlib import contextmanager

from app.services import intake_requirements_refine as refine
from app.services import keyword_suggest
from tests.taxonomy_fixture import PROD_LIKE_SKILLS, hydrated_taxonomy

SKILLS = {
    **PROD_LIKE_SKILLS,
    "MongoDB": ("database", ()),
    "CosmosDB": ("database", ("cosmos db",)),
    "Elasticsearch": ("database", ()),
    "MassTransit": ("messaging", ()),
    "Microsoft Orleans": ("backend", ()),
    ".NET": ("backend", ()),
    ".NET Core": ("backend", ()),
    "Dynamics 365": ("tools", ("d365",)),
    "Dataverse": ("tools", ()),
    "Terraform": ("devops", ()),
    "OAuth": ("security", ()),
    "Code Review": ("practice", ()),
    "GraphQL": ("api", ()),
}


@contextmanager
def dictionary():
    saved = keyword_suggest.catalog()
    names = list(SKILLS.items())
    keyword_suggest.load_catalog(
        [(i, name, cat) for i, (name, (cat, _a)) in enumerate(names)],
        [
            (i, alias)
            for i, (_n, (_c, aliases)) in enumerate(names)
            for alias in aliases
        ],
    )
    try:
        with hydrated_taxonomy(SKILLS):
            yield
    finally:
        keyword_suggest._catalog = saved


def _fold(text: str) -> str:
    return keyword_suggest.fold(text)


# ── M4 ──────────────────────────────────────────────────────────────────────


def test_list_after_commas_becomes_separate_rows():
    mail = "Wymagana znajomość baz: MongoDB, CosmosDB, Elasticsearch."
    rows = [{"words": ["MongoDB", "CosmosDB", "Elasticsearch"], "level": "must"}]
    with dictionary():
        out, notes = refine.split_listed_alternatives(rows, _fold(mail))
    assert [r["words"] for r in out] == [["MongoDB"], ["CosmosDB"], ["Elasticsearch"]]
    assert all(r["level"] == "must" for r in out)
    assert notes and "MongoDB, CosmosDB, Elasticsearch" in notes[0]


def test_alternatives_from_the_mail_stay_together():
    mail = "minimum 1 rok doświadczenia z MassTransit i/lub Microsoft Orleans"
    rows = [{"words": ["MassTransit", "Microsoft Orleans"], "level": "must"}]
    with dictionary():
        out, notes = refine.split_listed_alternatives(rows, _fold(mail))
    assert [r["words"] for r in out] == [["MassTransit", "Microsoft Orleans"]]
    assert notes == []


def test_same_family_and_non_dictionary_words_stay_together():
    mail = ".NET Core 6.0 lub nowszy, płatności"
    rows = [
        {"words": [".NET Core", ".NET"], "level": "must"},
        {"words": ["płatności", "płatn*", "payment*"], "level": "must"},
    ]
    with dictionary():
        out, _ = refine.split_listed_alternatives(rows, _fold(mail))
    assert [r["words"] for r in out] == [
        [".NET Core", ".NET"],
        ["płatności", "płatn*", "payment*"],
    ]


# ── M5 ──────────────────────────────────────────────────────────────────────


def test_trait_rows_go_to_the_interview_list():
    rows = [
        {"words": ["financial", "finance"], "level": "must"},
        {"words": ["drive"], "level": "must"},
        {"words": ["resilient"], "level": "must"},
        {"words": ["decision making"], "level": "nice"},
    ]
    with dictionary():
        out = refine.traits_to_talk(rows)
    assert [r["words"] for r in out.rows] == [["financial", "finance"]]
    assert out.talk == [
        {"name": "drive", "level": "must"},
        {"name": "resilient", "level": "must"},
        {"name": "decision making", "level": "nice"},
    ]
    assert "drive, resilient, decision making" in out.notes[0]


def test_tool_with_a_trait_word_inside_stays_a_search_row():
    rows = [
        {"words": ["Google Drive"], "level": "must"},
        {"words": ["Java"], "level": "must"},
    ]
    with dictionary():
        out = refine.traits_to_talk(rows)
    assert len(out.rows) == 2 and out.talk == [] and out.notes == []


# ── M2 ──────────────────────────────────────────────────────────────────────


def test_dictionary_technologies_in_the_mail_missing_from_rows():
    mail = (
        "Środowisko: Dynamics 365, Dataverse, Terraform, OAuth 2.0. "
        "Praktyki: code review. Jenkins jako CI."
    )
    rows = [{"words": ["Dynamics 365", "D365"], "level": "must"}]
    with dictionary():
        found = refine.mail_technologies(mail, rows)
    # Technologie z CV najpierw, potem narzędzia, praktyki na końcu; w grupie
    # kolejność z maila. Wiersz już jest.
    assert found == ["Terraform", "OAuth", "Jenkins", "Dataverse", "Code Review"]


def test_polish_words_and_names_inside_longer_names_are_not_mentions():
    # 789198 na stagingu: „jest” w zdaniu dawało bibliotekę Jest, a „Apache”
    # z „Apache Kafka” — serwer Apache HTTPD.
    skills = {"Jest": ("qa", ()), "Apache HTTPD": ("devops", ("apache",))}
    mail = "Projekt jest w banku. Integracje przez Apache Kafka i PostgreSQL."
    rows = [{"words": ["Java"], "level": "must"}]
    saved = dict(SKILLS)
    SKILLS.update(skills)
    try:
        with dictionary():
            found = refine.mail_technologies(mail, rows)
    finally:
        SKILLS.clear()
        SKILLS.update(saved)
    assert found == ["Kafka", "PostgreSQL"]


def test_dictionary_name_inside_a_row_phrase_counts_as_covered():
    mail = "Microsoft Dynamics 365 CE/CRM, C#/.NET, Terraform"
    rows = [
        {"words": ["Microsoft Dynamics 365 CE/CRM"], "level": "must"},
        {"words": ["C#/.NET"], "level": "must"},
    ]
    skills_saved = dict(SKILLS)
    SKILLS["Microsoft Dynamics 365"] = ("tools", ())
    try:
        with dictionary():
            found = refine.mail_technologies(mail, rows)
            proposal = refine.critical_proposal(
                rows, "minimum 5 lat z Microsoft Dynamics 365 CE/CRM", []
            )
    finally:
        SKILLS.clear()
        SKILLS.update(skills_saved)
    assert found == ["Terraform"]
    assert [p["label"] for p in proposal] == ["Microsoft Dynamics 365 CE/CRM"]


def test_roles_languages_and_covered_aliases_are_not_proposed():
    mail = "Backend developer, Java, Apache Kafka, angielski B2"
    rows = [{"words": ["Kafka"], "level": "must"}]
    with dictionary():
        found = refine.mail_technologies(mail, rows)
    assert "Software developer" not in found
    assert "Kafka" not in found
    assert found == ["Java"]


# ── M1 ──────────────────────────────────────────────────────────────────────


def test_critical_proposal_from_years_in_the_mail():
    mail = (
        "minimum 7 lat doświadczenia komercyjnego w programowaniu w technologii .NET\n"
        "minimum 5 lat doświadczenia w tworzeniu aplikacji webowych wykorzystujących React\n"
        "minimum 2 lata doświadczenia z GraphQL\n"
    )
    rows = [
        {"words": ["GraphQL"], "level": "must"},
        {"words": ["React"], "level": "must"},
        {"words": [".NET"], "level": "must"},
        {"words": ["Kafka"], "level": "nice"},
    ]
    with dictionary():
        proposal = refine.critical_proposal(rows, mail, ["Senior Fullstack Developer"])
    assert [p["label"] for p in proposal] == [".NET", "React"]
    assert proposal[0]["reason"].startswith("minimum 7 lat")


def test_long_phrase_from_the_mail_as_the_first_word_still_gets_a_proposal():
    mail = "minimum 5 lat pracy z Microsoft Dynamics 365 CE/CRM"
    rows = [{"words": ["Microsoft Dynamics 365 CE/CRM", "D365"], "level": "must"}]
    with dictionary():
        proposal = refine.critical_proposal(rows, mail, [])
    assert [p["label"] for p in proposal] == ["Microsoft Dynamics 365 CE/CRM"]


def test_years_go_to_the_nearest_technology():
    mail = (
        "Minimum 10 lat doświadczenia w technologiach Microsoft, w tym minimum 5 lat "
        "pracy z Dynamics 365 CE/CRM."
    )
    rows = [{"words": ["Dynamics 365", "D365"], "level": "must"}]
    with dictionary():
        proposal = refine.critical_proposal(rows, mail, [])
    assert [p["label"] for p in proposal] == ["Dynamics 365"]


def test_without_years_the_title_technology_is_proposed():
    rows = [
        {"words": ["Java"], "level": "must"},
        {"words": ["Spring Boot"], "level": "must"},
        {"words": ["Docker"], "level": "must"},
    ]
    with dictionary():
        proposal = refine.critical_proposal(
            rows, "Szukamy osoby do zespołu.", ["Java Developer"]
        )
    assert proposal == [{"label": "Java", "reason": "technologia z nazwy stanowiska"}]


def test_no_proposal_for_words_the_gate_cannot_check():
    rows = [{"words": ["płatności", "płatn*"], "level": "must"}]
    with dictionary():
        proposal = refine.critical_proposal(
            rows, "minimum 5 lat w płatnościach", ["płatności"]
        )
    assert proposal == []


# ── Odczyt w całości ────────────────────────────────────────────────────────


def test_refine_rows_rederives_fields_and_keeps_notes():
    from app.services.job_request_intake import (
        RequestIntake,
        refine_rows,
        with_proposals,
    )

    mail = (
        "Szukamy Java Developera. Bazy: MongoDB, CosmosDB.\n"
        "minimum 5 lat doświadczenia z Java\n"
        "Have good drive. Środowisko: Jenkins."
    )
    intake = RequestIntake(
        role_name="Java Developer",
        requirements=[
            {"words": ["Java"], "level": "must"},
            {"words": ["MongoDB", "CosmosDB"], "level": "must"},
            {"words": ["drive"], "level": "must"},
        ],
        advisories=["z modelu"],
    )
    with dictionary():
        out = with_proposals(refine_rows(intake, mail), mail)
    assert [r["words"] for r in out.requirements] == [
        ["Java"],
        ["MongoDB"],
        ["CosmosDB"],
    ]
    assert out.must == ["Java", "MongoDB", "CosmosDB"]
    assert out.search_requirements == [["Java"], ["MongoDB"], ["CosmosDB"]]
    assert out.experience["skills"] == [{"name": "drive", "level": "must"}]
    assert out.advisories[0] == "z modelu" and len(out.advisories) == 3
    assert out.critical_proposal == [
        {"label": "Java", "reason": "minimum 5 lat doświadczenia z Java"}
    ]
    assert out.mail_technologies == ["Jenkins"]
    assert {"critical_proposal", "mail_technologies"} <= set(out.as_dict())


def test_refine_rows_leaves_a_clean_reading_untouched():
    from app.services.job_request_intake import RequestIntake, refine_rows

    intake = RequestIntake(requirements=[{"words": ["Java"], "level": "must"}])
    with dictionary():
        assert refine_rows(intake, "Java") is intake
