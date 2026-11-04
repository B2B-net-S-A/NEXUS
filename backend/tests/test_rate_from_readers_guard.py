"""Strażnik „Stawki od” (0414): stawkę kandydata czyta się przez
``candidate_rate_from.effective_rate*`` / ``rate_summary``, nie wprost.

Filtry, AI, plakietki budżetu i listy mają porównywać budżet z NAJNIŻSZĄ
stawką z 18 miesięcy. Bezpośredni odczyt ``expected_rate_hourly`` (stawki
zapisanej ostatnio w profilu) w nowym module po cichu przywróciłby stary
rozjazd. Moduły poniżej czytają pole świadomie: piszą je, pokazują w edycji
profilu albo liczą z niego „Stawkę od”.
"""

from __future__ import annotations

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"

ALLOWED = {
    # liczenie „Stawki od” i jej wejścia
    "services/candidate_rate_from.py",
    "services/candidate_rate_observations.py",
    # zapis i edycja stawki profilu
    "services/candidate_profile_rate.py",
    "services/candidate_profile_facts.py",
    "api/candidate_profile_facts.py",
    "services/candidate_notes_facts.py",
    "services/notes_insights_extractor.py",
    "services/trainee_program.py",
    "services/candidate_merge.py",
    "services/public_apply.py",
    # cofnięcie stawki scrapera porównuje DOKŁADNIE zapisaną kwotę profilu
    # z kwotą scrapera (audyt 06.10.2026, ochrona przed scaleniem kandydatów)
    "services/scraper_rate_revert.py",
    # eksport (kolumna profilu obok „Stawki od”), podgląd profilu, walidacja zapisu
    "api/import_export.py",
    "api/candidates.py",
    "schemas/candidate.py",
    # podpowiedź „stawka z profilu” w oknie „Zweryfikowany” obok „Stawki od”
    "api/pipeline.py",
    # pole wiersza „Moi ludzie” (`PersonRow`) — liczone już z `rate_summary`
    "api/my_people.py",
}


def _reads(tree: ast.AST) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "expected_rate_hourly":
            if not isinstance(node.ctx, ast.Store):
                lines.append(node.lineno)
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "getattr"
            and len(node.args) >= 2
            and isinstance(node.args[1], ast.Constant)
            and node.args[1].value == "expected_rate_hourly"
        ):
            lines.append(node.lineno)
    return lines


def test_profile_rate_is_read_only_by_allowed_modules():
    offenders: list[str] = []
    for path in sorted(APP.rglob("*.py")):
        rel = path.relative_to(APP).as_posix()
        if rel.startswith("models/") or rel in ALLOWED:
            continue
        for line in _reads(ast.parse(path.read_text(encoding="utf-8"))):
            offenders.append(f"{rel}:{line}")
    assert not offenders, (
        "Odczyt `expected_rate_hourly` poza dozwolonymi modułami — czytaj przez "
        "`candidate_rate_from.effective_rate` / `rate_summary`: " + ", ".join(offenders)
    )
