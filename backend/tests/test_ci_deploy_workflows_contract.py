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


def _triggers(workflow: dict) -> dict:
    """Blok ``on:`` — PyYAML zamienia gołe ``on`` na ``True`` (YAML 1.1)."""
    triggers = workflow.get("on", workflow.get(True))
    assert isinstance(triggers, dict), "Workflow bez czytelnego bloku on:"
    return triggers


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
        ci["jobs"]["frontend-vitest"]["steps"],
        "Upload frontend coverage to Codecov",
    )
    assert "env.CODECOV_TOKEN != ''" in frontend_codecov["if"]


def test_backend_coverage_measures_branches_and_blocks_regressions() -> None:
    """Plan poprawy QA (15.09): pomiar gałęzi + bramka „bez spadku”.

    Próg 80% zostaje raportowy, ale spadek poniżej baseline'u z repo i
    niekompletny zestaw shardów kończą job czerwienią, a wymagany kontekst
    „Backend (pytest)” czyta wynik tego joba.
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

    frontend_steps = ci["jobs"]["frontend-vitest"]["steps"]
    assert "npm run test:coverage" in _step(frontend_steps, "Vitest with coverage")["run"]
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


# ── F03: pomiar przerwy (plan skracania przerwy, Etap 0) ──────────────────


def test_downtime_report_splits_targets_and_reads_postgres_start() -> None:
    deploy = _load("deploy.yml")
    steps = deploy["jobs"]["deploy"]["steps"]
    names = [s.get("name") for s in steps]
    probe = _step(steps, "Start user-facing downtime probe")
    assert names.index("Start user-facing downtime probe") < names.index(
        "Trigger deployment"
    ), "Sonda i odczyt startu Postgresa muszą być PRZED webhookiem."
    assert "/api/health/deep" in probe["run"] and "postgres_started_at" in probe["run"]
    assert "pg_before" in probe["run"]

    report = _step(steps, "Report user-facing downtime")
    assert (
        report["if"] == "${{ always() && steps.downtime_meter.outcome == 'success' }}"
    )
    run = report["run"]
    assert "deploy_downtime_report.py" in run
    assert "--postgres-before" in run and "--postgres-after" in run
    assert "GITHUB_STEP_SUMMARY" in run
    assert run.rstrip().endswith("exit 0"), "Pomiar nigdy nie zmienia wyniku deployu."
    assert names[-1] == "Report user-facing downtime", (
        "Raport zatrzymuje sondę — musi być ostatnim krokiem joba."
    )


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
    # Bieg produkcyjny nie może chodzić w przebiegu, który weryfikuje kod PRZED
    # merge'em. Do 2026-09-20 był to `pull_request`; od przeniesienia stacku do
    # kolejki merge'ów (cięcie kosztów Actions) jest to `merge_group`.
    pre_merge_event = next(
        event for event in ("merge_group", "pull_request") if event in (_triggers(e2e))
    )
    assert pre_merge_event in prod["if"], (
        "Bieg produkcyjny nie może chodzić w przebiegu weryfikującym kod przed "
        f"merge'em (zdarzenie {pre_merge_event!r})."
    )
    prod_runs = "\n".join(str(step.get("run", "")) for step in prod["steps"])
    assert "--project=prod-smoke" in prod_runs
    assert "test:e2e" not in prod_runs, (
        "`npm run test:e2e` odpaliłby też scenariusze @stack."
    )


# ── Koszt Actions (2026-09-20) ─────────────────────────────────────────────
#
# Pula 50 000 min/mc organizacji wyszła we wrześniu (rachunek: 47 273 min,
# rabat $0.00), a 99,3% tego to NEXUS. Poniższe testy pilnują trzech cięć,
# które łatwo cofnąć „przy okazji” refaktoru — każde z nich ma policzoną cenę
# w komentarzu przy samym workflow.


def test_ci_does_not_repeat_itself_on_push_to_main() -> None:
    """Ten sam commit testowany 3× (PR → kolejka → main) kosztował 18% rachunku.

    Kolejka merge'ów uruchamia CI na DOKŁADNIE tym drzewie, które ląduje na
    mainie, więc przebieg na `push` był trzecim wykonaniem tego samego kodu.
    """
    ci = _triggers(_load("ci.yml"))
    assert "push" not in ci, (
        "CI wróciło na `push: main` — to trzeci przebieg tego samego drzewa. "
        "Jeśli kolejka merge'ów została WYŁĄCZONA, przywrócenie jest słuszne: "
        "usuń wtedy także ten test i opisz decyzję w nagłówku ci.yml."
    )
    assert {"pull_request", "merge_group"} <= set(ci), (
        "CI musi biec na PR-ze (bramka przed merge'em) i w kolejce merge'ów "
        "(walidacja scalonego drzewa) — inaczej nic nie sprawdza kodu."
    )
    gate = _triggers(_load("ci-gate.yml"))
    assert "push" in gate, (
        "Bramką deployu jest „CI Gate” na push do maina (patrz deploy.yml) — "
        "bez niej deploy nigdy nie wystartuje."
    )


def test_frontend_required_context_always_reports_even_when_skipped() -> None:
    """Oszczędność nie może opierać się na tym, że `skipped` liczy się za sukces.

    „Frontend (typecheck + build)” jest wymaganym kontekstem rulesetu, a kolejka
    merge'ów ma `ALLGREEN`. Job więc ZAWSZE się zgłasza; pominięte są tylko jego
    drogie kroki, gdy PR nie dotyka frontendu (25% PR-ów, ~16 z 17 min).
    """
    job = _load("ci.yml")["jobs"]["frontend-lint-build"]
    assert "if" not in job, (
        "Warunek na POZIOMIE joba zamieniłby wymagany kontekst w `skipped` — "
        "to zachowanie GitHuba, nie nasza umowa, i jego zmiana zaklinowałaby "
        "kolejkę merge'ów bez komunikatu."
    )
    scope = _step(job["steps"], "Czy ten PR dotyka frontendu?")
    assert scope["id"] == "scope"
    body = scope["run"]
    # Fail-safe: każda gałąź niepewności musi kończyć się pełnym przebiegiem.
    assert body.count('echo "run=true"') >= 3, (
        "Brak listy plików, puste API albo inne zdarzenie niż pull_request MUSZĄ "
        "dawać pełny przebieg — pominięcie weryfikacji jest droższe niż 17 min."
    )
    assert "grep -rhoE" in body and "backend/" in body, (
        "Lustra backendu czytane przez testy frontendu wyliczamy Z REPO; lista "
        "wpisana w YAML zgniłaby cicho przy pierwszym nowym lustrze."
    )
    expensive = ("ESLint", "Type check", "Build", "npm ci")
    for name in expensive:
        step = _step(job["steps"], name)
        assert "steps.scope.outputs.run == 'true'" in str(step.get("if", "")), (
            f"Krok {name!r} nie jest podpięty pod filtr — płacimy za niego na "
            "każdym PR-ze, także takim, który nie tyka frontendu."
        )


def test_e2e_stack_verifies_the_merge_queue_not_every_pr_push() -> None:
    """226 przebiegów na PR-ach, 3 czerwone, 0 bramek: 1 506 min za sygnał.

    W kolejce ten sam sygnał BLOKUJE wejście na main, czyli po raz pierwszy coś
    znaczy. `pull_request` wraca w dniu, w którym „E2E stack (ci-chromium)”
    zostanie wymaganym kontekstem rulesetu.
    """
    triggers = _triggers(_load("e2e.yml"))
    assert "merge_group" in triggers
    assert "pull_request" not in triggers, (
        "E2E na każdym PR-ze nie bramkuje niczego (nie jest wymaganym "
        "kontekstem), a kosztowało ~9% rachunku za Actions."
    )
    assert "schedule" in triggers and "workflow_run" in triggers, (
        "Nocny stack i smoke po deployu zostają — to inne sygnały niż pre-merge."
    )


def test_the_dead_claude_review_workflow_stays_deleted() -> None:
    """174 przebiegi w 5 dni, wszystkie `skipped`: `CLAUDE_ENABLED=false`.

    Zero minut, ale też zero wartości — i zakładka Actions, w której nie da się
    odróżnić „nie było uwag” od „recenzji nie było”.
    """
    assert not (_WORKFLOWS / "claude-review.yml").exists(), (
        "Przywrócenie ma sens WYŁĄCZNIE razem z żywym tokenem i "
        "CLAUDE_ENABLED=true — inaczej wraca pusty szum."
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
    „Backend (pytest)” kodem 2 przy dwóch zielonych wejściach (PR planu poprawy
    QA, 15.09.2026). `bash -n` łapie to przed wypchnięciem."""
    import re
    import shutil
    import subprocess

    bash = shutil.which("bash")
    assert bash, "bash jest wymagany do kontroli składni workflowów"
    broken: list[str] = []
    # Od audytu 22.09.2026 (runda 2): WSZYSTKIE workflowy — alarmy i bramki
    # deployu siedzą też w deploy.yml, ci-gate.yml i workflowach monitoringu.
    for name in sorted(path.name for path in _WORKFLOWS.glob("*.yml")):
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


# ── Audyt 22.09.2026, runda 2 (OPS-N01..N08, REC-03, PROD-04) ─────────────


def test_e2e_stack_does_not_run_after_deploy() -> None:
    """OPS-N02: stack buduje się ze źródeł, nie z produkcji — bieg po Deploy
    powtarzał kolejkę merge'ów (757 min w 2 dni) i nie mówił nic o prod."""
    stack = _load("e2e.yml")["jobs"]["stack"]
    assert stack["if"] == "${{ github.event_name != 'workflow_run' }}"
    prod = _load("e2e.yml")["jobs"]["playwright"]
    assert "workflow_run" in prod["if"], "Po deployu biega `prod-smoke`."


def test_ci_gate_frontend_typecheck_skips_steps_not_the_job_on_prs() -> None:
    """OPS-N01: „Frontend (typecheck)” jest wymaganym kontekstem — job ZAWSZE
    się zgłasza; na PR-ze typy sprawdza „Frontend (typecheck + build)”."""
    job = _load("ci-gate.yml")["jobs"]["frontend-fast"]
    assert job["name"] == "Frontend (typecheck)"
    assert "if" not in job, "`if` na jobie = `skipped` wymaganego kontekstu."
    skip = "github.event_name != 'pull_request'"
    for name in ("Install dependencies", "Type check"):
        assert skip in _step(job["steps"], name)["if"]
    checkout = next(s for s in job["steps"] if "actions/checkout" in s.get("uses", ""))
    assert skip in checkout["if"]
    notice = _step(job["steps"], "Typy PR-a sprawdza CI")
    assert notice["working-directory"] == ".", "Bez checkoutu nie ma katalogu frontend."
    # Typy PR-a naprawdę sprawdza CI — inaczej pominięcie byłoby dziurą.
    jobs = _load("ci.yml")["jobs"]
    assert jobs["frontend-gate"]["name"] == "Frontend (typecheck + build)"
    assert "frontend-lint-build" in jobs["frontend-gate"]["needs"]
    _step(jobs["frontend-lint-build"]["steps"], "Type check")


def _run_step_script(script: str, env: dict[str, str], files: list[str]) -> str:
    """Wykonuje blok `run:` z atrapą `gh` zwracającą listę plików."""
    import os
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        gh = Path(tmp) / "gh"
        gh.write_text("#!/bin/bash\nprintf '%s\\n' $FAKE_FILES\n", encoding="utf-8")
        gh.chmod(0o755)
        out = Path(tmp) / "out"
        out.write_text("", encoding="utf-8")
        subprocess.run(
            ["bash", "-c", script],
            env={
                **os.environ,
                **env,
                "PATH": f"{tmp}:{os.environ['PATH']}",
                "GITHUB_OUTPUT": str(out),
                "FAKE_FILES": " ".join(files),
            },
            capture_output=True,
            text=True,
            check=False,
        )
        return out.read_text(encoding="utf-8")


def test_trivy_runs_only_when_dependencies_or_dockerfiles_change() -> None:
    """OPS-N01: skan zależności na PR-ze bez zmian w zależnościach powtarza
    wynik poprzedniego. Job nie jest wymaganym kontekstem, ale i tak się
    zgłasza — pomijane są kroki; każda niepewność = pełny skan."""
    job = _load("ci.yml")["jobs"]["security-scan"]
    assert "if" not in job
    scope = _step(job["steps"], "Czy zmieniły się zależności albo Dockerfile?")
    for step in job["steps"][1:]:
        assert "steps.scope.outputs.run == 'true'" in str(step.get("if")), step
    env = {
        "EVENT": "pull_request",
        "REPO": "o/r",
        "PR_NUMBER": "1",
        "BASE_SHA": "",
        "HEAD_SHA": "",
    }
    cases = {
        ("backend/app/main.py", "frontend/src/app/page.tsx"): "run=false",
        ("backend/requirements.txt",): "run=true",
        ("frontend/Dockerfile",): "run=true",
        ("frontend/package-lock.json",): "run=true",
        (".trivyignore",): "run=true",
        (".github/workflows/ci.yml",): "run=true",
        (): "run=true",  # pusta lista = niepewność = pełny skan
    }
    for files, expected in cases.items():
        assert expected in _run_step_script(scope["run"], env, list(files)), files
    dispatch = {**env, "EVENT": "workflow_dispatch"}
    assert "run=true" in _run_step_script(scope["run"], dispatch, [])


def test_set_env_does_not_bypass_the_deploy_gates() -> None:
    """OPS-N03: `redeploy=true` wołało webhook Coolify wprost — budowa HEAD-a
    z pominięciem DEP-01, smoke i kontroli migracji. Teraz domyślnie brak
    redeployu, a redeploy idzie przez workflow Deploy."""
    wf = _load("coolify-set-env.yml")
    inputs = _triggers(wf)["workflow_dispatch"]["inputs"]
    assert inputs["redeploy"]["default"] == "false"
    raw = (_WORKFLOWS / "coolify-set-env.yml").read_text(encoding="utf-8")
    assert "/api/v1/deploy" not in raw, "Webhook Coolify omija bramki deployu."
    job = wf["jobs"]["set-env"]
    assert job["permissions"]["actions"] == "write"
    deploy_step = _step(job["steps"], "Wdróż przez workflow Deploy")
    assert deploy_step["if"] == "${{ inputs.redeploy == 'true' }}"
    assert "gh workflow run deploy.yml" in deploy_step["run"]
    assert "--ref main" in deploy_step["run"] and "force_rebuild" in deploy_step["run"]

    deploy = _load("deploy.yml")
    force = _triggers(deploy)["workflow_dispatch"]["inputs"]["force_rebuild"]
    assert force["type"] == "boolean" and force["default"] is False
    trigger = _step(deploy["jobs"]["deploy"]["steps"], "Trigger deployment")
    assert "force=$FORCE_REBUILD" in trigger["run"]
    assert "workflow_dispatch" in trigger["env"]["FORCE_REBUILD"], (
        "Automatyczny deploy nigdy nie przebudowuje bez cache."
    )


def test_hold_label_and_draft_take_the_pr_out_of_the_queue() -> None:
    """REC-03 / OPS-N04: `wstrzymaj` dodane po włączeniu auto-merge'a nie
    zatrzymywało niczego — PR i tak wchodził na maina."""
    wf = _load("auto-enqueue.yml")
    types = _triggers(wf)["pull_request"]["types"]
    assert {"labeled", "converted_to_draft", "unlabeled"} <= set(types)
    enqueue = wf["jobs"]["enqueue"]
    assert "github.event.action != 'labeled'" in enqueue["if"]
    assert "github.event.action != 'converted_to_draft'" in enqueue["if"]
    hold = wf["jobs"]["hold"]
    assert "converted_to_draft" in hold["if"]
    assert "github.event.label.name == 'wstrzymaj'" in hold["if"]
    step = hold["steps"][0]
    assert step["env"]["GH_TOKEN"] == "${{ secrets.QUEUE_BOT_TOKEN }}"
    assert "--disable-auto" in step["run"]
    assert "dequeuePullRequest" in step["run"], (
        "Wyłączenie auto-merge'a nie wyjmuje PR-a z trwającej kolejki."
    )


def test_enqueue_rechecks_live_labels_not_the_event_snapshot() -> None:
    """24.09.2026: push tuż przed `wstrzymaj` dał job z migawką etykiet bez
    wstrzymania — auto-merge włączył się po etykiecie i PR wszedł do kolejki."""
    run = _load("auto-enqueue.yml")["jobs"]["enqueue"]["steps"][0]["run"]
    live = run.index("gh pr view")
    assert "labels" in run[live:] and "isDraft" in run[live:]
    assert live < run.index("--auto"), "Sprawdzenie stanu musi być PRZED włączeniem."


def test_jobs_with_production_secrets_run_only_from_main() -> None:
    """OPS-N05: workflow_dispatch z dowolnej gałęzi dawał jej wersji pliku
    sekrety produkcji (coolify-ops uruchomiony z gałęzi codex/...)."""
    import yaml as _yaml

    offenders: list[str] = []
    for path in sorted(_WORKFLOWS.glob("*.yml")):
        wf = _load(path.name)
        jobs = wf["jobs"]
        guarded = {
            job_id
            for job_id, job in jobs.items()
            if "github.ref == 'refs/heads/main'" in str(job.get("if", ""))
        }
        for job_id, job in jobs.items():
            text = _yaml.safe_dump(job)
            if "secrets.COOLIFY_" not in text and "secrets.BACKUP_" not in text:
                continue
            needs = job.get("needs") or []
            needs = [needs] if isinstance(needs, str) else needs
            if job_id in guarded or any(n in guarded for n in needs):
                continue
            offenders.append(f"{path.name}:{job_id}")
    assert offenders == []


def test_gitleaks_also_scans_every_commit_of_the_pr_and_merge_group() -> None:
    """OPS-N06: sekret dodany i usunięty w kolejnych commitach PR-a zostaje na
    GitHubie, a skan drzewa (`--no-git`) go nie widzi."""
    job = _load("ci-gate.yml")["jobs"]["secret-scan"]
    assert "if" not in job, "Gitleaks jest wymaganym kontekstem."
    assert job["steps"][0]["with"]["fetch-depth"] == 0
    tree = _step(job["steps"], "Scan working tree")
    assert "--no-git" in tree["run"]
    commits = _step(job["steps"], "Scan commits of this PR / merge group")
    assert "pull_request" in commits["if"] and "merge_group" in commits["if"]
    assert '--log-opts="${BASE_SHA}..${HEAD_SHA}"' in commits["run"]
    assert "--no-git" not in commits["run"]
    assert "merge_group.base_sha" in commits["env"]["BASE_SHA"]
    assert "pull_request.base.sha" in commits["env"]["BASE_SHA"]
    assert "exit 1" in commits["run"], "Brak zakresu = czerwień, nie cichy pass."


def test_deploy_freezes_at_night_and_catches_up_in_the_morning() -> None:
    """PROD-04: automatyczny deploy w oknie ciszy (domyślnie 0-7 Warszawa)
    jest odraczany; poranny `schedule` wdraża zaległe merge'e."""
    deploy = _load("deploy.yml")
    crons = [entry["cron"] for entry in _triggers(deploy)["schedule"]]
    assert crons == ["15 5,6 * * *"], "05:15Z = 07:15 latem, 06:15Z = 07:15 zimą."
    select = deploy["jobs"]["select"]
    assert "github.event_name == 'schedule'" in select["if"]
    assert "github.ref == 'refs/heads/main'" in select["if"]
    step = _step(select["steps"], "Wybierz wydanie")
    freeze = step["env"]["FREEZE_WINDOW"]
    assert "vars.DEPLOY_FREEZE_WINDOW" in freeze and "'0-7'" in freeze
    assert "github.event_name != 'workflow_dispatch'" in freeze, (
        "Ręczny deploy nie pyta o okno ciszy."
    )
    assert '--freeze-window "$FREEZE_WINDOW"' in step["run"]
    assert "$SCHEDULED" in step["run"]
    assert (
        step["env"]["SCHEDULED"]
        == "${{ github.event_name == 'schedule' && '--scheduled' || '' }}"
    )


def test_held_and_red_deploys_open_and_close_an_issue() -> None:
    """OPS-N07: wstrzymany i czerwony deploy zostawiały tylko `::warning::`."""
    deploy = _load("deploy.yml")
    assert deploy["env"]["HOLD_ALERT_MARKER"] == "Deploy NEXUS wstrzymany"
    assert deploy["env"]["RED_ALERT_MARKER"] == "Deploy NEXUS jest czerwony"

    select = deploy["jobs"]["select"]
    assert select["permissions"]["issues"] == "write"
    hold = _step(select["steps"], "Alarm — deploy wstrzymany")
    assert hold["if"] == "${{ steps.release_select.outputs.hold_alert != '' }}"
    assert 'alert_issue.sh open "$HOLD_ALERT_MARKER"' in hold["run"]
    resolve = _step(select["steps"], "Zamknij alarm wstrzymania")
    assert resolve["if"] == "${{ steps.release_select.outputs.defer == 'false' }}"
    assert 'alert_issue.sh resolve "$HOLD_ALERT_MARKER"' in resolve["run"]

    red_gate = deploy["jobs"]["gate-red-alert"]
    assert "workflow_run.conclusion == 'failure'" in red_gate["if"]
    assert (
        "hold-check"
        in _step(red_gate["steps"], "Czy HEAD maina nadal ma czerwoną bramkę?")["run"]
    )

    job = deploy["jobs"]["deploy"]
    assert job["permissions"]["issues"] == "write"
    ok = _step(job["steps"], "Zamknij alarm czerwonego deployu")
    assert ok["if"] == "${{ success() }}"
    assert 'resolve "$RED_ALERT_MARKER"' in ok["run"]
    red = _step(job["steps"], "Alarm — czerwony deploy")
    assert red["if"].startswith("${{ failure()")
    assert 'open "$RED_ALERT_MARKER"' in red["run"]


def test_every_alert_issue_can_also_be_closed_by_a_green_run() -> None:
    """OPS-N08: #825 i #1413 wisiały tygodniami po ustąpieniu warunku."""
    import re

    expected = {
        "disk-alert.yml": ["NEXUS host disk high"],
        "uptime-probe.yml": [
            "NEXUS health checks unhealthy",
            "NEXUS niedostępny (sonda GitHub)",
            "Kopia off-site NEXUS nieświeża lub niekompletna",
        ],
        "backup-drill.yml": ["NEXUS backup drill nie przechodzi"],
        "sentry-daily-monitor.yml": ["NEXUS dzienny monitor Sentry nie działa"],
        "e2e.yml": [
            "Nocny E2E przeciw produkcji jest czerwony",
            "E2E po deployu (prod-smoke) jest czerwony",
            "Nocny E2E na stacku testowym jest czerwony",
        ],
    }
    for name, markers in expected.items():
        wf = _load(name)
        opening, closing = [], []
        for job in wf["jobs"].values():
            for step in job.get("steps", []):
                run = str(step.get("run", ""))
                if "alert_issue.sh resolve" in run:
                    closing.append(run)
                elif "gh issue create" in run or "alert_issue.sh open" in run:
                    opening.append(run)
        opened = "\n".join(opening)
        closed = "\n".join(closing)
        for marker in markers:
            assert marker in opened, f"{name}: nikt nie otwiera alarmu {marker!r}"
            assert marker in closed, f"{name}: nic nie zamyka alarmu {marker!r}"
        # Każdy literał markera przy otwieraniu musi mieć swoje zamknięcie.
        literals = set(re.findall(r'marker="([^"$][^"]*)"', opened))
        literals |= set(re.findall(r'notify "([^"$][^"]*)"', opened))
        assert literals <= set(markers), (name, literals - set(markers))


def test_queue_failure_feedback_reports_ejected_merge_group_runs() -> None:
    """Czerwony bieg kolejki wyrzuca PR, a checki PR-a zostają zielone —
    62 z 99 biegów w kolejce czerwonych w 27 h (23–24.09.2026), PR-y
    wyrzucane po 4–6 razy, bo nikt nie mówił sesji, że PR wypadł."""
    wf = _load("queue-failure-feedback.yml")
    trigger = _triggers(wf)["workflow_run"]
    assert trigger["workflows"] == ["CI"]
    assert trigger["types"] == ["completed"]
    job = wf["jobs"]["feedback"]
    condition = " ".join(str(job["if"]).split())
    assert "github.event.workflow_run.event == 'merge_group'" in condition
    assert "github.event.workflow_run.conclusion == 'failure'" in condition
    assert job["permissions"]["statuses"] == "write"
    assert job["permissions"]["pull-requests"] == "write"
    assert (
        "queue_failure_feedback.py"
        in _step(job["steps"], "Status i komentarz na PR-ach z grupy")["run"]
    )
