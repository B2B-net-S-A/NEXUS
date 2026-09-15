"""Kontrakty workflowów po audycie Codexa 14.09.2026 (QA-01, DEP-03, DEP-01).

Parsowane są PLIKI YAML, nie ich wykonanie (``act`` nie jest dostępny) —
test pilnuje, żeby konstrukcje, na których stoją poprawki, nie zniknęły
cichym refaktorem:

* QA-01 — każdy shard pytest pisze własny plik danych pokrycia i wysyła go
  jako artefakt (z ``include-hidden-files``, bo plik zaczyna się od kropki),
  a job ``backend-coverage-combine`` scala je i wysyła do Codecov WYŁĄCZNIE
  przy ustawionym tokenie (``env.CODECOV_TOKEN != ''``); od planu poprawy
  (15.09) mierzy też gałęzie i blokuje spadek poniżej baseline'u z repo;
* QA-05 — Trivy blokuje znaleziska HIGH/CRITICAL z poprawką, wyjątki z terminem;
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
    codecov = _step(steps, "Upload backend coverage to Codecov")
    assert "env.CODECOV_TOKEN != ''" in codecov["if"]
    frontend_codecov = _step(
        ci["jobs"]["frontend-lint-build"]["steps"],
        "Upload frontend coverage to Codecov",
    )
    assert "env.CODECOV_TOKEN != ''" in frontend_codecov["if"]


def test_backend_coverage_measures_branches_and_blocks_regressions() -> None:
    """Plan poprawy QA (15.09): pomiar gałęzi + bramka „bez spadku".

    Próg 80% zostaje raportowy, ale spadek poniżej baseline'u z repo i
    niekompletny zestaw shardów kończą job czerwienią, a wymagany kontekst
    „Backend (pytest)" czyta wynik tego joba.
    """
    ci = _load("ci.yml")
    pytest_run = _step(
        ci["jobs"]["backend-lint-test"]["steps"],
        "Pytest (unit + in-process integration)",
    )["run"]
    assert "--cov-branch" in pytest_run

    shards = ci["jobs"]["backend-lint-test"]["strategy"]["matrix"]["shard"]
    job = ci["jobs"]["backend-coverage-combine"]
    assert int(job["env"]["EXPECTED_SHARDS"]) == len(shards), (
        "EXPECTED_SHARDS musi odpowiadać matrixowi — inaczej bramka kompletności "
        "odrzuci każdy bieg albo przepuści niepełny."
    )
    combine = _step(job["steps"], "Combine shards + report")["run"]
    assert "coverage_gate.py" in combine and "coverage-baseline.json" in combine
    assert '"$EXPECTED_SHARDS"' in combine and "exit 1" in combine

    gate = ci["jobs"]["backend-pytest-gate"]
    assert "backend-coverage-combine" in gate["needs"]
    assert "needs.backend-coverage-combine.result" in gate["steps"][0]["run"]

    frontend_steps = ci["jobs"]["frontend-lint-build"]["steps"]
    artifact = _step(frontend_steps, "Upload frontend coverage (artifact)")
    assert artifact["with"]["path"] == "frontend/coverage/lcov.info"
    vitest_config = (_WORKFLOWS.parents[1] / "frontend" / "vitest.config.ts").read_text(
        encoding="utf-8"
    )
    assert "thresholds:" in vitest_config, "Progi Vitest są bramką frontendu."


def test_trivy_blocks_findings_and_exceptions_have_expiry() -> None:
    """QA-05: Trivy czerwony przy HIGH/CRITICAL z poprawką; wyjątki z terminem."""
    ci = _load("ci.yml")
    steps = ci["jobs"]["security-scan"]["steps"]
    scan = _step(steps, "Trivy filesystem scan (deps + Dockerfile misconfig)")
    assert scan["with"]["trivyignores"] == ".trivyignore"
    publish = _step(steps, "Publish Trivy findings")["run"]
    assert "(Total|Failures)" in publish, (
        "Licznik musi obejmować też błędną konfigurację."
    )
    assert "exit 1" in publish

    ignore = (_WORKFLOWS.parents[1] / ".trivyignore").read_text(encoding="utf-8")
    entries = [
        line
        for line in ignore.splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert entries, "Pusty .trivyignore nie potrzebuje kontraktu — usuń plik."
    for entry in entries:
        assert " exp:" in entry, f"Wyjątek bez terminu: {entry!r}"


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


# ── QA-02 / QA-03 ─────────────────────────────────────────────────────────


def test_e2e_stack_job_runs_stack_scenarios_and_fails_on_skips() -> None:
    """Plan poprawy QA (15.09): zapisujące E2E tylko na efemerycznym stacku."""
    e2e = _load("e2e.yml")
    stack = e2e["jobs"]["stack"]
    runs = "\n".join(str(step.get("run", "")) for step in stack["steps"])
    assert "docker-compose.e2e.yml" in runs
    assert "scripts/seed_e2e.py" in runs and "E2E_SEED_CONFIRM=nexus-e2e" in runs
    assert "--project=ci-chromium" in runs
    assert "r.skipped > 0" in runs, "Pominięty przypadek na stacku ma być czerwony."
    assert stack["env"]["E2E_REQUIRE_AUTH"] == "1"
    assert any(
        step.get("if") == "always()" and "down -v" in str(step.get("run", ""))
        for step in stack["steps"]
    ), "Stack musi być zatrzymany niezależnie od wyniku."

    prod = e2e["jobs"]["playwright"]
    assert "pull_request" in prod["if"], "Bieg produkcyjny nie może chodzić na PR-ach."
    prod_runs = "\n".join(str(step.get("run", "")) for step in prod["steps"])
    assert "--project=prod-smoke" in prod_runs
    assert "test:e2e" not in prod_runs, (
        "`npm run test:e2e` odpaliłby też scenariusze @stack."
    )


def test_playwright_projects_separate_stack_from_production() -> None:
    config = (_WORKFLOWS.parents[1] / "frontend" / "playwright.config.ts").read_text(
        encoding="utf-8"
    )
    assert 'name: "ci-chromium",\n      grep: /@stack/' in config
    assert 'name: "prod-smoke",\n      grepInvert: /@stack|@writes/' in config


def test_e2e_specs_have_no_weak_assertions_or_parked_cases() -> None:
    """Audyt QA 14.09: `< 500` przyjmowało 401/403/404/422, a `fixme`/`skip(true)`
    zawyżały licznik przypadków, których nikt nie wykonywał."""
    e2e_dir = _WORKFLOWS.parents[1] / "frontend" / "e2e"
    offenders: list[str] = []
    for spec in sorted(e2e_dir.rglob("*.ts")):
        text = spec.read_text(encoding="utf-8")
        for needle in ("toBeLessThan(500)", "test.fixme(", "test.skip(true"):
            if needle in text:
                offenders.append(f"{spec.name}: {needle}")
    assert offenders == []


def test_every_run_block_in_quality_workflows_is_valid_bash() -> None:
    """Niezbalansowany cudzysłów w komunikacie `::error::` wywalił job zbiorczy
    „Backend (pytest)" kodem 2 przy dwóch zielonych wejściach (PR planu poprawy
    QA, 15.09.2026). `bash -n` łapie to przed wypchnięciem."""
    import re
    import shutil
    import subprocess

    bash = shutil.which("bash")
    assert bash, "bash jest wymagany do kontroli składni workflowów"
    broken: list[str] = []
    for name in ("ci.yml", "e2e.yml"):
        for job_id, job in _load(name)["jobs"].items():
            for step in job.get("steps", []):
                script = step.get("run")
                if not script:
                    continue
                # Wyrażenia GitHuba nie są bashem — zastępujemy je słowem.
                script = re.sub(r"\$\{\{.*?\}\}", "EXPR", script)
                result = subprocess.run(
                    [bash, "-n"], input=script, capture_output=True, text=True
                )
                if result.returncode != 0:
                    broken.append(
                        f"{name}:{job_id}:{step.get('name')}: {result.stderr.strip()}"
                    )
    assert broken == []


def test_manifest_skip_switch_is_limited_to_the_e2e_stack() -> None:
    """Stack E2E wykazał, że backend nie startuje na pustej bazie (manifest
    portfela jest fail-closed). Przełącznik pominięcia istnieje tylko dla
    stacku testowego — w compose czytanych przez Coolify nie może się pojawić."""
    repo = _WORKFLOWS.parents[1]
    entrypoint = (repo / "backend" / "entrypoint.sh").read_text(encoding="utf-8")
    assert '"${CLIENT_PORTFOLIO_MANIFEST_SKIP:-0}" = "1"' in entrypoint

    stack = yaml.safe_load(
        (repo / "docker-compose.e2e.yml").read_text(encoding="utf-8")
    )
    assert (
        stack["services"]["backend"]["environment"]["CLIENT_PORTFOLIO_MANIFEST_SKIP"]
        == "1"
    )

    for name in (
        "docker-compose.yml",
        "docker-compose.prod.yml",
        "docker-compose.override.yml",
    ):
        path = repo / name
        if path.exists():
            assert "CLIENT_PORTFOLIO_MANIFEST_SKIP" not in path.read_text(
                encoding="utf-8"
            ), name
