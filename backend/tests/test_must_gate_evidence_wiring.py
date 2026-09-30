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


def test_evidence_is_attached_for_every_technology_not_only_the_gate():
    """30.09.2026: bramka czyta tylko krytyczne, ale plakietki i ocena biorą
    dowód dla wszystkich technologii must i nice — dołączony raz na paczkę."""
    offenders = []
    for path in APP.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "attach_gate_evidence(" in line and ".must_skills" in line:
                offenders.append(f"{path.relative_to(APP).as_posix()}: {line.strip()}")
    assert not offenders, "Użyj .gate_evidence_labels: " + "; ".join(offenders)
