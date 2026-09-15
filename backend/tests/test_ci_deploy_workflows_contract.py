"""Kontrakty workflowów po audycie Codexa 14.09.2026 (QA-01, DEP-03, DEP-01).

Parsowane są PLIKI YAML, nie ich wykonanie (``act`` nie jest dostępny) —
test pilnuje, żeby konstrukcje, na których stoją poprawki, nie zniknęły
cichym refaktorem:

* QA-01 — każdy shard pytest pisze własny plik danych pokrycia i wysyła go
  jako artefakt (z ``include-hidden-files``, bo plik zaczyna się od kropki),
  a job ``backend-coverage-combine`` scala je i wysyła do Codecov WYŁĄCZNIE
  przy ustawionym tokenie (``env.CODECOV_TOKEN != ''``);
* DEP-03 — smoke deployu ma krok porównujący ``version.json`` frontendu
  z wersją przyjętą przez smoke backendu (ACCEPTED_SHA);
* DEP-01 — deploy rusza tylko przy zielonej bramce HEAD maina (RELEASE_SHA),
  a smoke przyjmuje RELEASE_SHA albo potomka z ZIELONĄ bramką (ACCEPTED_SHA);
  podsumowanie wersji biegnie ``always()`` i nie zmienia wyniku joba.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_WORKFLOWS = Path(__file__).parents[2] / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(steps: list[dict], name: str) -> dict:
    for step in steps:
        if step.get("name") == name:
            return step
    raise AssertionError(
        f"Brak kroku {name!r}; kroki: {[s.get('name') for s in steps]}"
    )


# ── QA-01 ─────────────────────────────────────────────────────────────────


def test_each_pytest_shard_writes_its_own_coverage_data_file() -> None:
    ci = _load("ci.yml")
    steps = ci["jobs"]["backend-lint-test"]["steps"]
    pytest_step = _step(steps, "Pytest (unit + in-process integration)")
    assert "strategy.job-index" in pytest_step["env"]["COVERAGE_FILE"], (
        "COVERAGE_FILE musi być per shard — wspólna nazwa dałaby 4 pliki o tej "
        "samej nazwie i combine scaliłby tylko jeden."
    )
    upload = _step(steps, "Upload coverage data (shard artifact)")
    assert upload["uses"].startswith("actions/upload-artifact@")
    assert upload["with"]["include-hidden-files"] is True, (
        "Plik .coverage.shard-N zaczyna się od kropki — bez include-hidden-files "
        "artefakt jest pusty (upload-artifact ≥ 4.4 pomija pliki ukryte)."
    )
    assert upload["with"]["name"].startswith("backend-coverage-shard-")
    assert not any("codecov" in str(s.get("uses", "")) for s in steps), (
        "Upload do Codecov per shard zastąpiono jednym po scaleniu."
    )


def test_combine_job_merges_shards_and_gates_codecov_on_token() -> None:
    ci = _load("ci.yml")
    job = ci["jobs"]["backend-coverage-combine"]
    assert job["needs"] == "backend-lint-test"
    assert job["env"]["CODECOV_TOKEN"] == "${{ secrets.CODECOV_TOKEN }}"
    steps = job["steps"]
    download = _step(steps, "Download shard coverage data")
    assert download["with"]["pattern"] == "backend-coverage-shard-*"
    assert download["with"]["merge-multiple"] is True
    combine = _step(steps, "Combine shards + report")
    assert "coverage combine" in combine["run"]
    assert "coverage xml" in combine["run"]
    assert "::warning::" in combine["run"] and "exit 1" not in combine["run"], (
        "Próg pokrycia jest raportowy: ostrzeżenie, nigdy czerwony job."
    )
    codecov = _step(steps, "Upload backend coverage to Codecov")
    assert "env.CODECOV_TOKEN != ''" in codecov["if"]
    frontend_codecov = _step(
        ci["jobs"]["frontend-lint-build"]["steps"],
        "Upload frontend coverage to Codecov",
    )
    assert "env.CODECOV_TOKEN != ''" in frontend_codecov["if"]


# ── DEP-03 / DEP-01 ───────────────────────────────────────────────────────


def test_deploy_smoke_asserts_frontend_version_json() -> None:
    deploy = _load("deploy.yml")
    steps = deploy["jobs"]["deploy"]["steps"]
    names = [s.get("name") for s in steps]
    reach = names.index("Frontend osiągalny (aplikacja użytkownika)")
    version = names.index("Frontend serwuje oczekiwaną wersję (version.json)")
    assert version == reach + 1, "Wersja frontendu sprawdzana zaraz po osiągalności."
    step = steps[version]
    assert step["id"] == "frontend_version"
    run = step["run"]
    assert "/version.json" in run
    assert '[ "$sha" = "$ACCEPTED_SHA" ]' in run
    assert '"$sha" != "unknown"' in run, (
        "Build bez GIT_SHA nie może przejść jako „jakaś wersja”."
    )
    assert run.rstrip().endswith("exit 1"), "Wyczerpanie ponowień = czerwony deploy."


def test_deploy_requires_green_head_and_green_accepted_version() -> None:
    deploy = _load("deploy.yml")
    assert deploy["permissions"]["actions"] == "read"
    select = deploy["jobs"]["select"]
    assert "workflow_run.conclusion == 'success'" in select["if"]
    select_step = _step(select["steps"], "Wybierz wydanie")
    assert "select_release_sha.py select" in select_step["run"]
    assert "--target-unverified" in select_step["env"]["TARGET_UNVERIFIED"]
    job = deploy["jobs"]["deploy"]
    assert job["needs"] == "select"
    assert job["if"] == "${{ needs.select.outputs.defer == 'false' }}"
    assert job["env"]["RELEASE_SHA"] == "${{ needs.select.outputs.release_sha }}"
    steps = job["steps"]
    health = _step(steps, "Healthcheck (standard shape + version match)")["run"]
    assert "select_release_sha.py accept" in health
    assert '[ "$verdict" = "1" ]' in health, "Potomek z czerwoną bramką = twardy błąd."
    raw = (_WORKFLOWS / "deploy.yml").read_text(encoding="utf-8")
    assert "/compare/" not in raw, "Pokrewieństwo liczy wyłącznie skrypt z bramką."
    deep = _step(steps, "Deep healthcheck (core modules not 503)")["run"]
    assert '[ "$version" = "$ACCEPTED_SHA" ]' in deep


def test_deploy_version_summary_runs_always() -> None:
    deploy = _load("deploy.yml")
    steps = deploy["jobs"]["deploy"]["steps"]
    summary = _step(steps, "Podsumowanie wersji (wydanie vs produkcja)")
    assert summary["if"] == "${{ always() }}"
    assert "deploy_version_summary.py" in summary["run"]
    assert '--accepted "${ACCEPTED_SHA:-}"' in summary["run"]
    assert "GITHUB_STEP_SUMMARY" in summary["run"]
    assert summary["run"].rstrip().endswith("exit 0"), (
        "Podsumowanie nigdy nie zmienia wyniku joba."
    )
    checkout = _step(steps, "Checkout (tylko .github/scripts)")
    assert checkout["with"]["sparse-checkout"] == ".github/scripts"
    precheck = _step(steps, "Skip if release already live (burst coalescing)")
    assert precheck["if"] == "${{ github.event_name != 'workflow_dispatch' }}"
    assert '[ "$version" = "$RELEASE_SHA" ]' in precheck["run"]
    assert precheck["run"].count('echo "skip=true" >> "$GITHUB_OUTPUT"') == 1
