"""Dopasowanie terminów w QC CV (`dz_review.found_in`, 13.10.2026).

Przypadki z pomiaru produkcji w fikcyjnej formie: QC mówiło „nie ma
w oryginale”, choć ta sama rzecz stała innym zapisem albo w drugim języku.
Prawdziwe trafienia muszą zostać (Redis spoza źródeł, Java ≠ JavaScript).
"""

import json
from pathlib import Path

import pytest

from app.services import dz_review as dz
from app.services.keyword_terms import parse_keyword


def _req(name: str) -> dz.Requirement:
    return dz.Requirement(label=name, alternatives=(name,), terms=(name,))


@pytest.mark.parametrize(
    ("term", "text"),
    [
        ("Entra ID", "Audyt bezpieczeństwa Azure: EntraID, Azure DevOps"),
        ("REST-assured", "Testy API z wykorzystaniem Java, Rest Assured i Selenium"),
        ("MS Office", "Jira, Office 365, raportowanie"),
        ("workshops", "Prowadziła warsztaty z klientem"),
        ("kSQL", "Strumienie na Kafce i KSQL"),
    ],
)
def test_same_thing_written_differently_supports_the_claim(
    term: str, text: str
) -> None:
    assert dz.found_in(text, _req(term), mode="support") is not None


@pytest.mark.parametrize(
    ("term", "text"),
    [
        ("bankowości", "Doświadczenie w bankowość i płatnościach"),
        ("mobile", "Testowała aplikacje webowe i mobilne"),
        ("Kafka", "Integracje oparte na Kafce"),
    ],
)
def test_inflection_and_translation_count_as_present(term: str, text: str) -> None:
    assert dz.found_in(text, _req(term), mode="presence") is not None


@pytest.mark.parametrize(
    ("term", "text", "mode"),
    [
        ("Redis", "PostgreSQL, MongoDB", "support"),
        ("Java", "JavaScript, TypeScript", "support"),
        ("Java", "JavaScript, TypeScript", "presence"),
        ("Go", "Google Cloud", "presence"),
        ("microservices", "Microsoft 365, Excel", "support"),
    ],
)
def test_real_gaps_stay_gaps(term: str, text: str, mode: str) -> None:
    assert dz.found_in(text, _req(term), mode=mode) is None


def test_every_curated_translation_is_a_valid_keyword() -> None:
    path = (
        Path(dz.__file__).resolve().parent.parent / "data" / "cv_term_translations.json"
    )
    groups = json.loads(path.read_text(encoding="utf-8"))["groups"]
    assert groups
    for group in groups:
        assert len(group) >= 2, group
        for word in group:
            parsed = parse_keyword(word)
            assert parsed is not None and parsed.text == word, word
            # Lista jest dokładna: bez gwiazdek (rdzeni), bo czyta ją blokada.
            assert not (parsed.open_end or parsed.open_start), word


@pytest.mark.parametrize(
    ("term", "text"),
    [
        ("APIs", "Projektowanie API dla systemu płatności"),
        ("aplikacji webowych", "Rozwój aplikacje webowe w React"),
        ("monitoringu produkcji", "Odpowiadał za monitoring produkcji"),
        ("Python/Perl", "Skrypty w Perlu i Bashu"),
    ],
)
def test_requirement_written_as_a_phrase_or_choice_counts_as_present(
    term: str, text: str
) -> None:
    assert dz.found_in(text, _req(term), mode="presence") is not None


@pytest.mark.parametrize(
    ("term", "text"),
    [
        ("PL/SQL", "Zapytania SQL w PostgreSQL"),
        ("aplikacji mobilnych", "Rozwój aplikacji webowych"),
    ],
)
def test_phrase_presence_still_needs_every_word(term: str, text: str) -> None:
    assert dz.found_in(text, _req(term), mode="presence") is None


@pytest.mark.parametrize(
    ("term", "text"),
    [
        # Przegląd PR 2: rdzeń 4 liter i słowa frazy w dowolnym miejscu
        # przepuszczały krytyczną umiejętność, której w CV nie ma.
        ("Spring", "Prowadził sprint planning i retrospektywy"),
        ("Scala", "Projektował scalable services"),
        ("Excel", "Excellent communication skills"),
        ("React", "Reactive programming w Javie"),
        ("Flask", "Pamięć flash w urządzeniach"),
        ("Unity", "Pisał unit tests"),
        ("Redux", "Reduced costs by 20%"),
        ("Spark", "Sparse matrices"),
        ("Teams", "Pracował w team leadership"),
        ("Google Cloud", "Google Analytics, Oracle Cloud"),
        ("Azure DevOps", "AWS DevOps, Azure Functions"),
    ],
)
def test_presence_does_not_take_a_prefix_or_scattered_words(
    term: str, text: str
) -> None:
    assert dz.found_in(text, _req(term), mode="presence") is None
