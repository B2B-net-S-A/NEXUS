"""Szkic uzasadnienia dopłaty premium (F5) — czyste funkcje, bez sieci. Dane fikcyjne."""

from app.services import premium_skill_justification as j


def _facts(**over):
    base = dict(
        technology="Kafka",
        percent="20",
        category="IT Developer - Senior",
        sources=[
            "CV",
            "oś czasu CV: 30 mies., obecnie",
            "karta techniczna projektu (opieka)",
        ],
        project_stack=["Kafka", "Java", "Spring Boot", "Java"],
        dl_note="Ola Testowa utrzymuje strumienie płatności na Kafce.",
        person_names=["Ola", "Testowa"],
    )
    base.update(over)
    return j.build_facts(**base)


def test_sources_are_translated_like_the_f4_template():
    assert j.source_en("CV") == "listed in the consultant's CV"
    assert j.source_en("oś czasu CV: 30 mies., obecnie") == (
        "30 months of hands-on use in the consultant's career timeline, "
        "ongoing on the current assignment"
    )
    assert (
        j.source_en("oś czasu CV") == "hands-on use in the consultant's career timeline"
    )
    assert (
        j.source_en("zweryfikowane na screeningu")
        == "verified in our technical screening"
    )
    assert j.source_en("coś nowego") == "coś nowego"


def test_facts_drop_the_name_and_the_technology_from_the_stack():
    facts = _facts()
    assert facts.dl_note == "the consultant utrzymuje strumienie płatności na Kafce."
    assert facts.project_stack == ("Java", "Spring Boot")


def test_prompt_has_facts_but_no_name_client_or_rate():
    prompt = j.build_prompt(_facts())
    assert "Kafka" in prompt and "20%" in prompt and "IT Developer - Senior" in prompt
    assert "30 months" in prompt and "Spring Boot" in prompt
    for absent in ("Ola", "Testowa", "115", "Bank"):
        assert absent not in prompt


def test_empty_note_and_missing_category_are_said_plainly():
    facts = _facts(dl_note="  ", category=None, sources=[], project_stack=[])
    block = j.facts_block(facts)
    assert "Examples from the project written by our Delivery Lead: none" in block
    assert "not set" in block and "Evidence collected by us: none" in block
    assert "Other technologies" not in block


def test_clean_draft_strips_wrappers_quotes_and_markdown():
    raw = 'Here is the justification:\n"**Kafka** is used daily.\n\n\n\nPlease apply."'
    assert j.clean_draft(raw) == "Kafka is used daily.\n\nPlease apply."
    assert j.clean_draft("   ") is None
    assert j.clean_draft(None) is None
    assert len(j.clean_draft("x" * 5000)) == j.MAX_DRAFT_CHARS


def test_invented_numbers_and_missing_technology_become_warnings():
    facts = _facts()
    ok = "Kafka is used daily; 30 months of use; the adder is 20%."
    assert j.warnings_for(ok, facts) == []
    invented = "The consultant has 5 years of experience and 12 certificates."
    warnings = j.warnings_for(invented, facts)
    assert any("(5, 12)" in w for w in warnings)
    assert any("nie wymienia technologii Kafka" in w for w in warnings)
