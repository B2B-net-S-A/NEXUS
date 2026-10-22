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
  (``--budget-seconds``, domyślnie ``DEFAULT_BUDGET_SECONDS`` według
  ``ci_test_durations.json`` + narzut kolekcji), najszybsze pierwsze; pominięte
  wypisujemy na stderr, żeby było je widać;
* zmieniony pomocnik testów (``backend/tests/…`` bez ``test_``) → testy, które
  go importują; ``conftest.py`` → nic ponad resztę (dotyka wszystkiego, tego
  PR nie sprawdzi, sprawdzi kolejka);
* każdy inny plik (workflow, skrypt, dokument, plik frontendu czytany przez
  testy-lustra) → testy, które wymieniają jego ścieżkę;
* strażnicy całego repo (``_ALWAYS``) → zawsze, niezależnie od zmian.

Sito biegnie w ``SIEVE_SHARDS`` jobach (``--shards``/``--shard``): każdy liczy ten
sam wybór i bierze swoją część (podział LPT po czasie, jak shardy kolejki).
Macierz bramek tras (~150 s w sicie, jeden plik) dzieli się po trasach między
wszystkie aktywne części (``AUTHZ_MATRIX_SLICE``, ``--env-out``). Mały wybór
zajmuje tylko jedną część; pozostałe kończą się bez instalacji zależności.

``--guards`` wypisuje samych strażników ``_ALWAYS`` — dla szybkiego kroku
kolejki merge'ów w ``ci-gate.yml`` (bez bazy).

Wejście: lista zmienionych plików (ścieżki od korzenia repo) na stdin.
Wyjście: ścieżki testów od katalogu ``backend/``, po jednej w linii.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import statistics
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

# Strażnicy całego repo: sprawdzają stan drzewa (stemple przewodników
# i procedury zamówień, jedna głowa Alembica), a nie konkretny moduł, więc
# żadna reguła wyżej ich nie wybiera. Wyrzucały PR-y z kolejki merge'ów
# najczęściej — 40 wyrzuceń 23–24.09.2026: stempel przewodników 34×,
# procedury zamówień 20×, dwie głowy Alembica 13×. PR był na tym zielony,
# więc `auto-enqueue` po każdym pushu wrzucał go z powrotem na ten sam pad.
#
# 21.10.2026 dołączyły trzy, które tak samo wyrzucały PR-y (#2522, #2540,
# #2542): daty liczone przy imporcie testu, `asyncio.create_task` poza
# `core.tasks.spawn` (app/services/ranking_publish.py:160) i snapshot API v1
# (nazwa schematu `EventOut`). Każdy ~10–14 s lokalnie (ast całego drzewa,
# `app.openapi()`), ~25 s na runnerze — wyjątek od reguły „poniżej 2 s”, bo
# wyrzucenie z kolejki kosztuje ~25 min i wszystkie PR-y za nim. Reszta to
# skanery drzewa z przeglądu `rglob(`/`os.walk(` (38 plików): bez bazy,
# poniżej 0,5 s każdy (pomiar lokalny, py3.12). Poza listą zostały skanery
# z testami na bazie albo dłuższe niż ~2 s (np. `test_no_utc_calendar_date`
# 15 s, `test_retired_roles_guard` 24 s, `test_jarvis_tool_registry_contract`
# 8 s) — łapie je kolejka. Ten sam zestaw biegnie w kolejce merge'ów
# w ``ci-gate.yml`` („Backend (lint + migrations)”), więc zły PR wypada po
# ~3 min, a nie po ~25. Razem ~90 s na runnerze; tylko bez bazy.
_ALWAYS = (
    "tests/test_screen_guides_freshness.py",
    "tests/test_orders_procedure_freshness.py",
    "tests/test_contract_order_workflows_migration.py",
    "tests/test_claude_md_index.py",
    "tests/test_no_import_time_dates.py",
    "tests/test_core_tasks_spawn.py",
    "tests/test_integrations_v1_contract.py",
    "tests/test_ci_coverage_contract.py",
    "tests/test_client_tab_links.py",
    "tests/test_funnel_coverage.py",
    "tests/test_insights_team_activity_sources.py",
    "tests/test_loop_heartbeat.py",
    "tests/test_no_recruitment_types.py",
    "tests/test_recommendation_card_ai_privacy.py",
)

# Macierz bramek tras (werdykt trasa × persona, wzorzec w
# ``tests/data/authz_golden``). Bramki siedzą w zależnościach rozsianych po
# całym ``app/``, więc zmiana dowolnego pliku aplikacji może zmienić werdykt
# którejś trasy — a żadna reguła niżej nie wybierze testu, który nie wymienia
# modułu z nazwy. Bez bazy, ale najdłuższy plik sita: ~150 s na runnerze
# (w shardzie kolejki 390 s), dlatego dzielony po trasach między części sita.
_AUTHZ_MATRIX = "tests/test_authz_guard_matrix.py"
_AUTHZ_GOLDEN_DIR = "tests/data/authz_golden/"
_AUTHZ_SLICE_ENV = "AUTHZ_MATRIX_SLICE"

# Szacunek czasu sita = suma czasów plików z ``ci_test_durations.json`` (z
# fixture'ami bazy — mapa liczy odstępy między testami w logu) + narzut
# procesu pytest: kolekcja, import aplikacji i pierwszy test. Zmierzone
# 21.10.2026 na biegach sita: 36 s przy 34 plikach, 79–102 s przy 186–287.
_RUN_OVERHEAD_SECONDS = 30.0
_PER_FILE_OVERHEAD_SECONDS = 0.3
# Części sita (matrix joba w ci.yml musi mieć tyle samo pozycji) i czas
# pytesta, ponad który dokładamy kolejną część. Z narzutem joba (kontener,
# instalacja, migracje: ~80 s) część trwa ≤ ~5,5 min.
SIEVE_SHARDS = 3
SHARD_TARGET_SECONDS = 240.0
DEFAULT_BUDGET_SECONDS = SIEVE_SHARDS * SHARD_TARGET_SECONDS


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
    direct: set[str] = {t for t in _ALWAYS if t in tests}
    indirect: set[str] = set()
    for raw in changed:
        path = raw.strip()
        if not path:
            continue
        if path.startswith("backend/"):
            rel = path[len("backend/") :]
            name = Path(rel).name
            if _AUTHZ_MATRIX in tests and (
                rel.startswith(_AUTHZ_GOLDEN_DIR)
                or (rel.startswith("app/") and rel.endswith(".py"))
            ):
                direct.add(_AUTHZ_MATRIX)
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


def _fallback(durations: dict[str, float]) -> float:
    """Plik bez pomiaru waży medianę zmierzonych — jak w conftest shardów."""
    return statistics.median(durations.values()) if durations else 1.0


def estimate_seconds(tests, durations: dict[str, float]) -> float:
    """Szacowany czas jednego procesu pytest na tych plikach (z narzutem)."""
    tests = list(tests)
    if not tests:
        return 0.0
    fallback = _fallback(durations)
    return (
        _RUN_OVERHEAD_SECONDS
        + _PER_FILE_OVERHEAD_SECONDS * len(tests)
        + sum(durations.get(t, fallback) for t in tests)
    )


def apply_budget(
    direct: set[str], indirect: set[str], budget: float, durations: dict[str, float]
) -> tuple[list[str], list[str]]:
    """Wprost zawsze; pośrednio najszybsze pierwsze, dopóki mieszczą się w budżecie."""
    fallback = _fallback(durations)
    spent = estimate_seconds(direct, durations)
    kept, dropped = set(direct), []
    for test in sorted(indirect, key=lambda t: (durations.get(t, fallback), t)):
        cost = durations.get(test, fallback) + _PER_FILE_OVERHEAD_SECONDS
        if spent + cost <= budget:
            kept.add(test)
            spent += cost
        else:
            dropped.append(test)
    return sorted(kept), sorted(dropped)


def plan_shards(
    kept: list[str], durations: dict[str, float], shards: int = SIEVE_SHARDS
) -> list[tuple[list[str], str | None]]:
    """Dzieli wybrane pliki na ``shards`` części: ``[(pliki, wycinek macierzy)]``.

    Aktywnych części jest tyle, ile trzeba, żeby każda zmieściła się
    w ``SHARD_TARGET_SECONDS`` (najwyżej ``shards``); reszta dostaje pustą
    listę. Macierz bramek tras trafia do KAŻDEJ aktywnej części z wycinkiem
    ``i/n`` (co n-ta trasa), pozostałe pliki — LPT od najdłuższego do części
    z najmniejszą sumą. Deterministyczne: każda część liczy to samo.
    """
    fallback = _fallback(durations)
    total = estimate_seconds(kept, durations)
    active = max(1, min(shards, math.ceil(total / SHARD_TARGET_SECONDS)))
    matrix = _AUTHZ_MATRIX in kept and active > 1
    rest = [t for t in kept if not (matrix and t == _AUTHZ_MATRIX)]
    share = durations.get(_AUTHZ_MATRIX, fallback) / active if matrix else 0.0
    loads = [share] * active
    parts: list[list[str]] = [[] for _ in range(active)]
    for test in sorted(rest, key=lambda t: (-durations.get(t, fallback), t)):
        target = min(range(active), key=lambda i: (loads[i], i))
        parts[target].append(test)
        loads[target] += durations.get(test, fallback) + _PER_FILE_OVERHEAD_SECONDS
    plan: list[tuple[list[str], str | None]] = []
    for index in range(shards):
        if index >= active:
            plan.append(([], None))
            continue
        files = sorted(parts[index] + ([_AUTHZ_MATRIX] if matrix else []))
        plan.append((files, f"{index}/{active}" if matrix else None))
    return plan


def _load_durations() -> dict[str, float]:
    try:
        return json.loads(_DURATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--budget-seconds", type=float, default=DEFAULT_BUDGET_SECONDS)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument(
        "--env-out",
        type=Path,
        help="plik (np. $GITHUB_ENV), do którego trafia AUTHZ_MATRIX_SLICE tej części",
    )
    parser.add_argument(
        "--guards", action="store_true", help="tylko strażnicy całego repo (_ALWAYS)"
    )
    args = parser.parse_args()
    if args.guards:
        for test in _ALWAYS:
            print(test)
        return
    if not 0 <= args.shard < args.shards:
        parser.error(f"--shard {args.shard} poza zakresem 0..{args.shards - 1}")
    durations = _load_durations()
    direct, indirect = select(sys.stdin.read().splitlines())
    kept, dropped = apply_budget(direct, indirect, args.budget_seconds, durations)
    plan = plan_shards(kept, durations, args.shards)
    mine, matrix_slice = plan[args.shard]
    for test in mine:
        print(test)
    if matrix_slice and args.env_out:
        with args.env_out.open("a", encoding="utf-8") as env:
            env.write(f"{_AUTHZ_SLICE_ENV}={matrix_slice}\n")
    active = sum(1 for files, _ in plan if files)
    print(
        f"Wybrano {len(kept)} plików testowych (~{estimate_seconds(kept, durations) / 60:.1f} min "
        f"razem, części: {active}); ta część: {len(mine)} plików "
        f"(~{_shard_estimate(mine, matrix_slice, durations) / 60:.1f} min); "
        f"poza budżetem {len(dropped)} — sprawdzi je kolejka merge'ów.",
        file=sys.stderr,
    )
    if matrix_slice:
        print(f"  macierz bramek tras: wycinek {matrix_slice}", file=sys.stderr)
    for test in dropped:
        print(f"  pominięty (budżet): {test}", file=sys.stderr)


def _shard_estimate(
    files: list[str], matrix_slice: str | None, durations: dict[str, float]
) -> float:
    if not matrix_slice:
        return estimate_seconds(files, durations)
    parts = int(matrix_slice.split("/")[1])
    full = durations.get(_AUTHZ_MATRIX, _fallback(durations))
    return estimate_seconds(files, durations) - full + full / parts


if __name__ == "__main__":
    main()
