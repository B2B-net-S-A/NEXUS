"""Formularz CV klienta: rekruter tylko weryfikuje (23.11.2026, staging CEZ 789225).

Trzy źródła fałszywych „braków” z pomiaru (21–29 na osobę):

* zapasowe wiersze wzoru (3 wiersze „Wykształcenia” przy jednych studiach),
* druga tabela doświadczenia bez tytułu (pusty akapit między tabelami
  w formularzach CEZ) — model nie wiedział, czym jest,
* „TAK/NIE” — tylko z cytatem; bez dowodu pole zostaje puste.

Bez bazy; trasy w ``test_client_forms_api.py``.
"""

from __future__ import annotations

import json

from app.services import client_form_fill as fill
from app.services import client_form_structure as form
from tests._client_form_docx import continued_experience_docx, form_docx

CV = (
    "Jan Fikcyjny\nKierownik projektów IT\n"
    "07.2023 – obecnie Project Manager / Bank Przykładowy S.A.\n"
    "- prowadzenie harmonogramu w MS Project\n"
    "06.2020 – 01.2023 Specjalista / Firma Testowa Sp. z o.o.\n"
    "Umiejętności: MS Office, Jira"
)
SOURCES = fill.Sources(cv=CV, notes="Kandydat zarządzał zespołem 12 osób.")

ROW_1 = {
    "t1.r1.c1": "Bank Przykładowy S.A.",
    "t1.r1.c2": "07.2023 – obecnie",
    "t1.r1.c3": "Project Manager",
    "t1.r1.c4": "Harmonogram w MS Project",
}


def _structure() -> dict:
    return form.read_structure(form_docx()).to_json()


def _continued() -> dict:
    return form.read_structure(continued_experience_docx()).to_json()


def _values(values: dict[str, str]) -> dict[str, dict]:
    return {
        key: {"value": value, "source": "cv", "quote": value}
        for key, value in values.items()
    }


# ── zapasowe wiersze ─────────────────────────────────────────────────────────


def test_empty_spare_rows_after_a_filled_row_are_not_missing() -> None:
    structure = _structure()
    fields = _values(ROW_1)
    missing = fill.missing_ids(structure, fields)
    spare = form.spare_ids(structure, fields)
    assert {f"t1.r{row}.c{col}" for row in (2, 3) for col in (1, 2, 3, 4)} <= spare
    assert not any(field_id.startswith(("t1.r2.", "t1.r3.")) for field_id in missing)


def test_partly_filled_row_is_still_missing() -> None:
    structure = _structure()
    fields = _values({**ROW_1, "t1.r2.c1": "Firma Testowa Sp. z o.o."})
    missing = fill.missing_ids(structure, fields)
    assert {"t1.r2.c2", "t1.r2.c3", "t1.r2.c4"} <= set(missing)
    # Za częściowo wypełnionym wierszem 2 wiersz 3 dalej jest wolny.
    assert not any(field_id.startswith("t1.r3.") for field_id in missing)


def test_empty_table_keeps_its_first_row_missing() -> None:
    structure = _structure()
    missing = set(fill.missing_ids(structure, {}))
    assert {"t1.r1.c1", "t1.r1.c2", "t1.r1.c3", "t1.r1.c4"} <= missing
    assert not any(field_id.startswith(("t1.r2.", "t1.r3.")) for field_id in missing)


def test_named_rows_are_never_spare() -> None:
    # Kompetencje i certyfikat ze wzoru mają nazwę wiersza — to nie zapas.
    structure = _structure()
    missing = set(fill.missing_ids(structure, {"t2.r2.c2": {"value": "TAK"}}))
    assert {"t2.r5.c2", "t2.r6.c2", "t4.r1.c2", "t4.r1.c3"} <= missing


# ── druga tabela doświadczenia bez tytułu ────────────────────────────────────


def test_untitled_table_after_same_columns_continues_the_section() -> None:
    titles = form.table_titles(_continued())
    assert titles[1] == "Doświadczenie zawodowe"
    assert titles[2] == "Doświadczenie zawodowe — tabela 2"
    # Tabela z własnym tytułem i tymi samymi kolumnami to inna sekcja.
    assert (
        form.table_titles(_structure())[3] == "Doświadczenie w projektach publicznych"
    )


def test_prompt_names_the_continued_table_and_lets_only_the_first_grow() -> None:
    prompt = fill.build_prompt(_continued(), SOURCES)
    assert "Doświadczenie zawodowe — tabela 2" in prompt
    assert "tabela 2" in prompt and "najbliższe" in prompt
    tables = [table["table"] for table in fill.extendable_tables(_continued())]
    assert tables == [1]


def test_model_rows_for_the_continued_table_are_kept_and_not_appended() -> None:
    raw = json.dumps(
        {
            "fields": [
                {
                    "id": "t2.r1.c1",
                    "value": "Bank Przykładowy S.A.",
                    "quote": "Bank Przykładowy S.A.",
                },
                {
                    "id": "t2.r1.c3",
                    "value": "Project Manager",
                    "quote": "Project Manager",
                },
            ],
            "extra_rows": [
                {
                    "table": 2,
                    "cells": {
                        "c1": {
                            "value": "Firma Testowa Sp. z o.o.",
                            "quote": "Firma Testowa Sp. z o.o.",
                        }
                    },
                }
            ],
        }
    )
    result = fill.check_parse(
        raw, structure=_continued(), sources=SOURCES, candidate_name="Jan Fikcyjny"
    )
    assert result["fields"]["t2.r1.c1"]["value"] == "Bank Przykładowy S.A."
    assert result["extra_rows"] == []
    assert result["dropped"] == 1


# ── TAK/NIE tylko z cytatem ──────────────────────────────────────────────────


def _yes_no(item: dict) -> dict:
    raw = json.dumps({"fields": [item]})
    return fill.check_parse(
        raw, structure=_continued(), sources=SOURCES, candidate_name="Jan Fikcyjny"
    )["fields"]


def test_yes_with_a_quote_from_the_cv_is_proposed_with_that_quote() -> None:
    fields = _yes_no(
        {
            "id": "t3.r1.c2",
            "value": "TAK",
            "quote": "prowadzenie harmonogramu w MS Project",
        }
    )
    assert fields["t3.r1.c2"] == {
        "value": "TAK",
        "source": "cv",
        "quote": "prowadzenie harmonogramu w MS Project",
    }


def test_yes_or_no_without_a_quote_stays_empty() -> None:
    assert "t3.r1.c2" not in _yes_no({"id": "t3.r1.c2", "value": "TAK"})
    assert "t3.r2.c2" not in _yes_no({"id": "t3.r2.c2", "value": "NIE", "quote": None})
    # Cytat spoza CV i notatek to zgadywanie.
    assert "t3.r2.c2" not in _yes_no(
        {"id": "t3.r2.c2", "value": "TAK", "quote": "zarządzał zespołem 40 osób"}
    )


def test_no_needs_a_fact_from_the_sources() -> None:
    fields = _yes_no(
        {"id": "t3.r2.c2", "value": "NIE", "quote": "zarządzał zespołem 12 osób"}
    )
    assert fields["t3.r2.c2"]["value"] == "NIE"
    assert fields["t3.r2.c2"]["source"] == "notes"


def test_prompt_asks_for_yes_no_with_evidence_only() -> None:
    prompt = fill.build_prompt(_continued(), SOURCES)
    assert "TAK/NIE" in prompt
    # NIE tylko z faktem, który przeczy wymaganiu (np. zespół 12 osób przy „> 30”).
    assert "przeczy" in prompt
    assert "nie zgaduj" in prompt.lower()


# ── odpowiedź modelu z obiektem zamkniętym za wcześnie ───────────────────────


def test_answer_closed_too_early_keeps_rows_and_roles() -> None:
    """Staging 23.11.2026: 2 z 3 odpowiedzi miały „…]}, "roles": …” — główny
    obiekt zamknięty o jeden nawias za wcześnie. ``json.loads`` padał na „Extra
    data” i formularz zostawał z samym imieniem i nazwiskiem."""
    good = {
        "fields": [{"id": "t1.r1.c1", "value": "Bank Przykładowy S.A.", "quote": "Bank Przykładowy S.A."}],
        "extra_rows": [],
        "roles": [
            {
                "key": "r1",
                "employer": "Bank Przykładowy S.A.",
                "title": "Project Manager",
                "start": "2023-07",
                "end": "obecnie",
                "quote": "07.2023 – obecnie Project Manager / Bank Przykładowy S.A.",
            }
        ],
    }
    text = json.dumps(good)
    broken = text.replace('"extra_rows": []', '"extra_rows": []}', 1)
    assert fill.parse_answer(broken) == good
    assert fill.parse_answer(text) == good
