"""Kontrakty przyspieszenia CI i deployu (22.09.2026).

Zmierzone przed zmianą: jedna poprawka czekała ~20 min na CI PR-a, potem ~20 min
na to samo CI w kolejce merge'ów, potem ~9 min na deploy. Każda z konstrukcji
poniżej odpowiada za część tego czasu i łatwo ją cofnąć „przy okazji”.
"""

from __future__ import annotations

import importlib.util
import json
import re
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
    assert "repo-guards" in gate["needs"]
    assert '[ "$guards" != "success" ]' in run, (
        "Czerwoni strażnicy repo muszą dawać czerwony wymagany kontekst."
    )


def test_frontend_heavy_steps_run_in_the_queue_and_prs_get_changed_tests() -> None:
    jobs = _load("ci.yml")["jobs"]
    steps = jobs["frontend-lint-build"]["steps"]
    assert "github.event_name != 'pull_request'" in _step(steps, "Build")["if"]
    assert jobs["frontend-vitest"]["if"] == (
        "${{ github.event_name != 'pull_request' }}"
    )
    pr = _step(steps, "Vitest (testy dotknięte zmianą)")
    assert "github.event_name == 'pull_request'" in pr["if"]
    assert "--changed" in pr["run"] and "--passWithNoTests" in pr["run"]


def test_required_frontend_context_collects_build_and_vitest() -> None:
    """24.09.2026: Vitest z pokryciem wyszedł z joba builda, żeby wymagany
    kontekst nie był dłuższy od backendu na 12 shardach. Nazwa kontekstu jest
    w rulesecie, więc niesie ją job zbiorczy — jak „Backend (pytest)”."""
    jobs = _load("ci.yml")["jobs"]
    gate = jobs["frontend-gate"]
    assert gate["name"] == "Frontend (typecheck + build)", (
        "Nazwa jest wymaganym kontekstem rulesetu."
    )
    assert gate["if"] == "${{ always() }}", (
        "Bez always() padnięty job zależny zostawia kontekst `skipped`."
    )
    assert set(gate["needs"]) == {"frontend-lint-build", "frontend-vitest"}
    run = gate["steps"][0]["run"]
    assert '[ "$build" != "success" ]' in run
    assert '[ "$vitest" != "success" ]' in run
    # Na PR-ze Vitest z pokryciem jest pominięty — bramka nie może go czytać
    # jako porażki, ale poza PR-em musi.
    assert run.index('"pull_request"') < run.index("needs.frontend-vitest.result")
    names = [job.get("name") for job in jobs.values()]
    assert names.count("Frontend (typecheck + build)") == 1, (
        "Dwa joby o nazwie wymaganego kontekstu = niejednoznaczny status."
    )


def test_backend_shard_count_matches_the_measurement() -> None:
    """12 shardów od 24.09.2026 (pomiar w komentarzu nad jobem). Zmiana liczby
    to zmiana czasu kolejki — rób ją razem z nowym pomiarem, nie przy okazji."""
    jobs = _load("ci.yml")["jobs"]
    shards = jobs["backend-lint-test"]["strategy"]["matrix"]["shard"]
    assert shards == list(range(12))
    assert jobs["backend-coverage-combine"]["env"]["EXPECTED_SHARDS"] == "12"


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


_PIPEFAIL = re.compile(r"^\s*set\s+-[a-z]*o\s+pipefail\b", re.M)


def _tee_without_pipefail(workflow: dict) -> list[str]:
    """Kroki, w których `| tee` ukrywa status komendy stojącej przed nim.

    Krok bez `shell:` biegnie jako `bash -e {0}` — bez pipefail, więc
    `pytest … | tee plik` kończy się statusem `tee` (0) także przy czerwonych
    testach. `shell: bash` (krok albo `defaults.run`) daje `-eo pipefail`;
    inaczej `set -o pipefail` musi stać przed pierwszym `tee`.
    """
    top_shell = ((workflow.get("defaults") or {}).get("run") or {}).get("shell")
    bad: list[str] = []
    for job_id, job in (workflow.get("jobs") or {}).items():
        job_shell = ((job.get("defaults") or {}).get("run") or {}).get("shell")
        for step in job.get("steps") or []:
            run = step.get("run") or ""
            tee = re.search(r"\|\s*tee\b", run)
            if not tee or (step.get("shell") or job_shell or top_shell) == "bash":
                continue
            guard = _PIPEFAIL.search(run)
            if not guard or guard.start() > tee.start():
                bad.append(f"{job_id}: {step.get('name')}")
    return bad


def test_shard_pytest_fails_the_step_when_tests_fail() -> None:
    # 22–23.09.2026: shardy z `1 failed` kończyły się sukcesem (status tee = 0),
    # a na main weszły dwa czerwone testy.
    run = _step(
        _load("ci.yml")["jobs"]["backend-lint-test"]["steps"],
        "Pytest (unit + in-process integration)",
    )["run"]
    guard = _PIPEFAIL.search(run)
    assert guard and guard.start() < run.index("pytest tests/")


def test_no_workflow_pipes_into_tee_without_pipefail() -> None:
    bad = {
        path.name: steps
        for path in sorted(_WORKFLOWS.glob("*.yml"))
        if (steps := _tee_without_pipefail(_load(path.name)))
    }
    assert bad == {}


def test_tee_detector_catches_the_22_09_shape() -> None:
    def wf(run: str, **step: str) -> dict:
        return {"jobs": {"j": {"steps": [{"name": "s", "run": run, **step}]}}}

    assert _tee_without_pipefail(wf("pytest 2>&1 | tee out")) == ["j: s"]
    assert _tee_without_pipefail(wf("pytest | tee out\nset -o pipefail")) == ["j: s"]
    assert _tee_without_pipefail(wf("set -o pipefail\npytest | tee out")) == []
    assert _tee_without_pipefail(wf("set -euo pipefail\npytest | tee out")) == []
    assert _tee_without_pipefail(wf("pytest | tee out", shell="bash")) == []


def test_deploys_are_batched_but_manual_deploy_does_not_wait() -> None:
    select = _load("deploy.yml")["jobs"]["select"]
    wait = _step(select["steps"], "Poczekaj na ciszę na mainie (grupowanie deployów)")
    assert wait["if"] == "${{ github.event_name != 'workflow_dispatch' }}"
    assert wait["env"]["QUIET"] == "${{ vars.DEPLOY_QUIET_SECONDS || '0' }}", (
        "Domyślnie bez czekania na ciszę (decyzja 26.09.2026)."
    )
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


def test_selector_changed_test_file_selects_tests_that_import_it() -> None:
    """09.11.2026: #3234 zmienił helper `_run` w pliku testowym, który importują
    dwa inne. Sito wybrało tylko sam plik, PR był zielony, a grupa w kolejce
    padła na importerze. Importerzy są pośredni, więc podlegają budżetowi."""
    sel = _selector()
    changed = "tests/test_uptime_probe_health_checks.py"
    direct, indirect = sel.select([f"backend/{changed}"])
    assert changed in direct
    assert {
        "tests/test_fix48_ws13_traffit_tails.py",
        "tests/test_fix48_ws08_traffit_retired.py",
    } <= indirect


def test_selector_finds_importers_of_a_test_file_imported_as_a_module() -> None:
    """Forma `from tests import test_x as y` nie zawiera ścieżki kropkowej."""
    _, indirect = _selector().select(["backend/tests/test_career_links_api.py"])
    assert "tests/test_career_apply_cv_only.py" in indirect


def test_selector_hub_modules_do_not_select_half_the_suite() -> None:
    sel = _selector()
    direct, indirect = sel.select(["backend/app/core/config.py"])
    assert not indirect, "config.py importuje prawie każdy test — to zadanie kolejki."
    assert all(
        Path(t).name == "test_config.py" or Path(t).name.startswith("test_config_")
        for t in direct - {sel._AUTHZ_MATRIX}
    )


def test_selector_finds_tests_that_import_a_changed_module() -> None:
    sel = _selector()
    direct, indirect = sel.select(["backend/app/services/order_mail_ingest.py"])
    assert "tests/test_order_mail_ingest.py" in direct, "Test o nazwie modułu."
    assert "tests/test_nordea_pdf_policy.py" in indirect, "Test importujący moduł."


def test_repo_guards_job_runs_the_static_marker_on_every_pr() -> None:
    """Ok. 17 z 48 czerwonych grup kolejki 21.10.2026 to strażnicy, których sito
    nie wybrało. Job nie patrzy na zmienione pliki i nie ma bazy, więc nie może
    po cichu pominąć strażnika ani go spowolnić migracjami."""
    job = _load("ci.yml")["jobs"]["repo-guards"]
    assert job["name"] == "Strażnicy repo"
    assert job["if"] == "${{ github.event_name == 'pull_request' }}"
    assert "services" not in job, "Bez Postgresa: marker obiecuje brak bazy."
    assert "DATABASE_URL" not in job["env"]
    pytest_run = _step(job["steps"], "Pytest (marker static, bez bazy)")["run"]
    assert "-m static" in pytest_run and "-n 4" in pytest_run
    vitest = _step(job["steps"], "Vitest (strażnicy repo)")["run"]
    assert "src/__tests__/" in vitest and "--changed" not in vitest
    names = [s.get("name") for s in job["steps"]]
    assert names.index("Zaślepka rodzica z PR-a przed tym w pasie") < names.index(
        "Pytest (marker static, bez bazy)"
    ), "Strażnik jednej głowy Alembica musi widzieć zaślepkę rodzica."
    requirements = (_REPO / "backend" / "requirements-testing.txt").read_text("utf-8")
    assert "pytest-xdist==" in requirements


def test_selector_runs_the_route_guard_matrix_for_any_application_change() -> None:
    """Zmiana bramki ma wyjść na PR-ze, nie dopiero w kolejce merge'ów."""
    sel = _selector()
    for changed in (
        "backend/app/api/contracts.py",
        "backend/app/core/config.py",
        "backend/app/services/client_access.py",
        "backend/tests/data/authz_golden/contracts.json",
    ):
        direct, _ = sel.select([changed])
        assert sel._AUTHZ_MATRIX in direct, changed
    direct, indirect = sel.select(["frontend/src/components/EditOrderDialog.tsx"])
    assert sel._AUTHZ_MATRIX not in direct | indirect


def test_selector_budget_keeps_direct_and_drops_slowest_indirect() -> None:
    sel = _selector()
    durations = {"a": 100.0, "b": 10.0, "c": 50.0, "d": 200.0}
    # Budżet liczy też narzut procesu pytest (kolekcja + 0,3 s na plik).
    kept, dropped = sel.apply_budget({"a"}, {"b", "c", "d"}, 200.0, durations)
    assert kept == ["a", "b", "c"]
    assert dropped == ["d"]


def test_selector_no_longer_lists_repo_guards_by_hand() -> None:
    """Lista ``_ALWAYS`` puchła po każdym wypadnięciu z kolejki. Strażnika
    wyznacza teraz marker ``static``, więc sito go nie wybiera."""
    sel = _selector()
    for name in ("_ALWAYS", "_ROUTE_CONTRACTS", "tree_scanner_nodes"):
        assert not hasattr(sel, name), name
    direct, _ = sel.select(["frontend/src/components/EditOrderDialog.tsx"])
    assert not direct


def test_budget_estimate_matches_recorded_sieve_runs() -> None:
    """Szacunek ma odpowiadać zegarowi. Do 21.10.2026 mapa czasów miała pomiar
    dla 1048 z 1967 plików (reszta ważyła 1 s), a macierz bramek 22 s zamiast
    ~150 — sito „na 5 min” trwało 8–15 min samego pytesta.

    Biegi z ``data/sieve_runs_2026_10_21.json`` nie wchodzą do mapy (od
    22.10.2026 mapa to wyłącznie shardy kolejki, przeliczone ×0,8 na brak
    pokrycia). Ten sam wybór na różnych runnerach różni się do ~1,4× (s3),
    dlatego próg per bieg jest szerszy niż próg dla sumy."""
    sel = _selector()
    durations = sel._load_durations()
    runs = json.loads(
        (_REPO / "backend" / "tests" / "data" / "sieve_runs_2026_10_21.json").read_text(
            encoding="utf-8"
        )
    )["runs"]
    assert len(runs) >= 3
    ratios = []
    for run in runs:
        ratio = sel.estimate_seconds(run["files"], durations) / run["pytest_seconds"]
        ratios.append(ratio)
        assert 0.7 <= ratio <= 1.4, (run["job"], round(ratio, 2))
    total = sum(sel.estimate_seconds(r["files"], durations) for r in runs)
    actual = sum(r["pytest_seconds"] for r in runs)
    assert 0.7 <= total / actual <= 1.3, round(total / actual, 2)


def test_sieve_shards_split_the_selection_and_the_route_matrix() -> None:
    sel = _selector()
    durations = sel._load_durations()
    small = ["tests/test_claude_md_index.py", "tests/test_loop_heartbeat.py"]
    plan = sel.plan_shards(small, durations, 3)
    assert plan[0] == (small, None)
    assert plan[1:] == [([], None), ([], None)], "Mały wybór = jedna część."

    run = json.loads(
        (_REPO / "backend" / "tests" / "data" / "sieve_runs_2026_10_21.json").read_text(
            encoding="utf-8"
        )
    )["runs"][0]
    kept = sorted(run["files"])
    assert sel._AUTHZ_MATRIX in kept
    plan = sel.plan_shards(kept, durations, 3)
    assert [s for _, s in plan] == ["0/3", "1/3", "2/3"]
    rest = [f for files, _ in plan for f in files if f != sel._AUTHZ_MATRIX]
    assert sorted(rest) + [sel._AUTHZ_MATRIX] == sorted(
        [f for f in kept if f != sel._AUTHZ_MATRIX]
    ) + [sel._AUTHZ_MATRIX], "Każdy plik w dokładnie jednej części."
    assert all(sel._AUTHZ_MATRIX in files for files, _ in plan)
    loads = [sel._shard_estimate(files, s, durations) for files, s in plan]
    assert max(loads) <= sel.SHARD_TARGET_SECONDS * 1.25, loads


def test_sieve_job_has_as_many_parts_as_the_selector_plans() -> None:
    job = _load("ci.yml")["jobs"]["backend-pr-tests"]
    assert len(job["strategy"]["matrix"]["part"]) == _selector().SIEVE_SHARDS
    assert job["strategy"]["fail-fast"] is False
    pick = _step(job["steps"], "Wybierz testy dla zmienionych plików")["run"]
    assert '--shards "${{ strategy.job-total }}"' in pick
    assert '--shard "${{ strategy.job-index }}"' in pick
    assert '--env-out "$GITHUB_ENV"' in pick, "Bez tego macierz nie dzieli się."


def test_queue_runs_the_repo_guards_in_the_fast_required_job() -> None:
    """Zły PR ma wypaść z kolejki po ~3 min, nie po ~25 (21.10.2026)."""
    job = _load("ci-gate.yml")["jobs"]["backend-fast"]
    assert job["name"] == "Backend (lint + migrations)", "Wymagany kontekst."
    names = [s.get("name") for s in job["steps"]]
    step = _step(job["steps"], "Strażnicy repo (bez bazy, kolejka merge'ów)")
    assert step["if"] == "${{ github.event_name == 'merge_group' }}"
    assert "-m static" in step["run"] and "-n 4" in step["run"]
    assert "DATABASE_URL" not in (step.get("env") or {})
    assert names.index(step["name"]) < names.index(
        "Alembic legacy-row, retry, and contact-queue rollback probe"
    ), "Przed migracjami — inaczej sygnał przychodzi później."


def test_frontend_sieve_always_runs_the_repo_guards() -> None:
    step = _step(
        _load("ci.yml")["jobs"]["frontend-lint-build"]["steps"],
        "Vitest (testy dotknięte zmianą)",
    )
    guards = (
        "src/components/v2/shell/__tests__/BreadcrumbV2.test.tsx",
        "src/lib/__tests__/recruitment-feature-parity.test.ts",
        "src/lib/__tests__/orders-contracts-feature-parity.test.ts",
        "src/lib/__tests__/candidate-profile-feature-parity.test.ts",
    )
    for guard in guards:
        assert guard in step["run"], guard
        assert (_REPO / "frontend" / guard).exists(), guard


def test_ready_prs_enter_the_queue_by_themselves_with_a_real_token() -> None:
    """Zielony PR nie może czekać, aż ktoś go ręcznie wrzuci do kolejki."""
    wf = _load("auto-enqueue.yml")
    triggers = wf.get("on", wf.get(True))
    assert "ready_for_review" in triggers["pull_request"]["types"]
    job = wf["jobs"]["enqueue"]
    for guard in ("draft", "dependabot[bot]", "wstrzymaj"):
        assert guard in job["if"], f"Brak bezpiecznika {guard!r}."
    step = job["steps"][0]
    assert step["env"]["GH_TOKEN"] == "${{ secrets.QUEUE_BOT_TOKEN }}", (
        "GITHUB_TOKEN nie uruchamia merge_group — grupa wisiałaby bez testów."
    )
    assert "--auto" in step["run"] and "--squash" in step["run"]
