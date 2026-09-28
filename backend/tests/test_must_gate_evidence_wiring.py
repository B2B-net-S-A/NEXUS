"""Każde miejsce, które ukrywa kandydatów bramką must, dołącza dowody z CV
i notatek (decyzja 27.09.2026). Bez tego ekran liczyłby must z samego profilu
i CV, a notatki rekrutera nie liczyłyby się — dwa ekrany, dwie odpowiedzi."""

import ast
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
GATE_CALLS = {"apply_dealbreakers", "_apply_dealbreakers_yielding"}
# Wołający dołącza dowód piętro wyżej (funkcja jest synchroniczna albo
# pomocnicza) — wpis z powodem.
EXEMPT = {
    (
        "services/talent_radar_search.py",
        "_apply_dealbreakers_yielding",
    ): "pomocnik paczkujący; dowód dołącza search_talent przed wywołaniem",
    (
        "services/my_people_matching.py",
        "dealbreaker_exclusions",
    ): "synchroniczna; dowód dołącza run_for_job przed wywołaniem",
}


def _calls(node):
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            func = sub.func
            name = getattr(func, "id", None) or getattr(func, "attr", None)
            if name:
                yield name


def test_every_gate_caller_attaches_text_evidence():
    missing = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if rel == "services/dealbreaker_filters.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            names = set(_calls(fn))
            if not names & GATE_CALLS:
                continue
            if (rel, fn.name) in EXEMPT:
                continue
            if "attach_gate_evidence" not in names:
                missing.append(f"{rel}:{fn.name}")
    assert not missing, (
        "Te funkcje wołają bramkę must bez attach_gate_evidence: " + ", ".join(missing)
    )
