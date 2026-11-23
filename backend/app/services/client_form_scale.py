"""Reguła klienta „doświadczenie = 10/10” w polach skali formularza (0756).

Delivery Lead Centrum e-Zdrowia (20.11.2026): „Jeżeli kandydat ma jakieś
doświadczenie w czymś, wpisujemy poziom 10/10.” Dotyczy pól „Stopień
zaawansowania w skali 1–10” w tabeli kompetencji, gdzie w tym samym wierszu
stoją „Liczba lat doświadczenia” i „Opis wykonywanych zadań”.

Liczy KOD, nie model: przy włączonej fladze klienta
(``clients.client_form_scale_full_on_experience``) pole skali dostaje „10”,
gdy w tym samym wierszu kod policzył lata z ról w CV (miesiące > 0 z ról
włączonych w siatce, ``client_form_years``) albo opis ma przyjęty cytat z CV
lub notatek, a nie mówi o braku doświadczenia. Bez tego pole zostaje puste
do uzupełnienia — także wtedy, gdy model wpisał ocenę. Wartość rekrutera
(``source = recruiter``) wygrywa zawsze.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from app.services.client_form_fill import (
    DESCRIPTION_LABEL,
    SCALE_LABEL,
    SOURCE_CV,
    SOURCE_NOTES,
    SOURCE_RECRUITER,
)
from app.services.client_form_years import months_of, years_fields

SOURCE_CLIENT_RULE = "client_rule"
FULL_SCALE = "10"
# Opis, który mówi o BRAKU doświadczenia, nie jest dowodem (staging 23.11.2026,
# „Tester Automatyczny” CEZ: „Brak komercyjnego doświadczenia w sektorze
# healthcare.” z cytatem dawało 10/10).
NO_EXPERIENCE = re.compile(
    r"^\s*(?:brak|nie|bez|no|none|n/?a)\b"
    r"|\bbrak\s+(?:\w+\s+)?do[sś]wiadcz"
    r"|\bnie\s+(?:posiada|ma|mia[łl]\w*|pracowa\w*|zna)\b"
    r"|\bno\s+(?:\w+\s+)?experience",
    re.IGNORECASE,
)


def _row(field_id: str) -> str | None:
    """``t2.r7.c3`` → ``t2.r7``; pole spoza tabeli (``p3``) nie ma wiersza."""
    parts = field_id.split(".")
    return ".".join(parts[:2]) if len(parts) == 3 else None


def _experience(
    row_items: list[dict[str, Any]],
    fields: dict[str, Any],
    years_ids: set[str],
    today: date,
) -> bool:
    for item in row_items:
        entry = fields.get(item["id"]) or {}
        if item["id"] in years_ids:
            basis = (entry.get("years") or {}).get("basis") or []
            if months_of(basis, today) > 0:
                return True
        elif DESCRIPTION_LABEL.search(item.get("label") or ""):
            if (
                entry.get("value")
                and entry.get("quote")
                and entry.get("source") in (SOURCE_CV, SOURCE_NOTES)
                and not NO_EXPERIENCE.search(str(entry["value"]))
            ):
                return True
    return False


def scale_fields(structure: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in structure.get("fields") or []
        if _row(item["id"]) is not None and SCALE_LABEL.search(item.get("label") or "")
    ]


def apply(
    structure: dict[str, Any], fields: dict[str, Any], today: date
) -> dict[str, Any]:
    """Pola po regule klienta. Czysta funkcja — nie zmienia ``fields``."""
    targets = scale_fields(structure)
    if not targets:
        return fields
    by_row: dict[str, list[dict[str, Any]]] = {}
    for item in structure.get("fields") or []:
        row = _row(item["id"])
        if row is not None:
            by_row.setdefault(row, []).append(item)
    years_ids = set(years_fields(structure))
    result = dict(fields)
    for target in targets:
        field_id = target["id"]
        if (result.get(field_id) or {}).get("source") == SOURCE_RECRUITER:
            continue
        siblings = [
            item for item in by_row[_row(field_id) or ""] if item["id"] != field_id
        ]
        if _experience(siblings, result, years_ids, today):
            result[field_id] = {
                "value": FULL_SCALE,
                "source": SOURCE_CLIENT_RULE,
                "quote": None,
            }
        else:
            result.pop(field_id, None)
    return result
