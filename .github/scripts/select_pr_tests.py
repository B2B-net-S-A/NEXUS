#!/usr/bin/env python3
"""Wybiera testy backendu związane ze zmianami w PR-ze.

Na PR-ze nie puszczamy już pełnego pytestu (~57 min testów rozłożonych na
shardy): pełny zestaw leci raz, w kolejce merge'ów, na dokładnie tym drzewie,
które trafia na maina. PR dostaje szybki sygnał z testów, które mają z jego
zmianą coś wspólnego. To jest SITO, nie dowód: test, który tylko woła endpoint
po HTTP i nie wymienia modułu z nazwy, może zostać pominięty — złapie go kolejka.

Reguły (każda dokłada pliki, żadna nie odejmuje):

* zmieniony plik testowy → on sam;
* zmieniony moduł ``backend/app/…`` → testy wymieniające jego ścieżkę kropkową
  (``app.services.foo`` albo ``from app.services import foo``) lub mające
  w nazwie jego rdzeń (``test_foo.py``, ``test_foo_*.py``);
* moduły-węzły (``config.py``, ``main.py``, baza, zależności) importuje prawie
  każdy test — dla nich tylko testy o ich nazwie; resztę sprawdzi kolejka;
* testy znalezione pośrednio (import, wzmianka) mają budżet czasu
  (``--budget-seconds``, domyślnie 300 s według ``ci_test_durations.json``),
  najszybsze pierwsze; pominięte wypisujemy na stderr, żeby było je widać;
* zmieniony pomocnik testów (``backend/tests/…`` bez ``test_``) → testy, które
  go importują; ``conftest.py`` → nic ponad resztę (dotyka wszystkiego, tego
  PR nie sprawdzi, sprawdzi kolejka);
* każdy inny plik (workflow, skrypt, dokument, plik frontendu czytany przez
  testy-lustra) → testy, które wymieniają jego ścieżkę.

Wejście: lista zmienionych plików (ścieżki od korzenia repo) na stdin.
Wyjście: ścieżki testów od katalogu ``backend/``, po jednej w linii.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
_BACKEND = _REPO / "backend"
_TESTS = _BACKEND / "tests"
_DURATIONS = _TESTS / "ci_test_durations.json"

# Importowane (pośrednio) przez niemal każdy test: pełne dopasowanie po imporcie
# wybrałoby 80–140 plików, czyli PR-owy odpowiednik pełnego biegu.
_HUB_MODULES = {
    "app/core/config.py",
    "app/main.py",
    "app/core/database.py",
    "app/api/deps.py",
    "app/models/__init__.py",
    "app/core/security.py",
}


def _test_files() -> dict[str, str]:
    found: dict[str, str] = {}
    for path in sorted(_TESTS.rglob("test_*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(_BACKEND).as_posix()
        found[rel] = path.read_text(encoding="utf-8", errors="ignore")
    return found


def _module_patterns(rel_from_backend: str) -> list[re.Pattern[str]]:
    """``app/services/foo.py`` → wzorce na ``app.services.foo`` i ``import foo``."""
    parts = list(Path(rel_from_backend).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    if not parts:
        return []
    dotted = ".".join(parts)
    patterns = [re.compile(rf"\b{re.escape(dotted)}\b")]
    if len(parts) > 1:
        parent, leaf = ".".join(parts[:-1]), parts[-1]
        patterns.append(
            re.compile(
                rf"from\s+{re.escape(parent)}\s+import\s+[^\n]*\b{re.escape(leaf)}\b"
            )
        )
    return patterns


def select(changed: list[str]) -> tuple[set[str], set[str]]:
    """Zwraca (wybrane wprost, wybrane pośrednio)."""
    tests = _test_files()
    direct: set[str] = set()
    indirect: set[str] = set()
    for raw in changed:
        path = raw.strip()
        if not path:
            continue
        if path.startswith("backend/"):
            rel = path[len("backend/") :]
            name = Path(rel).name
            if (
                rel.startswith("tests/")
                and name.startswith("test_")
                and rel.endswith(".py")
            ):
                if rel in tests:
                    direct.add(rel)
                continue
            if rel == "tests/conftest.py":
                continue
            if rel.endswith(".py") and (
                rel.startswith("app/") or rel.startswith("tests/")
            ):
                stem = Path(rel).stem
                if stem != "__init__":
                    direct.update(
                        t
                        for t in tests
                        if Path(t).name == f"test_{stem}.py"
                        or Path(t).name.startswith(f"test_{stem}_")
                    )
                if rel in _HUB_MODULES:
                    continue
                patterns = _module_patterns(rel)
                indirect.update(
                    t
                    for t, text in tests.items()
                    if any(p.search(text) for p in patterns)
                )
                continue
            needles = {rel, path}
        else:
            needles = {path}
            if "/" in path:
                needles.add(path.split("/", 1)[1])
        indirect.update(
            t for t, text in tests.items() if any(n in text for n in needles)
        )
    return direct, indirect - direct


def apply_budget(
    direct: set[str], indirect: set[str], budget: float, durations: dict[str, float]
) -> tuple[list[str], list[str]]:
    """Wprost zawsze; pośrednio najszybsze pierwsze, dopóki mieszczą się w budżecie."""
    fallback = 1.0
    spent = sum(durations.get(t, fallback) for t in direct)
    kept, dropped = set(direct), []
    for test in sorted(indirect, key=lambda t: (durations.get(t, fallback), t)):
        cost = durations.get(test, fallback)
        if spent + cost <= budget:
            kept.add(test)
            spent += cost
        else:
            dropped.append(test)
    return sorted(kept), sorted(dropped)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget-seconds", type=float, default=300.0)
    args = parser.parse_args()
    try:
        durations = json.loads(_DURATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        durations = {}
    direct, indirect = select(sys.stdin.read().splitlines())
    kept, dropped = apply_budget(direct, indirect, args.budget_seconds, durations)
    for test in kept:
        print(test)
    estimate = sum(durations.get(t, 1.0) for t in kept)
    print(
        f"Wybrano {len(kept)} plików testowych (~{estimate / 60:.1f} min); "
        f"poza budżetem {len(dropped)} — sprawdzi je kolejka merge'ów.",
        file=sys.stderr,
    )
    for test in dropped:
        print(f"  pominięty (budżet): {test}", file=sys.stderr)


if __name__ == "__main__":
    main()
