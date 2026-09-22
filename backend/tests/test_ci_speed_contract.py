"""Kontrakty przyspieszenia CI i deployu (22.09.2026).

Zmierzone przed zmianą: jedna poprawka czekała ~20 min na CI PR-a, potem ~20 min
na to samo CI w kolejce merge'ów, potem ~9 min na deploy. Każda z konstrukcji
poniżej odpowiada za część tego czasu i łatwo ją cofnąć „przy okazji”.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

_REPO = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(f"Brak kroku {name!r}")


def _selector():
    path = _REPO / ".github" / "scripts" / "select_pr_tests.py"
    spec = importlib.util.spec_from_file_location("select_pr_tests", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_full_pytest_runs_in_the_queue_not_on_every_pr() -> None:
    jobs = _load("ci.yml")["jobs"]
    assert jobs["backend-lint-test"]["if"] == (
        "${{ github.event_name != 'pull_request' }}"
    )
    assert (
        "github.event_name != 'pull_request'" in jobs["backend-coverage-combine"]["if"]
    )
    assert (
        jobs["backend-pr-tests"]["if"] == "${{ github.event_name == 'pull_request' }}"
    )


def test_required_backend_context_is_decided_by_the_sieve_on_prs() -> None:
    gate = _load("ci.yml")["jobs"]["backend-pytest-gate"]
    assert gate["name"] == "Backend (pytest)", (
        "Nazwa jest wymaganym kontekstem rulesetu."
    )
    assert gate["if"] == "${{ always() }}"
    assert "backend-pr-tests" in gate["needs"]
    run = gate["steps"][0]["run"]
    assert "needs.backend-pr-tests.result" in run
    assert '[ "$sieve" != "success" ]' in run, (
        "Czerwone sito musi dawać czerwony kontekst."
    )


def test_frontend_heavy_steps_run_in_the_queue_and_prs_get_changed_tests() -> None:
    steps = _load("ci.yml")["jobs"]["frontend-lint-build"]["steps"]
    for name in ("Vitest with coverage", "Build"):
        assert "github.event_name != 'pull_request'" in _step(steps, name)["if"]
    pr = _step(steps, "Vitest (testy dotknięte zmianą)")
    assert "github.event_name == 'pull_request'" in pr["if"]
    assert "--changed" in pr["run"] and "--passWithNoTests" in pr["run"]


def test_test_postgres_skips_disk_flushes_in_both_backend_jobs() -> None:
    jobs = _load("ci.yml")["jobs"]
    for job in ("backend-lint-test", "backend-pr-tests"):
        steps = jobs[job]["steps"]
        names = [s.get("name") for s in steps]
        fast = names.index("Szybszy Postgres (bez fsync — tylko CI)")
        assert fast < names.index("Apply migrations")
        assert "fsync = off" in steps[fast]["run"]


def test_flaky_tests_are_retried_once_and_reported() -> None:
    jobs = _load("ci.yml")["jobs"]
    shard_steps = jobs["backend-lint-test"]["steps"]
    pytest_run = _step(shard_steps, "Pytest (unit + in-process integration)")["run"]
    assert "--reruns 1" in pytest_run and "tee pytest-output.txt" in pytest_run
    report = _step(shard_steps, "Testy powtórzone (kapryśne)")
    assert "GITHUB_STEP_SUMMARY" in report["run"]
    requirements = (_REPO / "backend" / "requirements-testing.txt").read_text("utf-8")
    assert "pytest-rerunfailures==" in requirements


def test_deploys_are_batched_but_manual_deploy_does_not_wait() -> None:
    select = _load("deploy.yml")["jobs"]["select"]
    wait = _step(select["steps"], "Poczekaj na ciszę na mainie (grupowanie deployów)")
    assert wait["if"] == "${{ github.event_name != 'workflow_dispatch' }}"
    assert "DEPLOY_QUIET_SECONDS" in wait["env"]["QUIET"]
    assert "900" in wait["run"], (
        "Ciągły strumień merge'ów nie może blokować deployu bez końca."
    )
    assert "ci-gate.yml/runs?branch=main&event=push" in wait["run"], (
        "Ciszę liczymy od pusha na maina (start „CI Gate”), nie od daty commita — "
        "kolejka merge'ów stempluje commit chwilą dodania do kolejki."
    )
    assert "commits/main" not in wait["run"]
    names = [s.get("name") for s in select["steps"]]
    assert names.index(wait["name"]) < names.index("Wybierz wydanie"), (
        "Wybór wydania po ciszy — inaczej deploy bierze HEAD sprzed serii."
    )


def test_selector_changed_test_file_is_always_selected() -> None:
    sel = _selector()
    direct, _ = sel.select(["backend/tests/test_ci_speed_contract.py"])
    assert "tests/test_ci_speed_contract.py" in direct


def test_selector_hub_modules_do_not_select_half_the_suite() -> None:
    sel = _selector()
    direct, indirect = sel.select(["backend/app/core/config.py"])
    assert not indirect, "config.py importuje prawie każdy test — to zadanie kolejki."
    assert all(
        Path(t).name == "test_config.py" or Path(t).name.startswith("test_config_")
        for t in direct
    )


def test_selector_finds_tests_that_import_a_changed_module() -> None:
    sel = _selector()
    direct, indirect = sel.select(["backend/app/services/order_mail_ingest.py"])
    assert "tests/test_order_mail_ingest.py" in direct, "Test o nazwie modułu."
    assert "tests/test_nordea_pdf_policy.py" in indirect, "Test importujący moduł."


def test_selector_budget_keeps_direct_and_drops_slowest_indirect() -> None:
    sel = _selector()
    durations = {"a": 100.0, "b": 10.0, "c": 50.0, "d": 200.0}
    kept, dropped = sel.apply_budget({"a"}, {"b", "c", "d"}, 170.0, durations)
    assert kept == ["a", "b", "c"]
    assert dropped == ["d"]
