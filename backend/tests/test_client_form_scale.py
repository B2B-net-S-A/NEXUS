"""0756: reguła klienta „doświadczenie = 10/10” w polach skali (bez bazy).

Fikcyjny formularz CEZ (``tests/_client_form_docx.py``): w tabeli kompetencji
wiersz „Selenium” ma „Liczba lat doświadczenia” (t2.r5.c2), „Stopień
zaawansowania w skali 1-10” (t2.r5.c3) i „Opis wykonywanych zadań” (t2.r5.c4).
"""

from __future__ import annotations

from datetime import date

from app.services import client_form_scale, client_form_structure
from tests._client_form_docx import form_docx

TODAY = date(2026, 11, 23)
ROLE = {
    "key": "r1",
    "start": "2023-07",
    "end": "obecnie",
    "on": True,
    "quote": "07.2023 – obecnie Automation Test Engineer",
}


def _structure() -> dict:
    return client_form_structure.read_structure(form_docx()).to_json()


def _years(*roles: dict) -> dict:
    return {
        "value": "2 lata" if any(r["on"] for r in roles) else None,
        "source": "cv",
        "quote": "07.2023",
        "years": {"basis": list(roles)},
    }


def test_years_from_roles_give_ten_and_override_the_model() -> None:
    fields = {
        "t2.r5.c2": _years(ROLE),
        "t2.r5.c3": {"value": "7", "source": "cv", "quote": "7"},
    }
    result = client_form_scale.apply(_structure(), fields, TODAY)
    assert result["t2.r5.c3"] == {
        "value": "10",
        "source": "client_rule",
        "quote": None,
    }
    assert fields["t2.r5.c3"]["value"] == "7"  # wejście bez zmian


def test_description_with_an_accepted_quote_gives_ten() -> None:
    fields = {
        "t2.r6.c4": {
            "value": "Testy systemu rejestracji pacjentów",
            "source": "notes",
            "quote": "testował rejestrację pacjentów",
        }
    }
    result = client_form_scale.apply(_structure(), fields, TODAY)
    assert result["t2.r6.c3"]["value"] == "10"
    assert "t2.r5.c3" not in result


def test_without_experience_the_scale_stays_empty() -> None:
    fields = {
        # Rola zdjęta w siatce i opis wpisany ręcznie (bez cytatu) to nie dowód.
        "t2.r5.c2": _years({**ROLE, "on": False}),
        "t2.r5.c3": {"value": "8", "source": "cv", "quote": "8 / 10"},
        "t2.r5.c4": {"value": "Selenium", "source": "recruiter", "quote": None},
        "t2.r6.c3": {"value": "10", "source": "client_rule", "quote": None},
    }
    result = client_form_scale.apply(_structure(), fields, TODAY)
    assert "t2.r5.c3" not in result
    assert "t2.r6.c3" not in result


def test_recruiter_value_wins() -> None:
    fields = {
        "t2.r5.c2": _years(ROLE),
        "t2.r5.c3": {"value": "6", "source": "recruiter", "quote": None},
        "t2.r6.c3": {"value": "3", "source": "recruiter", "quote": None},
    }
    result = client_form_scale.apply(_structure(), fields, TODAY)
    assert result["t2.r5.c3"]["value"] == "6"
    assert result["t2.r6.c3"]["value"] == "3"


def test_experience_in_another_row_does_not_count() -> None:
    result = client_form_scale.apply(_structure(), {"t2.r2.c3": _years(ROLE)}, TODAY)
    assert "t2.r5.c3" not in result and "t2.r6.c3" not in result


def test_only_scale_columns_are_touched() -> None:
    assert [item["id"] for item in client_form_scale.scale_fields(_structure())] == [
        "t2.r5.c3",
        "t2.r6.c3",
    ]
    structure = {"fields": [{"id": "p1", "kind": "line", "label": "Imię"}]}
    fields = {"p1": {"value": "Anna"}}
    assert client_form_scale.apply(structure, fields, TODAY) is fields


def test_description_saying_there_is_no_experience_is_not_evidence() -> None:
    """Staging 23.11.2026, „Tester Automatyczny” CEZ: opis z cytatem „Brak
    komercyjnego doświadczenia w sektorze healthcare.” dawał 10/10."""
    for text in (
        "Brak komercyjnego doświadczenia w sektorze healthcare.",
        "Nie posiada doświadczenia w projektach medycznych.",
        "Kandydat nie pracował w służbie zdrowia.",
        "No commercial experience in healthcare.",
    ):
        fields = {"t2.r6.c4": {"value": text, "source": "cv", "quote": text}}
        result = client_form_scale.apply(_structure(), fields, TODAY)
        assert "t2.r6.c3" not in result, text
