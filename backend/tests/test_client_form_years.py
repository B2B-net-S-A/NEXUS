"""Lata doświadczenia w formularzu CV klienta liczy kod ze stanowisk (19.11.2026).

DL CEZ: „nie daje rady odczytać lat doświadczenia w danej technologii”. Model
oddaje stanowiska z cytatami, kod sprawdza daty i liczy miesiące. Dane fikcyjne,
ale w kształcie CV z rekrutacji „Tester” na stagingu.
"""

from __future__ import annotations

import json
from datetime import date

from app.services import client_form_fill as fill
from app.services import client_form_structure as form
from app.services import client_form_years as years
from app.services.llm_prompts import CLIENT_FORM_FILL
from tests._client_form_docx import form_docx

TODAY = date(2026, 11, 15)
CV = (
    "Anna Fikcyjna\n"
    "03.2025 – obecnie Tester / Firma Alfa\n"
    "- testy manualne aplikacji, zgłaszanie błędów w Jira\n"
    "- przygotowanie planów testów i raportów z testów\n"
    "01.2024 – 02.2025 Młodszy tester / Firma Beta\n"
    "- testy regresji w projekcie dla NFZ\n"
    "2021 – 12.2023 Analityk / Firma Gamma\n"
    "- analiza wymagań\n"
    "06.2018 – 09.2018 Sprzedawca / Sklep Delta\n"
    "Umiejętności: SQL, Postman"
)
NOTES = "Kandydat nie pracował przy projektach związanych ze służbą zdrowia."
RULES = (
    "Dokumentacja testów: od 3 lat doświadczenia — 3 pkt. "
    "Służba zdrowia: 1 pkt za każdy rok, od 1 roku 1 pkt, od 2 lat 2 pkt, maks. 5 pkt."
)
ROLES = [
    {
        "key": "r1",
        "employer": "Firma Alfa",
        "title": "Tester",
        "start": "2025-03",
        "end": "obecnie",
        "quote": "03.2025 – obecnie Tester / Firma Alfa",
    },
    {
        "key": "r2",
        "employer": "Firma Beta",
        "title": "Młodszy tester",
        "start": "2024-01",
        "end": "2025-02",
        "quote": "01.2024 – 02.2025 Młodszy tester / Firma Beta",
    },
    {
        "key": "r3",
        "employer": "Firma Gamma",
        "title": "Analityk",
        "start": "2021",
        "end": "2023-12",
        "quote": "2021 – 12.2023 Analityk / Firma Gamma",
    },
]


def _structure() -> dict:
    return form.read_structure(form_docx()).to_json()


def _parse(answer: dict, structure: dict | None = None, rules: str = "") -> dict:
    return fill.check_parse(
        json.dumps(answer),
        structure=structure or _structure(),
        sources=fill.Sources(cv=CV, notes=NOTES, rules=rules),
        candidate_name="Anna Fikcyjna",
        today=TODAY,
    )


def test_years_fields_of_the_form() -> None:
    assert years.years_fields(_structure()) == {
        "p3": "total",
        "t2.r2.c3": "competency",
        "t2.r5.c2": "competency",
        "t2.r6.c2": "competency",
    }


def test_total_is_the_union_of_all_roles() -> None:
    # 2021-01 – 2026-11 bez przerw = 71 mies.
    result = _parse({"roles": ROLES, "years": []})
    total = result["fields"]["p3"]
    assert total["value"] == "5 lat 11 mies."
    assert total["source"] == "cv"
    assert [b["key"] for b in total["years"]["basis"]] == ["r1", "r2", "r3"]
    # Rok bez miesiąca liczy się od stycznia.
    assert total["years"]["basis"][2]["period"] == "2021 – 12.2023"


def test_competency_counts_direct_and_implied_roles() -> None:
    answer = {
        "roles": ROLES,
        "years": [
            {
                "id": "t2.r2.c3",
                "roles": [
                    {"key": "r1", "level": "role", "quote": "zgłaszanie błędów w Jira"},
                    {
                        "key": "r2",
                        "level": "implied",
                        "quote": "testy regresji w projekcie dla NFZ",
                    },
                ],
                "skills_quote": "SQL, Postman",
            }
        ],
    }
    entry = _parse(answer)["fields"]["t2.r2.c3"]
    # 2024-01 – 2026-11 = 35 mies.
    assert entry["value"] == "2 lata 11 mies."
    assert [(b["key"], b["level"]) for b in entry["years"]["basis"]] == [
        ("r1", "role"),
        ("r2", "implied"),
    ]
    # Rekruter zdejmuje rolę „pośrednio” — zostaje 21 mies.
    narrower = years.recompute(entry, {"r1"}, TODAY)
    assert narrower["value"] == "1 rok 9 mies."
    assert [b["on"] for b in narrower["years"]["basis"]] == [True, False]
    # Zdjęte wszystkie role = pole do uzupełnienia, siatka zostaje.
    empty = years.recompute(entry, set(), TODAY)
    assert empty["value"] is None and empty["years"]["basis"]


def test_skills_list_alone_gives_no_years_but_a_question() -> None:
    answer = {
        "roles": ROLES,
        "years": [{"id": "t2.r5.c2", "roles": [], "skills_quote": "SQL, Postman"}],
    }
    entry = _parse(answer)["fields"]["t2.r5.c2"]
    assert entry["value"] is None
    assert entry["years"]["skills"] == "SQL, Postman"
    assert entry["years"]["question"].startswith(
        "Długość doświadczenia z frameworkiem Selenium —"
    )
    assert "t2.r5.c2" in fill.missing_ids(_structure(), _parse(answer)["fields"])


def test_role_without_its_dates_in_the_quote_does_not_count() -> None:
    bad = [
        # Cytat bez dat roli.
        {**ROLES[0], "key": "x1", "quote": "Tester / Firma Alfa"},
        # Miesiąc, którego CV nie podaje.
        {**ROLES[2], "key": "x2", "start": "2021-06"},
        # „obecnie” bez słowa o trwającej pracy w cytacie.
        {**ROLES[1], "key": "x3", "end": "obecnie"},
        # Cytat spoza CV.
        {**ROLES[1], "key": "x4", "quote": "01.2024 – 02.2025 Lider zespołu"},
    ]
    result = _parse({"roles": bad, "years": []})
    assert result["fields"]["p3"]["value"] is None
    assert result["fields"]["p3"]["years"]["basis"] == []


def test_evidence_quote_must_stand_in_the_cv() -> None:
    answer = {
        "roles": ROLES,
        "years": [
            {
                "id": "t2.r2.c3",
                "roles": [
                    {"key": "r1", "level": "role", "quote": "zapytania SQL w Oracle"},
                    {"key": "r9", "level": "role", "quote": "analiza wymagań"},
                    {"key": "r3", "level": "wprost", "quote": "analiza wymagań"},
                ],
            }
        ],
    }
    result = _parse(answer)
    assert result["fields"]["t2.r2.c3"]["value"] is None
    assert result["dropped"] == 3


def test_model_value_stays_when_no_role_counts() -> None:
    # „0” z notatki o braku służby zdrowia — kod nie ma ról, wartość modelu zostaje.
    answer = {
        "fields": [
            {
                "id": "t2.r6.c2",
                "value": "0",
                "quote": "nie pracował przy projektach związanych ze służbą zdrowia",
            }
        ],
        "roles": ROLES,
        "years": [{"id": "t2.r6.c2", "roles": []}],
    }
    entry = _parse(answer)["fields"]["t2.r6.c2"]
    assert entry["value"] == "0" and entry["source"] == "notes"
    assert entry["years"]["basis"] == []


def _score_structure() -> dict:
    return {
        "fields": [
            {
                "id": "s0.r8.c4",
                "kind": "cell",
                "label": "Liczba punktów",
                "row_label": "Dokumentacja procesu testowania",
                "max_points": 3,
            },
            {
                "id": "s0.r9.c4",
                "kind": "cell",
                "label": "Liczba punktów",
                "row_label": "Staż w projektach związanych ze służbą zdrowia",
                "max_points": 5,
            },
        ]
    }


def test_points_follow_thresholds_from_the_scoring_rules() -> None:
    answer = {
        "roles": ROLES,
        "years": [
            {
                "id": "s0.r8.c4",
                "roles": [
                    {
                        "key": "r1",
                        "level": "role",
                        "quote": "przygotowanie planów testów i raportów z testów",
                    },
                    {
                        "key": "r2",
                        "level": "implied",
                        "quote": "testy regresji w projekcie dla NFZ",
                    },
                ],
                "thresholds": [{"years": 3, "points": 3}],
                "rules_quote": "od 3 lat doświadczenia — 3 pkt",
            },
            {
                "id": "s0.r9.c4",
                "roles": [
                    {
                        "key": "r2",
                        "level": "role",
                        "quote": "testy regresji w projekcie dla NFZ",
                    }
                ],
                "thresholds": [
                    {"years": 1, "points": 1},
                    {"years": 2, "points": 2},
                    {"years": 9, "points": 9},
                ],
                "rules_quote": "od 1 roku 1 pkt, od 2 lat 2 pkt",
            },
        ],
    }
    fields = _parse(answer, _score_structure(), RULES)["fields"]
    # 35 mies. < 3 lata → 0 z 3; zasady liczy kod, nie model.
    assert fields["s0.r8.c4"]["value"] == "0"
    # 14 mies. → próg 1 roku; próg 9 lat nie stoi w cytacie zasad.
    assert fields["s0.r9.c4"]["value"] == "1"
    assert fields["s0.r9.c4"]["years"]["thresholds"] == [
        {"years": 1, "points": 1},
        {"years": 2, "points": 2},
    ]
    assert years.points_for(200, [{"years": 1, "points": 9}], 5) == 5


def test_points_without_rules_quote_are_not_computed() -> None:
    answer = {
        "roles": ROLES,
        "years": [
            {
                "id": "s0.r8.c4",
                "roles": [{"key": "r1", "level": "role", "quote": "Tester"}],
                "thresholds": [{"years": 1, "points": 3}],
                "rules_quote": "od 1 roku — 3 pkt",
            }
        ],
    }
    assert "s0.r8.c4" not in _parse(answer, _score_structure(), RULES)["fields"]


def _over_minimum_structure() -> dict:
    return {
        "fields": [
            {
                "id": "t2.r7.c2",
                "kind": "cell",
                "label": "Liczba lat doświadczenia",
                "row_label": (
                    "Staż pracy liczony w latach ponad minimalne wymagania opisane "
                    "w OPZ - doświadczenie w testowaniu oprogramowania."
                ),
            }
        ]
    }


def _over_minimum_answer(**extra) -> dict:
    return {
        "roles": ROLES,
        "years": [
            {
                "id": "t2.r7.c2",
                "roles": [
                    {"key": "r1", "level": "role", "quote": "testy manualne aplikacji"},
                    {
                        "key": "r2",
                        "level": "role",
                        "quote": "testy regresji w projekcie dla NFZ",
                    },
                    {"key": "r3", "level": "implied", "quote": "analiza wymagań"},
                ],
                **extra,
            }
        ],
    }


def test_over_minimum_subtracts_the_quoted_minimum() -> None:
    rules = "Minimum 3 lata doświadczenia w testowaniu oprogramowania."
    answer = _over_minimum_answer(
        minimum_years=3, minimum_quote="Minimum 3 lata doświadczenia w testowaniu"
    )
    entry = _parse(answer, _over_minimum_structure(), rules)["fields"]["t2.r7.c2"]
    # 71 mies. − 36 = 35 mies.
    assert entry["value"] == "2 lata 11 mies."
    assert entry["years"]["minimum_months"] == 36


def test_over_minimum_without_a_known_minimum_stays_empty() -> None:
    # Bez minimum cały staż trafiłby do wiersza „ponad minimum” — za dużo.
    for extra in ({}, {"minimum_years": 2, "minimum_quote": "Minimum 2 lata"}):
        entry = _parse(_over_minimum_answer(**extra), _over_minimum_structure())[
            "fields"
        ]["t2.r7.c2"]
        assert entry["value"] is None
        assert entry["years"]["minimum_unknown"] is True


def test_points_over_minimum_follow_thresholds_of_the_whole_tenure() -> None:
    """Tabela „Testera ePP” CEZ (staging 26.11.2026): legenda wiersza „Staż ponad
    minimalne wymagania” daje progi całego stażu („1 pkt - więcej niż 3 lata”),
    więc minimum nie jest potrzebne. Kod zostawiał pole puste z „minimum
    nieznane”, bo minimum liczył tylko dla pól lat w formularzu Word."""
    structure = {
        "fields": [
            {
                "id": "s0.r12.c4",
                "kind": "cell",
                "label": "Liczba punktów (0–5 pkt)",
                "row_label": (
                    "Staż pracy liczony w latach ponad minimalne wymagania opisane "
                    "w OPZ - doświadczenie w testowaniu oprogramowania."
                ),
                "max_points": 5,
            }
        ]
    }
    rules = (
        "1 pkt - więcej niż 3 lata doświadczenia\n"
        "2 pkt - więcej niż 4 lata doświadczenia\n"
        "3 pkt - więcej niż 5 lat doświadczenia"
    )
    answer = _over_minimum_answer(
        thresholds=[
            {"years": 3, "points": 1},
            {"years": 4, "points": 2},
            {"years": 5, "points": 3},
        ],
        rules_quote=rules,
    )
    answer["years"][0]["id"] = "s0.r12.c4"
    entry = _parse(answer, structure, rules)["fields"]["s0.r12.c4"]
    # 71 mies. (5 lat 11 mies.) → próg 5 lat.
    assert entry["value"] == "3"
    assert entry["years"]["minimum_unknown"] is False


def test_without_model_answer_there_is_no_grid() -> None:
    result = fill.check_parse(
        "",
        structure=_structure(),
        sources=fill.Sources(cv=CV, notes=NOTES),
        candidate_name="Anna Fikcyjna",
        today=TODAY,
    )
    assert not any("years" in value for value in result["fields"].values())


def test_prompt_asks_for_roles_not_for_computed_years() -> None:
    prompt = CLIENT_FORM_FILL.render(
        fields="F", tables="T", years_fields="Y", cv="C", notes="N", rules="R"
    )
    assert 'NIE wpisuj w "fields" — lata policzy kod' in prompt
    # Lista pól lat od kodu — bez niej model pomijał „Kompetencje dodatkowe”.
    built = fill.build_prompt(_structure(), fill.Sources(cv=CV, notes=NOTES))
    assert '"id": "t2.r6.c2", "row": "Staż pracy w projektach' in built
    assert '"id": "p3"' in built
    assert '"roles": [{"key": str' in prompt
    assert '"thresholds": [{"years": int, "points": int}]' in prompt
    assert CLIENT_FORM_FILL.version == 7


def test_minimum_in_the_row_name_is_a_requirement_not_a_subtraction() -> None:
    # „Minimum 3-letnie doświadczenie w wytwarzaniu dokumentacji” to próg wymagania
    # (staging 20.11.2026: 4 lata 11 mies. zamieniło się w 1 rok 11 mies.).
    structure = {
        "fields": [
            {
                "id": "t2.r8.c2",
                "kind": "cell",
                "label": "Liczba lat doświadczenia",
                "row_label": (
                    "Minimum 3-letnie doświadczenie w wytwarzaniu dokumentacji "
                    "dla procesu testowania"
                ),
            }
        ]
    }
    answer = {
        "roles": ROLES,
        "years": [
            {
                "id": "t2.r8.c2",
                "roles": [
                    {
                        "key": "r1",
                        "level": "role",
                        "quote": "przygotowanie planów testów i raportów z testów",
                    }
                ],
                "minimum_years": 3,
                "minimum_quote": "Minimum 3-letnie doświadczenie",
            }
        ],
    }
    entry = _parse(answer, structure)["fields"]["t2.r8.c2"]
    assert entry["value"] == "1 rok 9 mies."
    assert entry["years"]["minimum_months"] is None


def test_client_test_and_free_rows_are_not_years_fields() -> None:
    # Staging 20.11.2026: „Test sprawdzający wiedzę” (test u klienta) i wolny
    # „Wiersz 1” dostawały pytanie „w której firmie i od kiedy do kiedy?”.
    structure = {
        "fields": [
            {
                "id": "t2.r13.c2",
                "kind": "cell",
                "label": "Liczba lat doświadczenia",
                "row_label": "Test sprawdzający wiedzę z zakresu wymagań podstawowych",
            },
            {
                "id": "t2.r15.c2",
                "kind": "cell",
                "label": "Liczba lat doświadczenia",
                "row_label": "Wiersz 1",
            },
            {
                "id": "t2.r9.c2",
                "kind": "cell",
                "label": "Liczba lat doświadczenia",
                "row_label": "Staż pracy w projektach związanych ze służbą zdrowia",
            },
        ]
    }
    assert years.years_fields(structure) == {"t2.r9.c2": "competency"}


def test_role_from_screening_note_counts_with_a_note_quote() -> None:
    # Pętla „pytanie na screeningu → notatka → Wypełnij ponownie”: okres
    # podany przez kandydata w rozmowie liczy się jak stanowisko z CV.
    notes = "Kandydat: Szpital Przykładowy, 03.2019 – 05.2021, testy systemu HIS."
    answer = {
        "roles": [
            {
                "key": "n1",
                "employer": "Szpital Przykładowy",
                "title": "Tester",
                "start": "2019-03",
                "end": "2021-05",
                "quote": "Szpital Przykładowy, 03.2019 – 05.2021",
            }
        ],
        "years": [
            {
                "id": "t2.r6.c2",
                "roles": [{"key": "n1", "level": "role", "quote": "testy systemu HIS"}],
            }
        ],
    }
    result = fill.check_parse(
        json.dumps(answer),
        structure=_structure(),
        sources=fill.Sources(cv=CV, notes=notes),
        candidate_name="Anna Fikcyjna",
        today=TODAY,
    )
    assert result["fields"]["t2.r6.c2"]["value"] == "2 lata 3 mies."
    prompt = CLIENT_FORM_FILL.render(
        fields="F", tables="T", years_fields="Y", cv="C", notes="N", rules="R"
    )
    assert "w notatce screeningu" in prompt


def test_ongoing_role_in_english_cv_counts_to_this_month() -> None:
    # 25.11.2026: CV po angielsku ma „03.2025 – currently”; gdy model przepisze
    # to słowo do "end" zamiast „obecnie”, stanowisko nie może wypaść z lat.
    for word in ("currently", "Present", "ongoing", "to date", "aktualnie"):
        cv = CV.replace("03.2025 – obecnie", f"03.2025 – {word}")
        roles = [
            {**ROLES[0], "end": word, "quote": f"03.2025 – {word} Tester / Firma Alfa"},
            *ROLES[1:],
        ]
        result = fill.check_parse(
            json.dumps({"roles": roles, "years": []}),
            structure=_structure(),
            sources=fill.Sources(cv=cv, notes=NOTES, rules=""),
            candidate_name="Anna Fikcyjna",
            today=TODAY,
        )
        total = result["fields"]["p3"]
        assert total["value"] == "5 lat 11 mies.", word
        assert total["years"]["basis"][0]["period"] == "03.2025 – obecnie", word
