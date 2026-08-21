"""Bramka sekretów nie może być ślepa na PLIKI ŚLEDZONE PRZEZ GITA.

``.gitleaks.toml`` → ``[allowlist].paths`` nie wycisza pojedynczego trafienia:
wyłącza skaner na CAŁYM pliku, na zawsze, także dla reguł, które dopiero
powstaną. Ten sam plik ostrzega przed tą techniką własnym komentarzem — to
właśnie ona pozwoliła przeleżeć w repo działającemu hasłu administratora.

Regresja jest CICHA: dopisanie ścieżki nie psuje ani jednego testu i sprawia,
że CI Gate robi się zielone. Dokładnie dlatego potrzebny jest test, który
czyta listę i porównuje ją ze stanem repozytorium, zamiast ufać komentarzowi.

Test jest wykonujący: dopasowuje każdy wzorzec do RZECZYWISTEJ listy
``git ls-files``, więc złapie też wpis, który dziś nie obejmuje niczego,
a jutro obejmie nowy plik.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CONFIG = REPO / ".gitleaks.toml"

# Zbiór jest PUSTY i taki ma zostać.
#
# Lista wyjątków eroduje: każdy kolejny wpis wygląda na tak samo niewinny jak
# poprzedni, a po kilku nikt już nie pamięta, czy plik trafił tu, bo naprawdę
# musiał, czy dlatego, że tak było szybciej. Po audycie #211 żaden śledzony
# plik nie wymaga wyłączenia — wszystkie placeholdery są allowlistowane po
# WARTOŚCI. Dopisanie czegokolwiek tutaj to świadoma decyzja o oślepieniu
# bramki na cały plik i wymaga uzasadnienia w ``.gitleaks.toml``.
ALLOWED_TRACKED_BLINDSPOTS: set[str] = set()


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(REPO), "ls-files"],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.splitlines()


def _offending_patterns(
    patterns: list[str], tracked: list[str]
) -> dict[str, list[str]]:
    """Czyste jądro reguły — wydzielone, żeby dało się je sprawdzić BEZ gita.

    Sam test na żywym repo potrafi się pominąć (worktree bez katalogu ``.git``
    w zasięgu), a pominięty test niczego nie broni. Ta funkcja jest zawsze
    wykonywana na syntetycznej liście plików niżej.
    """
    offenders: dict[str, list[str]] = {}
    for pattern in patterns:
        rx = re.compile(pattern)
        hits = [
            f for f in tracked if rx.search(f) and f not in ALLOWED_TRACKED_BLINDSPOTS
        ]
        if hits:
            offenders[pattern] = sorted(hits)[:5]
    return offenders


def _global_allowlist_paths() -> list[str]:
    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    return list(data["allowlist"]["paths"])


def test_config_exists() -> None:
    """Znikniecie konfigu to nie 'skip' — bramka deployu przestaje istnieć."""
    assert CONFIG.is_file(), f"brak {CONFIG}"


def test_no_path_entry_blinds_the_scanner_to_a_tracked_file() -> None:
    try:
        tracked = _tracked_files()
    except (subprocess.CalledProcessError, FileNotFoundError):  # pragma: no cover
        pytest.skip("brak gita w środowisku testowym")

    offenders = _offending_patterns(_global_allowlist_paths(), tracked)

    assert not offenders, (
        "wpisy ścieżkowe w .gitleaks.toml oślepiają skaner na pliki ŚLEDZONE "
        f"przez gita: {offenders}. Allowlistuj po WARTOŚCI "
        "([allowlist].regexes albo blok per-reguła), nie po ścieżce."
    )


def test_workflow_files_are_never_path_allowlisted() -> None:
    """Osobno i dosłownie, bo tu ryzyko jest największe.

    ``backup-drill.yml`` to jedyne miejsce w repo dotykające PRYWATNEJ połowy
    klucza age (odszyfrowuje cały archiwalny backup kandydatów) oraz kluczy
    Backblaze B2. Ta asercja przeżyje nawet wtedy, gdyby plik chwilowo zniknął
    z ``git ls-files`` i test wyżej nie miał czego dopasować.
    """
    bad = [p for p in _global_allowlist_paths() if "workflows" in p]
    assert not bad, f"workflow nie może być allowlistowany po ścieżce: {bad}"


def test_ci_test_dsns_are_allowlisted_by_value_in_the_per_rule_block() -> None:
    """Blok per-reguła NADPISUJE globalny — oba DSN-y CI muszą być w nim.

    To jest zależność, która sprawiała, że wpisów ścieżkowych „nie dało się"
    usunąć: globalne ``nexus:nexus-ci-password`` / ``drill:drill-password``
    dla reguły ``hardcoded-db-password`` nie obowiązują.
    """
    data = tomllib.loads(CONFIG.read_text(encoding="utf-8"))
    rule = next(r for r in data["rules"] if r["id"] == "hardcoded-db-password")
    joined = "\n".join(rule["allowlist"]["regexes"])
    assert "nexus:nexus-ci-password" in joined
    assert "drill:drill-password" in joined


def test_the_guard_itself_catches_a_reintroduced_path_entry() -> None:
    """Bez tego test wyżej mógłby przechodzić dlatego, że nic nie sprawdza.

    Odtwarza dokładnie stan sprzed poprawki #211: cztery szerokie wpisy
    ścieżkowe i lista plików, na które oślepiały skaner.
    """
    tracked = [
        ".github/workflows/ci.yml",
        ".github/workflows/backup-drill.yml",
        "frontend/package-lock.json",
        ".claude/ops.yaml",
        ".claude/commands/ops-db-query.md",
        "backend/app/main.py",
    ]
    reintroduced = [
        r"\.github/workflows/ci\.yml",
        r"\.github/workflows/backup-drill\.yml",
        r"frontend/package-lock\.json",
        r"\.claude/",
    ]

    offenders = _offending_patterns(reintroduced, tracked)
    assert set(offenders) == set(reintroduced), (
        "strażnik przestał wykrywać wpisy ścieżkowe, które kiedyś tu były"
    )

    # A bieżąca konfiguracja na tej samej liście plików jest już czysta.
    assert _offending_patterns(_global_allowlist_paths(), tracked) == {}
