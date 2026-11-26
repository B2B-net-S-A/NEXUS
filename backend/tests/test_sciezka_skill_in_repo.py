"""Skill ``/sciezka`` jest w repo, a ``.gitignore`` go nie połyka.

``CLAUDE.md``, reguła ścieżki, ``sciezki/mapa-rol.json`` i bramka
``sciezka-stagingu-gate.js`` odsyłają do ``.claude/skills/sciezka/``. Do
26.11.2026 ``.gitignore`` ignorował całe ``.claude/``, więc PR-y #4034 i #4042
opisywały zmiany w skillu, ale jego pliki nie weszły do commitów: sesja
w nowym worktree czytała „uruchom /sciezka” i nie miała czego uruchomić.

Reszta ``.claude/`` (worktree, ``settings.local.json``) zostaje ignorowana.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.static

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / ".claude" / "skills" / "sciezka" / "SKILL.md"
ROLE_MAP = REPO / "docs" / "claude" / "podstawy" / "sciezki" / "mapa-rol.json"


def _is_ignored(path: str) -> bool:
    """Werdykt samych reguł ignorowania (``--no-index``: także dla śledzonych)."""
    command = ["git", "-C", str(REPO), "check-ignore", "--no-index", "--quiet", path]
    try:
        result = subprocess.run(command, capture_output=True)
    except FileNotFoundError:  # pragma: no cover
        pytest.skip("brak gita w środowisku testowym")
    if result.returncode not in (0, 1):  # pragma: no cover
        pytest.skip("katalog testów nie leży w repozytorium gita")
    return result.returncode == 0


def test_skill_and_every_scenario_from_role_map_are_in_repo() -> None:
    areas = json.loads(ROLE_MAP.read_text(encoding="utf-8"))["obszary"]
    wanted = [SKILL, *(REPO / area["scenariusz"] for area in areas.values())]

    missing = [str(path.relative_to(REPO)) for path in wanted if not path.is_file()]

    assert not missing, (
        f"Brak w repo plików, do których odsyłają mapa ról i bramka ścieżki: {missing}. "
        "Dodaj je i sprawdź, że .gitignore ich nie ignoruje."
    )


@pytest.mark.parametrize(
    "path",
    [
        ".claude/skills/sciezka/SKILL.md",
        ".claude/skills/sciezka/scenariusze/nowy-obszar.md",
    ],
)
def test_gitignore_lets_repo_skills_in(path: str) -> None:
    assert not _is_ignored(path), (
        f".gitignore ignoruje {path}: nowy plik skilla nie wejdzie do commita."
    )


@pytest.mark.parametrize(
    "path",
    [
        ".claude/worktrees/inna-sesja/README.md",
        ".claude/settings.local.json",
        "frontend/.claude/settings.local.json",
    ],
)
def test_gitignore_keeps_local_claude_files_out(path: str) -> None:
    assert _is_ignored(path), f".gitignore przestał ignorować {path}."
