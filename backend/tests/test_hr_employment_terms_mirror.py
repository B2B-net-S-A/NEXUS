"""Słowa według formy współpracy są JEDNE — front i backend (etap 2, D4).

Powiadomienia, maile i PDF raportu godzin biorą słowa z
``app/services/hr/employment_terms.EMPLOYMENT_TERMS``, ekrany z
``frontend/src/lib/hr-employment-terms.ts``. Rozjazd dałby osobie na B2B
„przerwę” w powiadomieniu i „urlop” na ekranie.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.services.hr.employment_terms import EMPLOYMENT_TERMS

_FRONT = (
    Path(__file__).resolve().parents[2]
    / "frontend"
    / "src"
    / "lib"
    / "hr-employment-terms.ts"
)
_BLOCK = re.compile(r"export const EMPLOYMENT_TERMS = (\{.*?\n\}) as const", re.S)


def test_frontend_terms_are_the_backend_terms_word_for_word() -> None:
    match = _BLOCK.search(_FRONT.read_text(encoding="utf-8"))
    assert match, "Nie znaleziono EMPLOYMENT_TERMS w hr-employment-terms.ts"
    assert json.loads(match.group(1)) == EMPLOYMENT_TERMS


def test_frontend_interface_lists_every_word() -> None:
    source = _FRONT.read_text(encoding="utf-8")
    interface = source.split("export interface EmploymentTerms {", 1)[1].split("}", 1)[
        0
    ]
    keys = set(re.findall(r"^\s+(\w+):", interface, re.M))
    assert keys == set(EMPLOYMENT_TERMS["uop"])
