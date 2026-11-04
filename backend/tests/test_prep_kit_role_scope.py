"""Prep kit opisuje TĘ rolę, nie cały dorobek klienta (UAT B70).

Rola Power Platform bez opisu i bez Championa dostawała w przeglądzie stack
Angular/Java/Kafka z wiedzy o kliencie, te technologie jako „luki” oraz pytania
Angular z innych rekrutacji tego klienta.
"""

from types import SimpleNamespace

import pytest

from app.api.prep_kit import _role_stack_summary
from app.services import question_suggestions as qs
from app.services import scoring_service as scoring

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _taxonomy():
    scoring.set_alias_map(
        {
            s: s
            for s in (
                "angular",
                "java",
                "kafka",
                "power platform",
                "power automate",
                "developer",
            )
        }
    )


def _job(must=None, nice=None, title="Konsultant"):
    return SimpleNamespace(
        id=1,
        title=title,
        must_skills=must,
        nice_skills=nice,
        matching_requirements=None,
        requirements_reviewed=bool(must or nice),
        champion_profile=None,
        requirements=None,
        description=None,
    )


def test_stack_line_lists_the_role_requirements():
    line = _role_stack_summary(_job(must=["Power Platform"], nice=["Power Automate"]))
    assert "Power Platform" in line
    assert "power automate" in line.lower()
    assert "angular" not in line.lower()


def test_empty_role_says_no_data_instead_of_borrowing_client_stack():
    line = _role_stack_summary(_job())
    assert line.startswith("Wymagania techniczne roli: brak danych")


def test_question_about_a_foreign_technology_is_dropped():
    names = qs.job_requirement_names(_job(must=["Power Platform"]))
    foreign = qs.SuggestedQuestion(
        text="Jak zarządzasz stanem w Angular?", source_tier="tier_3_client_knowledge"
    )
    tagged = qs.SuggestedQuestion(
        text="Opowiedz o projekcie", source_tier="tier_1_same_cc", skill_tags=["java"]
    )
    assert not qs._fits_job(foreign, names)
    assert not qs._fits_job(tagged, names)


def test_matching_and_technology_free_questions_stay():
    names = qs.job_requirement_names(_job(must=["Power Platform"]))
    matching = qs.SuggestedQuestion(
        text="Jak budujesz rozwiązania w Power Platform?", source_tier="tier_1_same_cc"
    )
    generic = qs.SuggestedQuestion(
        text="Dlaczego szukasz nowego projektu?", source_tier="tier_3_client_knowledge"
    )
    role_word = qs.SuggestedQuestion(
        text="Jak pracujesz jako developer w zespole?",
        source_tier="tier_2_secondary_cc",
    )
    assert qs._fits_job(matching, names)
    assert qs._fits_job(generic, names)
    assert qs._fits_job(role_word, names)


def test_role_without_requirements_keeps_only_technology_free_questions():
    names = qs.job_requirement_names(_job())
    assert not qs._fits_job(
        qs.SuggestedQuestion(
            text="Kafka w produkcji?", source_tier="tier_3_client_knowledge"
        ),
        names,
    )
    assert qs._fits_job(
        qs.SuggestedQuestion(
            text="Jak wygląda Twoja dostępność?", source_tier="tier_3_client_knowledge"
        ),
        names,
    )


@pytest.mark.parametrize(
    "text,expected",
    [
        # Polskie litery nie są granicą słowa — „r” w „różni”, „c” w „dostając”.
        ("Czym się różni retest od testów regresji?", set()),
        ("Co zrobisz, dostając od PO taki temat?", set()),
        # Polskie słowa, które są też aliasami taksonomii.
        ("Jaka jest Twoja dostępność?", set()),
        ("Do czego służy INNER JOIN i kiedy go stosujemy?", set()),
        # Te same technologie napisane jak technologie zostają.
        ("Jak testujesz komponenty w Jest?", {"jest"}),
        ("Jak obsługujesz błędy w Go?", {"go"}),
        ("Jakich pakietów R używałeś do statystyki?", {"r"}),
        ("Jak zarządzasz pamięcią w C?", {"c"}),
        ("Pisałeś w C# i Java?", {"c#", "java"}),
    ],
)
def test_polish_words_are_not_technologies(text, expected):
    scoring.set_alias_map(
        {s: s for s in ("jest", "go", "r", "c", "c#", "java", "kafka")}
    )
    assert qs.mentioned_technologies(text) == expected
