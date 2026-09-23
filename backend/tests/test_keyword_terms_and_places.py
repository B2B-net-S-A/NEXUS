"""Czyste reguły wyszukiwania z porównania z Traffitem (22.09.2026).

* ``keyword_terms`` — całe słowa, gwiazdka, fraza, znaki specjalne; wzorzec
  Pythona (wycinki) jest lustrem wzorca Postgresa (filtr).
* ``pl_places`` — nazwa → miejscowość bez polskich znaków, promień, województwo.
* ``candidate_snippets.extract_field_snippets`` — każde pole osobno, zakresy
  pogrubień, zakres pola.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import pl_places
from app.services.candidate_snippets import extract_field_snippets, snippets_as_text
from app.services.keyword_terms import (
    parse_keyword,
    pg_regex,
    py_regex,
    tsquery_text,
)


def _matches(keyword: str, text: str) -> bool:
    term = parse_keyword(keyword)
    assert term is not None
    return py_regex(term).search(text) is not None


@pytest.mark.parametrize(
    ("keyword", "text", "expected"),
    [
        ("java", "Senior Java Developer", True),
        ("java", "Java, Spring Boot", True),
        ("java", "Java/Kotlin", True),
        ("java", "C#/Java", True),
        ("java", "JavaScript, TypeScript", False),
        ("java", "Java8 i Spring", False),
        ("java*", "JavaScript, TypeScript", True),
        ("*script", "JavaScript", True),
        ("*script", "Script kiddie", True),
        ("bankow*", "doświadczenie w sektorze bankowym", True),
        ("bankowość", "bankowości inwestycyjnej", False),
        ("spring boot", "Spring   Boot 3", True),
        ("spring boot", "Spring Cloud, Boot camp", False),
        ("c++", "C++17, Python", True),
        ("c++", "C++17", True),
        (".net", "ASP.NET Core", True),
        (".net", "C# (.NET), Azure", True),
        (".net", "VB.NET", True),
        # Klauzula zgody w prawie każdym CV i domeny — nie technologia.
        (".net", "zgodę na przetwarzanie przez B2B.net S.A.", False),
        (".net", "www.behance.net/jan", False),
        ("node.js", "Node.js, React", True),
        ("c#", ".NET, C#, Azure", True),
        ("qa", "QA Engineer", True),
        ("qa", "aqua park", False),
        ("zażółć", "zażółć gęślą jaźń", True),
        ("żółć", "zażółć", False),
        ("Łódź", "biuro w łódź", True),
    ],
)
def test_python_pattern_matches_whole_words(keyword, text, expected):
    assert _matches(keyword, text) is expected


def test_star_alone_is_not_a_keyword():
    assert parse_keyword("*") is None
    assert parse_keyword("  ") is None


def test_tsquery_uses_index_only_for_plain_words_and_phrases():
    assert tsquery_text(parse_keyword("java")) == "java"
    assert tsquery_text(parse_keyword("java*")) == "java:*"
    assert tsquery_text(parse_keyword("spring boot")) == "spring <-> boot"
    assert tsquery_text(parse_keyword("spring boo*")) == "spring <-> boo:*"
    # Gwiazdka z przodu i znaki specjalne — regex, nie indeks.
    assert tsquery_text(parse_keyword("*script")) is None
    assert tsquery_text(parse_keyword("c++")) is None
    assert tsquery_text(parse_keyword("node.js")) is None


def test_pg_pattern_escapes_special_characters_and_keeps_boundaries():
    pattern = pg_regex(parse_keyword("c++"))
    assert "c\\+\\+" in pattern
    # „c++” zaczyna się literą (granica z lewej), kończy plusem (bez granicy).
    assert pattern.startswith("(^|[^") and pattern.endswith("c\\+\\+")
    assert pg_regex(parse_keyword("java*")).endswith("java")
    assert pg_regex(parse_keyword("*script")).startswith("script")
    assert "[[:space:]/-]+" in pg_regex(parse_keyword("spring boot"))


# ── Miejscowości ────────────────────────────────────────────────────────────


def test_place_is_found_without_polish_letters_and_by_alias():
    assert pl_places.resolve("lodz").name == "Łódź"
    assert pl_places.resolve("Warsaw").name == "Warszawa"
    assert pl_places.resolve("Jastrzebie Zdroj").voivodeship == "śląskie"
    assert pl_places.resolve("Trójmiasto").name == "Gdańsk"
    assert pl_places.resolve("Berlin") is None


def test_radius_contains_neighbours_and_not_distant_towns():
    krakow = pl_places.resolve("Kraków")
    near = set(pl_places.keys_within(krakow, 30))
    assert {"krakow", "wieliczka", "niepolomice"} <= near
    assert "katowice" not in near
    wider = set(pl_places.keys_within(krakow, 80))
    assert "katowice" in wider
    # Alias „Cracow” należy do Krakowa, więc wpada razem z nim.
    assert "cracow" in near


def test_voivodeship_keys():
    keys = set(pl_places.keys_in_voivodeships(["pomorskie"]))
    assert {"gdansk", "gdynia", "sopot", "trojmiasto"} <= keys
    assert "warszawa" not in keys


def test_sql_and_python_keys_agree_on_shape():
    assert pl_places.place_key("  Jastrzębie-Zdrój , Polska") == "jastrzebie zdroj"
    assert pl_places.place_key("Bielsko - Biała") == "bielsko biala"


def test_suggest_starts_with_biggest_towns():
    names = [p.name for p in pl_places.suggest("gd")]
    assert names[:2] == ["Gdańsk", "Gdynia"]
    assert pl_places.suggest("g") == []


# ── Wycinki pod wynikiem ────────────────────────────────────────────────────


def _cand(**kw):
    base = dict(
        raw_cv_text=None,
        experience=None,
        skills=None,
        ai_summary=None,
        engagement_notes=None,
        tags=None,
        education=None,
        languages=None,
        competence_category=None,
        location=None,
        city=None,
        email=None,
        name=None,
        lastname=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _bold(snippet: dict) -> list[str]:
    return [snippet["text"][s:e] for s, e in snippet["highlights"]]


def test_every_field_with_a_hit_is_listed_with_bold_words():
    cand = _cand(
        raw_cv_text="Built microservices in Java 17.\nAlso some JavaScript.",
        experience=[{"role": "Senior Java Developer", "company": "X"}],
        skills=[{"name": "Java"}, {"name": "Kafka"}],
    )
    snippets = extract_field_snippets(cand, ["java", "kafka"], ["Zna Kafka i Javę"])
    fields = [s["field"] for s in snippets]
    assert fields[:3] == ["Treść CV", "Stanowisko", "Umiejętności"]
    cv = snippets[0]
    assert _bold(cv) == ["Java"]  # JavaScript nie jest pogrubiony
    assert "\n" not in cv["text"]
    assert _bold(snippets[2]) == ["Java", "Kafka"]
    note = next(s for s in snippets if s["field"] == "Notatka")
    assert _bold(note) == ["Kafka"]


def test_scope_limits_snippets_to_one_field():
    cand = _cand(
        raw_cv_text="Java developer",
        experience=[{"role": "Java Developer"}],
    )
    snippets = extract_field_snippets(cand, ["java"], scope="title")
    assert [s["field"] for s in snippets] == ["Stanowisko"]


def test_wildcard_highlights_the_whole_word_and_text_form_keeps_labels():
    cand = _cand(raw_cv_text="Frontend: JavaScript, TypeScript")
    snippets = extract_field_snippets(cand, ["java*"])
    assert _bold(snippets[0]) == ["JavaScript"]
    assert snippets_as_text(snippets).startswith("Treść CV: ")
    assert snippets_as_text([]) is None


def test_highlights_are_utf16_offsets_after_emoji():
    cand = _cand(raw_cv_text="📧 kontakt · 📱 Java developer")
    snippet = extract_field_snippets(cand, ["java"])[0]
    start, end = snippet["highlights"][0]
    # Dwa emoji przed trafieniem = +2 jednostki UTF-16 względem znaków Pythona.
    utf16 = snippet["text"].encode("utf-16-le")
    assert utf16[start * 2 : end * 2].decode("utf-16-le") == "Java"


def test_short_wildcard_is_ignored_and_bare_star_is_no_keyword():
    term = parse_keyword("*go")
    assert term is not None and not term.open_start
    assert parse_keyword("**") is None


def test_whole_word_tsquery_has_path_variants():
    from app.services.keyword_terms import tsquery_path_variants

    assert tsquery_path_variants(parse_keyword("Java")) == "'java/':* | 'java-':*"
    assert tsquery_path_variants(parse_keyword("java*")) is None
    assert tsquery_path_variants(parse_keyword("łódź")) is None


def test_phrase_matches_hyphen_and_slash():
    assert _matches("spring boot", "Spring-Boot 3")
    assert _matches("spring boot", "Spring/Boot")
