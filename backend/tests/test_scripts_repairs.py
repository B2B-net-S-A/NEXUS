"""Naprawy z `scripts/repairs/` są do uruchomienia ręcznie i nie wracają na start."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[1]
REPAIRS = BACKEND / "scripts" / "repairs"
RUN_SCRIPTS = sorted(REPAIRS.glob("run_*.py"))


def test_there_are_repair_scripts() -> None:
    assert len(RUN_SCRIPTS) >= 36


@pytest.mark.parametrize("script", RUN_SCRIPTS, ids=lambda path: path.stem)
def test_script_imports_only_existing_repair_modules(script: Path) -> None:
    tree = ast.parse(script.read_text(encoding="utf-8"))
    targets = [
        node.module.rsplit(".", 1)[1]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        and node.module
        and node.module.startswith("scripts.repairs.")
    ]
    for target in targets:
        assert (REPAIRS / f"{target}.py").exists(), f"{script.name}: brak modułu {target}"


@pytest.mark.parametrize("script", RUN_SCRIPTS, ids=lambda path: path.stem)
def test_script_actually_runs_a_repair(script: Path) -> None:
    source = script.read_text(encoding="utf-8")
    assert "asyncio.run(" in source, f"{script.name}: brak wywołania naprawy"


def test_startup_does_not_run_anything_from_scripts_repairs() -> None:
    assert "scripts.repairs" not in (BACKEND / "entrypoint.sh").read_text(encoding="utf-8")
