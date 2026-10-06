"""Strażnik: notatka pisze arkusz screeningu WYŁĄCZNIE przez ``screening_note_sync``.

Od 07.10.2026 odpowiedzi z notatek trafiają do arkusza (pochodzenie
``note_sync``), a arkusz z notatki widzi klient i liczy się w ocenie pary.
Reguły tego zapisu (arkusz człowieka nietykalny, próba procesu, dopasowanie
pytań) mieszkają w jednym module. Nowe miejsce zapisu arkusza albo nowy
moduł wstawiający ``note_sync`` = świadomy wpis tutaj.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_BACKEND = Path(__file__).resolve().parents[1]
_APP = _BACKEND / "app"

# Moduły, które zapisują `candidate_stages.screening_answers`.
_SHEET_WRITERS = {
    # Zapis arkusza przez człowieka (Tablica, warsztat screeningu).
    "app/api/pipeline.py",
    # Odpowiedzi przyjęte z notatki w oknie karty (0421) — człowiek klika.
    "app/api/recommendation_card_assist.py",
    # Trafienie „Odpada, gdy…” zaznaczone na karcie — człowiek klika.
    "app/api/recommendation_cards.py",
    # Kopia arkusza pary na nowy wiersz etapu przy ruchu karty.
    "app/services/recruitment_process_commands.py",
    # Automat: odpowiedzi z notatek (decyzje 07.10.2026).
    "app/services/screening_note_sync.py",
}

# Moduły, w których wolno użyć pochodzenia `note_sync`.
_NOTE_SYNC_USERS = {
    "app/schemas/champion.py",
    # Plakietka pochodzenia na karcie rekomendacji (tylko odczyt).
    "app/services/recommendation_card_rules.py",
    "app/services/screening_note_sync.py",
}


def _python_files():
    return sorted(_APP.rglob("*.py"))


def _relative(path: Path) -> str:
    return path.relative_to(_BACKEND).as_posix()


def _writes_sheet(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = list(node.targets)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            targets = [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "screening_answers":
                return True
            if (
                isinstance(target, ast.Subscript)
                and isinstance(target.slice, ast.Constant)
                and target.slice.value == "screening_answers"
            ):
                return True
        if isinstance(node, ast.Call):
            for keyword in node.keywords:
                if keyword.arg == "screening_answers":
                    return True
    return False


def test_only_listed_modules_write_the_screening_sheet() -> None:
    writers = {
        _relative(path)
        for path in _python_files()
        if _writes_sheet(ast.parse(path.read_text(encoding="utf-8")))
    }
    assert writers <= _SHEET_WRITERS, sorted(writers - _SHEET_WRITERS)


def test_no_raw_sql_writes_the_screening_sheet() -> None:
    offenders = []
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and "candidate_stages" in node.value.lower()
                and re.search(r"\bset\b[^;]*screening_answers", node.value, re.I)
            ):
                offenders.append(_relative(path))
    assert offenders == []


def test_note_sync_origin_is_used_only_by_the_sync_module() -> None:
    users = {
        _relative(path)
        for path in _python_files()
        if "note_sync" in {
            node.value
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
    }
    assert users <= _NOTE_SYNC_USERS, sorted(users - _NOTE_SYNC_USERS)
    assert "app/services/screening_note_sync.py" in users


def test_sync_module_is_the_only_note_to_sheet_bridge() -> None:
    # Moduły czytające karty rekomendacji nie zapisują arkusza samodzielnie.
    for module in (
        "app/services/recommendation_card_import.py",
        "app/services/recommendation_cards.py",
        "app/services/screening_note_backfill.py",
    ):
        tree = ast.parse((_BACKEND / module).read_text(encoding="utf-8"))
        assert not _writes_sheet(tree), module
