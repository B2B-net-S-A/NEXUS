"""Formularz CV klienta: wartości pól z CV, screeningu i notatek (0522, PR 2).

Pola wzoru odczytał kod (``client_form_structure``). Tu model wpisuje do nich
fakty o kandydacie — podział pracy jak w odczytach „znajdź i zacytuj” (F25,
``debrief_from_text``):

* model zwraca każdą wartość z DOSŁOWNYM cytatem z CV albo notatek,
* KOD odrzuca wartość bez cytatu ze źródła, „TAK/NIE” spoza tych dwóch słów,
  ocenę w skali, której liczby nie ma w cytacie, i wartość z e-mailem albo
  telefonem. Imię i nazwisko wpisuje kod z profilu.

Czego zabrakło, zostaje puste i rekruter to uzupełnia — ocen 1–10 i numerów
certyfikatów zwykle nie ma w żadnym źródle. Model jest dodatkiem: błąd albo
brak klucza = formularz z samym imieniem i nazwiskiem do uzupełnienia ręcznie.
Do logu idą liczby, nie treść.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Optional

from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_feature import AIFeatureKey
from app.services.ai_models import model_chain_for
from app.services.ai_quota import ai_feature
from app.services.cv_qc import _json_object
from app.services.interview_slot_mail import _quote_in_text
from app.services.llm_prompts import CLIENT_FORM_FILL
from app.services.llm_providers import api_key_configured
from app.services.prompt_fencing import fence, json_for_prompt

logger = logging.getLogger(__name__)

FEATURE = AIFeatureKey.client_form_fill
CV_MAX = 30_000
NOTES_MAX = 15_000
VALUE_MAX = 1_500
EXTRA_ROWS_MAX = 10
QUOTE_PARTS_MAX = 8
ROWS_PARSED_MAX = 60

SOURCE_CV = "cv"
SOURCE_NOTES = "notes"
SOURCE_PROFILE = "profile"
SOURCE_RECRUITER = "recruiter"

MSG_UNAVAILABLE = (
    "Nie udało się wypełnić formularza automatycznie — uzupełnij pola ręcznie."
)

NAME_LABEL = re.compile(r"imi[eę]\s+i\s+nazwisko", re.IGNORECASE)
CITY_LABEL = re.compile(r"miejsce\s+zamieszkania", re.IGNORECASE)
YES_NO_LABEL = re.compile(r"tak\s*/\s*nie", re.IGNORECASE)
SCALE_LABEL = re.compile(r"skali|\b1\s*[-–]\s*10\b", re.IGNORECASE)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE = re.compile(r"\+?\d[\d \-]{7,}\d")


@dataclass(frozen=True)
class Sources:
    cv: str
    notes: str


def _short(value: Any, limit: int = VALUE_MAX) -> Optional[str]:
    if not isinstance(value, str):
        return None
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text[:limit] or None


def _grounded_one(quote: Any, sources: Sources) -> tuple[Optional[str], Optional[str]]:
    found = _quote_in_text(quote, sources.cv)
    if found is not None:
        return SOURCE_CV, found
    found = _quote_in_text(quote, sources.notes)
    if found is not None:
        return SOURCE_NOTES, found
    return None, None


def _grounded(quote: Any, sources: Sources) -> tuple[Optional[str], Optional[str]]:
    """(źródło, cytat) — cytat musi stać w CV albo w notatkach.

    Cytat może być listą fragmentów: tekst CV z dwukolumnowego PDF-a przeplata
    punkty z kolumną boczną, więc opis złożony z kilku punktów nie stoi w CV
    jednym ciągiem (staging 26.10.2026: 3 z 4 odrzuconych wartości). Każdy
    fragment musi stać w źródle osobno.
    """
    if isinstance(quote, list):
        found = [_grounded_one(part, sources) for part in quote[:QUOTE_PARTS_MAX]]
        if not found or any(part is None for _, part in found):
            return None, None
        source = (
            SOURCE_CV if any(src == SOURCE_CV for src, _ in found) else SOURCE_NOTES
        )
        return source, " … ".join(part for _, part in found if part)
    return _grounded_one(quote, sources)


def _contact(value: str) -> bool:
    """E-mail albo numer telefonu (9+ cyfr — okres „2019 - 2023” to nie telefon)."""
    if _EMAIL.search(value):
        return True
    return any(
        sum(ch.isdigit() for ch in match.group(0)) >= 9
        for match in _PHONE.finditer(value)
    )


def _checked_value(label: str, value: str, quote: str) -> Optional[str]:
    """Wartość po kontrolach kodu albo ``None`` (pole zostaje do uzupełnienia)."""
    if _contact(value):
        return None
    if YES_NO_LABEL.search(label):
        word = value.strip().upper()
        return word if word in ("TAK", "NIE") else None
    if SCALE_LABEL.search(label):
        number = value.strip()
        if not number.isdigit() or not 1 <= int(number) <= 10:
            return None
        return number if re.search(rf"(?<!\d){number}(?!\d)", quote) else None
    return value


def name_fields(structure: dict[str, Any]) -> list[str]:
    return _line_fields(structure, NAME_LABEL)


def _line_fields(structure: dict[str, Any], pattern: re.Pattern[str]) -> list[str]:
    return [
        item["id"]
        for item in structure.get("fields") or []
        if item.get("kind") == "line" and pattern.search(item.get("label") or "")
    ]


def extendable_tables(structure: dict[str, Any]) -> list[dict[str, Any]]:
    """Tabele z „…”: kolumny wiersza wzorcowego (``c<kolumna>`` → etykieta)."""
    return [
        {
            "table": table["index"],
            "title": table.get("title"),
            "columns": table.get("columns") or {},
        }
        for table in structure.get("tables") or []
        if table.get("extendable") and table.get("template_row") is not None
    ]


def check_parse(
    raw: str,
    *,
    structure: dict[str, Any],
    sources: Sources,
    candidate_name: str,
    candidate_city: str = "",
) -> dict[str, Any]:
    """Odpowiedź modelu → wartości, które przeszły kontrolę kodu. Czysta funkcja.

    Imię i nazwisko oraz miejsce zamieszkania (gdy profil je zna) wpisuje kod
    z profilu — model ich nie nadpisuje.
    """
    labels = {
        item["id"]: item.get("label") or "" for item in structure.get("fields") or []
    }
    profile = {
        **{field_id: candidate_name for field_id in name_fields(structure)},
        **{
            field_id: candidate_city for field_id in _line_fields(structure, CITY_LABEL)
        },
    }
    profile = {
        field_id: value.strip() for field_id, value in profile.items() if value.strip()
    }
    names = set(profile)
    fields: dict[str, dict[str, Any]] = {
        field_id: {"value": value, "source": SOURCE_PROFILE, "quote": None}
        for field_id, value in profile.items()
    }
    dropped = 0
    data = _json_object(raw) if raw else {}
    for item in data.get("fields") or []:
        if not isinstance(item, dict) or item.get("id") not in labels:
            dropped += 1
            continue
        field_id = item["id"]
        if field_id in names:
            continue
        value = _short(item.get("value"))
        source, quote = _grounded(item.get("quote"), sources)
        checked = (
            _checked_value(labels[field_id], value, quote)
            if value and quote is not None
            else None
        )
        if checked is None:
            dropped += 1
            continue
        fields[field_id] = {"value": checked, "source": source, "quote": quote}

    tables = {table["table"]: table for table in extendable_tables(structure)}
    extra_rows: list[dict[str, Any]] = []
    for row in (data.get("extra_rows") or [])[:ROWS_PARSED_MAX]:
        if not isinstance(row, dict) or row.get("table") not in tables:
            dropped += 1
            continue
        table = tables[row["table"]]
        cells: dict[str, dict[str, Any]] = {}
        for column, cell in (row.get("cells") or {}).items():
            if column not in table["columns"] or not isinstance(cell, dict):
                dropped += 1
                continue
            value = _short(cell.get("value"))
            source, quote = _grounded(cell.get("quote"), sources)
            checked = (
                _checked_value(table["columns"][column], value, quote)
                if value and quote is not None
                else None
            )
            if checked is None:
                dropped += 1
                continue
            cells[column] = {"value": checked, "source": source, "quote": quote}
        if cells:
            extra_rows.append({"table": table["table"], "cells": cells})
    # Najpierw puste wiersze wzoru, dopiero reszta ponad wzór — z limitem.
    kept: list[dict[str, Any]] = []
    per_table: dict[int, int] = {}
    for row in _into_free_rows(structure, fields, extra_rows):
        if per_table.get(row["table"], 0) >= EXTRA_ROWS_MAX:
            dropped += 1
            continue
        per_table[row["table"]] = per_table.get(row["table"], 0) + 1
        kept.append(row)
    return {"fields": fields, "extra_rows": kept, "dropped": dropped}


def _into_free_rows(
    structure: dict[str, Any],
    fields: dict[str, dict[str, Any]],
    extra_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Dopisane wiersze najpierw w puste wiersze wzoru tej tabeli.

    Model bywa, że pierwsze stanowisko wpisze do wiersza 1, a kolejne od razu
    do „extra_rows” — w dokumencie zostałyby puste wiersze 2–3 nad nimi.
    """
    free: dict[int, list[dict[str, str]]] = {}
    for item in structure.get("fields") or []:
        if item.get("kind") != "cell" or not (item.get("row_label") or "").startswith(
            "Wiersz "
        ):
            continue
        t_part, r_part, c_part = item["id"].split(".")
        table, row = int(t_part[1:]), int(r_part[1:])
        rows = free.setdefault(table, [])
        if not rows or rows[-1]["_row"] != str(row):
            rows.append({"_row": str(row)})
        rows[-1][c_part] = item["id"]
    left: list[dict[str, Any]] = []
    for extra in extra_rows:
        slots = [
            slot
            for slot in free.get(extra["table"], [])
            if not any(
                (fields.get(field_id) or {}).get("value")
                for key, field_id in slot.items()
                if key != "_row"
            )
        ]
        if not slots:
            left.append(extra)
            continue
        slot = slots[0]
        for column, cell in extra["cells"].items():
            if column in slot:
                fields[slot[column]] = cell
    return left


def missing_ids(structure: dict[str, Any], fields: dict[str, Any]) -> list[str]:
    return [
        item["id"]
        for item in structure.get("fields") or []
        if not (fields.get(item["id"]) or {}).get("value")
    ]


def build_prompt(structure: dict[str, Any], sources: Sources) -> str:
    fields = [
        {
            key: item.get(key)
            for key in ("id", "label", "row_label", "section", "table")
            if item.get(key)
        }
        for item in structure.get("fields") or []
        if not (
            item.get("kind") == "line" and NAME_LABEL.search(item.get("label") or "")
        )
    ]
    return CLIENT_FORM_FILL.render(
        fields=json_for_prompt(fields),
        tables=json_for_prompt(extendable_tables(structure)),
        cv=fence("cv", sources.cv[:CV_MAX]),
        notes=fence("screening_notes", sources.notes[:NOTES_MAX]),
    )


def _call_model(system: str, prompt: str, chain: tuple[str, ...]) -> str:
    from app.services.claude_client import call_claude, text_of  # noqa: PLC0415

    message = call_claude(
        model=chain[0],
        fallback_models=list(chain[1:]) or None,
        max_tokens=8000,
        thinking={"type": "disabled"},
        system=system,
        messages=[{"role": "user", "content": prompt}],
    )
    return text_of(message)


async def fill(
    db: AsyncSession,
    *,
    structure: dict[str, Any],
    sources: Sources,
    candidate_name: str,
    user_id: int,
    candidate_city: str = "",
) -> dict[str, Any]:
    """Wartości pól formularza. Nigdy nie rzuca — model to podpowiedź."""
    chain = tuple(model_chain_for(FEATURE))
    fallback = check_parse(
        "",
        structure=structure,
        sources=sources,
        candidate_name=candidate_name,
        candidate_city=candidate_city,
    )
    if not api_key_configured(chain[0]):
        return {
            **fallback,
            "status": "unavailable",
            "message": MSG_UNAVAILABLE,
            "model": None,
        }
    try:
        system = CLIENT_FORM_FILL.system_prompt or ""
        async with ai_feature(db, FEATURE, user_id=user_id):
            # Licznik AI zapisuje wiersz w tej sesji — commit PRZED modelem.
            await db.commit()
            raw = await run_in_threadpool(
                _call_model, system, build_prompt(structure, sources), chain
            )
        result = check_parse(
            raw,
            structure=structure,
            sources=sources,
            candidate_name=candidate_name,
            candidate_city=candidate_city,
        )
    except Exception as exc:  # noqa: BLE001 — AI to podpowiedź, nigdy bramka
        logger.warning("client_form_fill: model niedostępny (%s)", type(exc).__name__)
        return {
            **fallback,
            "status": "unavailable",
            "message": MSG_UNAVAILABLE,
            "model": None,
        }
    logger.info(
        "client_form_fill: %d pól, %d wierszy dopisanych, %d odrzuconych",
        len(result["fields"]),
        len(result["extra_rows"]),
        result["dropped"],
    )
    return {**result, "status": "ok", "message": None, "model": chain[0]}
