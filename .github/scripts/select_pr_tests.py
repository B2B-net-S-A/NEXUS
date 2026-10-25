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
* testy skanujące drzewo (``rglob(``/``os.walk(``, bez bazy) → zawsze, wykrywane
  same (``tree_scanner_nodes``), bez dopisywania do listy.

Sito biegnie w ``SIEVE_SHARDS`` jobach (``--shards``/``--shard``): każdy liczy ten
sam wybór i bierze swoją część (podział LPT po czasie, jak shardy kolejki).
Macierz bramek tras (~150 s w sicie, jeden plik) dzieli się po trasach między
wszystkie aktywne części (``AUTHZ_MATRIX_SLICE``, ``--env-out``). Mały wybór
zajmuje tylko jedną część; pozostałe kończą się bez instalacji zależności.

``--guards`` wypisuje strażników ``_ALWAYS``, kontrakty tras
``_ROUTE_CONTRACTS`` i skanery drzewa — dla szybkiego kroku kolejki merge'ów w ``ci-gate.yml``
(bez bazy).

Wejście: lista zmienionych plików (ścieżki od korzenia repo) na stdin.
Wyjście: ścieżki testów od katalogu ``backend/``, po jednej w linii.
"""

from __future__ import annotations

import argparse
import ast
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
# modułu z nazwy. Bez bazy, ale najdłuższy plik sita: ~150 s na runnerze,
# w shardzie kolejki 185–390 s (tracer pokrycia + rozrzut runnerów), dlatego
# dzielony po trasach między części sita.
_AUTHZ_MATRIX = "tests/test_authz_guard_matrix.py"
_AUTHZ_GOLDEN_DIR = "tests/data/authz_golden/"
_AUTHZ_SLICE_ENV = "AUTHZ_MATRIX_SLICE"

# Kontrakty tras: każda trasa ma bramkę sekcji (albo wpis z powodem) i bramkę
# roli. Z tego samego powodu co macierz nie wymieniają routera z nazwy, więc
# biegną przy każdej zmianie ``app/``. 23.10.2026 #2611 zastąpił bramkę routera
# w ``api/pre_contracts.py`` własną zależnością: sito zielone, w kolejce
# czerwony strażnik sekcji i 7 PR-ów za nim wypadło. Bez bazy, < 1 s każdy.
_ROUTE_CONTRACTS = (
    "tests/test_section_ceiling_contract.py",
    "tests/test_route_authz_contract.py",
)

# Skanery drzewa wykrywane same: funkcja testowa, która (wprost albo przez
# pomocnika z tego samego pliku) woła ``rglob(``/``os.walk(``. 25.10.2026 #2649
# przeszedł sito z odczytem stawki poza listą strażnika
# (``test_rate_from_readers_guard``), a w kolejce padał w każdej grupie — 31 z 41
# plików skanujących nie było w ``_ALWAYS``. Bierzemy pojedyncze testy, nie
# pliki (w plikach siedzą też testy na bazie), i tylko te bez fixture'ów bazy,
# bo te same biegną w ``ci-gate.yml`` przed migracjami. 60 testów lokalnie
# 136 s (py3.12), z tego jeden 30 s — ten zostaje kolejce.
_SCAN_CALLS = ("rglob(", "os.walk(")
_NO_DB_FIXTURES = frozenset(
    {"monkeypatch", "tmp_path", "tmp_path_factory", "capsys", "caplog", "request"}
)
_QUEUE_ONLY_SCANNERS = frozenset(
    {
        # 30 s lokalnie (reszta ≤ 6 s).
        "tests/test_priority_work_writer_architecture.py"
        "::test_candidate_stage_update_delete_and_critical_fields_use_command_writer",
    }
)
# Wagi pojedynczego testu w szacunku sita (mapa czasów zna tylko pliki).
_SCANNER_NODE_SECONDS = 3.0

# Szacunek czasu sita = suma czasów plików z ``ci_test_durations.json`` (z
# fixture'ami bazy — mapa liczy odstępy między testami w logu) + narzut
# procesu pytest: kolekcja, import aplikacji i pierwszy test. Zmierzone
# 21.10.2026 na biegach sita: 36 s przy 34 plikach, 79–102 s przy 186–287.
#
# Mapa pochodzi z shardów kolejki, które biegną pod tracerem pokrycia
# (``--cov-branch``); sito biegnie bez niego. Mediana stosunku kolejka/sito
# na 337 plikach z biegów 21.10.2026: 1,25 (testy na bazie ~1,0–1,3×, czysty
# Python do ~2–2,8×, np. macierz bramek tras). Stąd jeden współczynnik.
_NO_COVERAGE_FACTOR = 0.8
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


def _parametrized(func: ast.FunctionDef) -> set[str]:
    names: set[str] = set()
    for deco in func.decorator_list:
        if (
            isinstance(deco, ast.Call)
            and "parametrize" in ast.unparse(deco.func)
            and deco.args
            and isinstance(deco.args[0], ast.Constant)
        ):
            names |= {n.strip() for n in str(deco.args[0].value).split(",")}
    return names


def _scanner_nodes_in(rel: str, text: str) -> list[str]:
    if not any(call in text for call in _SCAN_CALLS):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    lines = text.splitlines()

    def scans(node: ast.AST) -> bool:
        body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
        return any(call in body for call in _SCAN_CALLS)

    def calls(node: ast.AST) -> set[str]:
        return {
            c.func.id
            for c in ast.walk(node)
            if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
        }

    funcs = {
        n.name: n
        for n in tree.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    scanning = {name for name, f in funcs.items() if scans(f)}
    grew = True
    while grew:
        grew = False
        for name, f in funcs.items():
            if name not in scanning and calls(f) & scanning:
                scanning.add(name)
                grew = True
    nodes = []
    for name in sorted(scanning):
        func = funcs[name]
        if not name.startswith("test_") or not isinstance(func, ast.FunctionDef):
            continue
        params = {a.arg for a in func.args.args}
        if params <= _NO_DB_FIXTURES | _parametrized(func):
            nodes.append(f"{rel}::{name}")
    return nodes


def tree_scanner_nodes(tests: dict[str, str]) -> list[str]:
    """Testy skanujące drzewo, bez bazy i bez ``_QUEUE_ONLY_SCANNERS``."""
    return [
        node
        for rel, text in sorted(tests.items())
        for node in _scanner_nodes_in(rel, text)
        if node not in _QUEUE_ONLY_SCANNERS
    ]


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
            if rel.startswith("app/") and rel.endswith(".py"):
                direct.update(t for t in _ROUTE_CONTRACTS if t in tests)
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
    files = direct | indirect
    direct.update(n for n in tree_scanner_nodes(tests) if n.split("::")[0] not in files)
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
    """Mapa czasów kolejki przeliczona na sito (bez pomiaru pokrycia)."""
    try:
        raw = json.loads(_DURATIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    durations = {name: seconds * _NO_COVERAGE_FACTOR for name, seconds in raw.items()}
    durations.update(
        (node, _SCANNER_NODE_SECONDS) for node in tree_scanner_nodes(_test_files())
    )
    return durations


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
        "--guards",
        action="store_true",
        help="tylko strażnicy całego repo (_ALWAYS, _ROUTE_CONTRACTS, skanery drzewa)",
    )
    args = parser.parse_args()
    if args.guards:
        guards = _ALWAYS + _ROUTE_CONTRACTS
        for test in guards:
            print(test)
        for node in tree_scanner_nodes(_test_files()):
            if node.split("::")[0] not in guards:
                print(node)
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
