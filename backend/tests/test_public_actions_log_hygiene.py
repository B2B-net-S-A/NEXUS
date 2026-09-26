"""Runda 7 (X2): log Actions publicznego repo nie dostaje danych ani sekretów.

Każdy test uruchamia albo czyta prawdziwy fragment workflowu — nie jego opis.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
import yaml

_REPO = Path(__file__).resolve().parents[2]
_WORKFLOWS = _REPO / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((_WORKFLOWS / name).read_text(encoding="utf-8"))


def _step(job: dict, name: str) -> dict:
    return next(step for step in job["steps"] if step.get("name") == name)


# ── Coolify set env (R7-X2-2) ────────────────────────────────────────────────

_SET_ENV_STEP = "Set env via Coolify API"
_CURL_STUB = """#!/bin/bash
out=""; fmt=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    -w) fmt="$2"; shift 2;;
    *) shift;;
  esac
done
[ -n "$out" ] && echo '[]' > "$out"
[ -n "$fmt" ] && printf 200
exit 0
"""


def _run_set_env(key: str, value: str) -> subprocess.CompletedProcess:
    step = _step(_load("coolify-set-env.yml")["jobs"]["set-env"], _SET_ENV_STEP)
    with tempfile.TemporaryDirectory() as tmp:
        curl = Path(tmp) / "curl"
        curl.write_text(_CURL_STUB, encoding="utf-8")
        curl.chmod(0o755)
        event = Path(tmp) / "event.json"
        event.write_text(json.dumps({"inputs": {"value": value}}), encoding="utf-8")
        env = {
            "PATH": f"{tmp}:{os.environ['PATH']}",
            "GITHUB_EVENT_PATH": str(event),
            "COOLIFY_URL": "https://coolify.example",
            "COOLIFY_TOKEN": "t",
            "COOLIFY_APP_UUID": "app",
            "KEY": key,
            "VALUE_FROM_SECRET": "",
            "VALUE_SECRET": "",
            "IS_BUILDTIME": "false",
        }
        for name, raw in (step.get("env") or {}).items():
            # Bez wartości z `inputs.value` w `env:` — sprawdza to osobny test.
            env.setdefault(name, "" if "${{" in str(raw) else str(raw))
        return subprocess.run(
            ["bash", "-c", step["run"]],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.mark.skipif(shutil.which("jq") is None, reason="brak jq")
def test_set_env_masks_the_plain_value_before_printing_anything():
    value = "wartosc-jawna-123\ndruga-linia"
    result = _run_set_env("SOME_FLAG", value)
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:2] == [
        "::add-mask::wartosc-jawna-123",
        "::add-mask::druga-linia",
    ], lines[:3]
    visible = [line for line in lines if not line.startswith("::add-mask::")]
    assert not any("wartosc-jawna" in line or "druga-linia" in line for line in visible)


@pytest.mark.skipif(shutil.which("jq") is None, reason="brak jq")
def test_set_env_refuses_a_plain_value_for_a_secret_looking_key():
    for key in (
        "COMPASS_INTEGRATION_BOOTSTRAP_KEY",
        "M365_CLIENT_SECRET",
        "SMTP_PASSWORD",
    ):
        result = _run_set_env(key, "x")
        assert result.returncode == 1, key
        assert "value_from_secret" in result.stderr


def test_set_env_does_not_put_the_plain_value_in_step_env():
    """GitHub wypisuje blok `env:` w nagłówku kroku, zanim zadziała maska."""
    raw = (_WORKFLOWS / "coolify-set-env.yml").read_text(encoding="utf-8")
    wf = _load("coolify-set-env.yml")
    for step in wf["jobs"]["set-env"]["steps"]:
        for value in (step.get("env") or {}).values():
            assert "inputs.value }}" not in str(value), step.get("name")
    assert "${{ inputs.value }}" not in raw


# ── Backup drill (R7-X2-4) ───────────────────────────────────────────────────

_RESTORE_ERR = """pg_restore: error: could not execute query: ERROR:  duplicate key value violates unique constraint "candidates_email_key"
DETAIL:  Key (email)=(jan.nowak@example.com) already exists.
Command was: COPY public.candidates (id, first_name, last_name, email) FROM stdin;
pg_restore: error: COPY failed for table "candidates": ERROR:  invalid input syntax for type integer: "Jan Nowak"
CONTEXT:  COPY candidates, line 5, column id: "Jan Nowak"
pg_restore: warning: errors ignored on restore: 2
"""


def _drill_restore_run() -> str:
    job = _load("backup-drill.yml")["jobs"]
    run = next(
        step["run"]
        for j in job.values()
        for step in j["steps"]
        if step.get("name") == "Restore dump into ephemeral Postgres"
    )
    return run


def test_drill_never_prints_the_raw_pg_restore_stderr():
    run = _drill_restore_run()
    assert "cat /tmp/restore.err" not in run
    assert "Command was: " not in re.sub(r"^\s*#.*$", "", run, flags=re.M).replace(
        "/^Command was: ", ""
    ), "linia `Command was:` z treścią nie może trafić do logu"


def test_drill_classifier_prints_error_kinds_without_row_values():
    run = _drill_restore_run()
    program = run.split("awk '", 1)[1].split("' /tmp/restore.err", 1)[0]
    with tempfile.TemporaryDirectory() as tmp:
        err = Path(tmp) / "restore.err"
        err.write_text(_RESTORE_ERR, encoding="utf-8")
        out = subprocess.run(
            ["awk", program, str(err)], capture_output=True, text=True, check=True
        ).stdout
    assert out.count("error: ") == 2, out
    for leaked in ("jan.nowak", "Jan Nowak", "Key (email)", "first_name"):
        assert leaked not in out, out
    assert "duplicate key value violates unique constraint" in out
    assert "COPY public.candidates" in out


def test_drill_alembic_step_prints_only_the_exception_class():
    job = _load("backup-drill.yml")["jobs"]
    run = next(
        step["run"]
        for j in job.values()
        for step in j["steps"]
        if step.get("name") == "Alembic upgrade head on restored DB"
    )
    assert "> /tmp/alembic.log 2>&1" in run
    assert "cat /tmp/alembic.log" not in run


# ── E2E przeciw produkcji (R7-X2-8) ──────────────────────────────────────────


def test_production_e2e_prints_counts_and_titles_not_assertion_text():
    job = _load("e2e.yml")["jobs"]["playwright"]
    run = _step(job, "Run tests")["run"]
    calls = re.findall(r"^\s*(npx playwright test[^\n]*|run_pw[^\n]*)$", run, re.M)
    assert calls, run
    for call in calls:
        if '"$@"' in call:  # jedyne gołe wywołanie — wewnątrz run_pw
            continue
        assert call.strip().startswith("run_pw"), call
    assert "--reporter=json > /dev/null" in run


@pytest.mark.skipif(shutil.which("node") is None, reason="brak node")
def test_production_e2e_summary_omits_the_error_message():
    run = _step(_load("e2e.yml")["jobs"]["playwright"], "Run tests")["run"]
    script = run.split("node -e '", 1)[1].split("' \"${RUNNER_TEMP}", 1)[0]
    results = {
        "stats": {"expected": 3, "unexpected": 1, "flaky": 0, "skipped": 0},
        "suites": [
            {
                "title": "candidates.spec.ts",
                "specs": [
                    {
                        "title": "lista kandydatów",
                        "tests": [
                            {
                                "projectName": "prod-smoke",
                                "status": "unexpected",
                                "results": [
                                    {"error": {"message": "Received: Jan Nowak"}}
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
    }
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pw.json"
        path.write_text(json.dumps(results), encoding="utf-8")
        out = subprocess.run(
            ["node", "-e", script, str(path)],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    assert "fail=1" in out
    assert "lista kandydatów" in out
    assert "Jan Nowak" not in out and "Received" not in out


# ── Jednorazowe sprzątanie poczty zamówień (R7-X2-6) ─────────────────────────


def test_no_production_job_uploads_the_order_mail_cleanup_report():
    """Artefakt niósł nazwy PDF-ów i powody bramki; operacja wykonana 09.09."""
    assert not (_WORKFLOWS / "order-mail-cleanup.yml").exists()
    assert not (_REPO / ".github" / "scripts" / "order-mail-cleanup-ops.py").exists()
