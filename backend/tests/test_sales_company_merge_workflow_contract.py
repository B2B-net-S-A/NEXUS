"""Scalanie kart firm z workflowu: do publicznego logu Actions idą same liczby.

Trzy rzeczy, na których stoi bieg na produkcji:

* krok „Zbuduj komendę” przepuszcza do komendy wyłącznie cyfry, przecinki
  i dwukropki (test uruchamia prawdziwy krok z pliku workflowu);
* filtr ``sales_company_merge_report.py`` drukuje tylko zwalidowany raport albo
  komunikat o stałej treści i odtwarza kod wyjścia skryptu;
* filtr i workflow zgadzają się ze skryptem ``scripts/sales_company_merge.py``
  (pola raportu, treść odmów, kody, flagi), więc zmiana skryptu bez zmiany filtra
  pada tutaj, a nie po zapisie na produkcji.
"""

from __future__ import annotations

import ast
import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import patch

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPT = ROOT / "backend" / "scripts" / "sales_company_merge.py"
SPEC = importlib.util.spec_from_file_location(
    "sales_company_merge_report_under_test",
    ROOT / ".github" / "scripts" / "sales_company_merge_report.py",
)
assert SPEC and SPEC.loader
reporter = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = reporter
SPEC.loader.exec_module(reporter)

JOB = yaml.safe_load(
    (WORKFLOWS / "coolify-sales-company-merge.yml").read_text(encoding="utf-8")
)["jobs"]["merge"]
SENTINEL = JOB["env"]["SENTINEL"]
RUN_ID = "19876543210"
LOCK = f"/tmp/nexus-sales-company-merge-{RUN_ID}"
MARKER = "SYNTHETIC_PRIVATE_MARKER"

REPORT = {
    "mode": "dry-run",
    "seeds_pipeline": 48,
    "seeds_names": 0,
    "seeds_ids": 0,
    "names_without_card": 0,
    "groups": {"pojedyncza": 46, "do_decyzji": 2},
    "to_decide_reasons": {"rozne_nipy": 1, "wspolny_nip_rozne_nazwy": 1},
    "blocked_reasons": {},
    "similar_cards": 60,
    "similar_name_variants": 17,
    "to_merge": 0,
    "to_merge_by_origin": {},
    "moving": {"contacts": 0, "opportunities": 0, "activities": 0, "files": 0},
    "names_to_join": 0,
    "outlook_duplicates": 54,
    "domains": {"jest": 2, "do_zapisu": 27, "slaba": 3, "brak": 16},
    "domains_to_set": 27,
    "merged": 0,
    "names_joined": 0,
    "domains_set": 0,
}
APPLIED = {
    **REPORT,
    "mode": "apply",
    "to_merge": 3,
    "to_merge_by_origin": {"decyzja": 3},
    "names_to_join": 2,
    "merged": 3,
    "names_joined": 2,
    "domains_set": 27,
}
LOCK_LINE = f"lock {LOCK} exists — already ran"
DIFFERS_LINE = "Odmowa, transakcja wycofana: wynik zapisu różni się od planu"


def _step(name: str) -> dict:
    return next(step for step in JOB["steps"] if step.get("name") == name)


def _execution(text: str) -> dict:
    return {"status": "success", "message": f"{text}\n{SENTINEL}\n"}


def _read(executions: Any, mode: str = "dry-run") -> tuple[int, str]:
    stdin = executions if isinstance(executions, str) else json.dumps(executions)
    output = io.StringIO()
    with (
        patch.dict(os.environ, {"MODE": mode, "SENTINEL": SENTINEL}, clear=True),
        patch.object(sys, "stdin", io.StringIO(stdin)),
        contextlib.redirect_stdout(output),
    ):
        code = reporter.main()
    return code, output.getvalue().strip()


# ── Filtr raportu ────────────────────────────────────────────────────────────


def test_report_is_printed_without_the_logs_around_it() -> None:
    message = (
        f"2026-11-10 INFO sqlalchemy {MARKER} {{'mode': 'x'}}\n"
        + json.dumps(REPORT, indent=2)
        + f"\nWARNING {MARKER}"
    )
    code, printed = _read([_execution(message), _execution(LOCK_LINE)])
    assert code == 0
    assert json.loads(printed) == REPORT
    assert MARKER not in printed


def test_apply_report_is_green_only_when_writes_equal_the_plan() -> None:
    assert _read([_execution(json.dumps(APPLIED))], "apply") == (
        0,
        json.dumps(APPLIED, ensure_ascii=False, indent=2),
    )
    for wrong in (
        {**APPLIED, "merged": 2},
        {**APPLIED, "names_joined": 0},
        {**APPLIED, "domains_set": 26},
        {**APPLIED, "mode": "dry-run"},
    ):
        code, printed = _read([_execution(json.dumps(wrong))], "apply")
        assert code == 1 and printed.startswith("::error::"), wrong
    # Bieg na sucho, który raportuje zapis, też nie jest zielony.
    assert _read([_execution(json.dumps({**REPORT, "merged": 1}))])[0] == 1
    assert _read([_execution(json.dumps(APPLIED))], "dry-run")[0] == 1


@pytest.mark.parametrize(
    "change",
    [
        {"company_names": 1},
        {"to_merge": True},
        {"to_merge": -1},
        {"to_merge": 1.0},
        {"to_merge": "0"},
        {"to_merge": None},
        {"groups": 3},
        {"groups": [1]},
        {"groups": {"pewna": "1"}},
        {"groups": {"pewna": True}},
        {"groups": {"pewna": {"x": 1}}},
        {"domains": {"example.com": 1}},
        {"domains": {"Firma": 1}},
        {"domains": {"firma testowa": 1}},
        {"domains": {"": 1}},
        {"mode": "verify"},
    ],
)
def test_report_of_another_shape_is_not_printed(change: dict) -> None:
    code, printed = _read([_execution(json.dumps({**REPORT, **change}))])
    assert code == 1
    assert printed.startswith("::error::") and "stan zapisu jest nieznany" in printed
    assert "{" not in printed


def test_report_with_a_missing_field_is_not_printed() -> None:
    for missing in REPORT:
        partial = {key: value for key, value in REPORT.items() if key != missing}
        assert _read([_execution(json.dumps(partial))])[0] == 1, missing


@pytest.mark.parametrize(
    "executions",
    [
        [],
        "",
        "<html>502 Bad Gateway</html>",
        {"message": "Unauthenticated."},
        [{"status": "running", "message": None}],
        [{"status": "running"}, _execution(LOCK_LINE)],
        [{"status": "failed", "message": "No such container"}],
        ["nie słownik"],
    ],
)
def test_no_finished_work_means_keep_waiting(executions: Any) -> None:
    assert _read(executions) == (reporter.EXIT_PENDING, "")


def test_only_lock_lines_mean_this_run_already_worked() -> None:
    code, printed = _read([_execution(LOCK_LINE), _execution(LOCK_LINE)])
    assert code == 4
    assert printed.startswith("::error::Kod 4: blokada")


@pytest.mark.parametrize(
    "reason",
    [
        "--expect-merge 12, a jest 14",
        "--expect-domains 27, a jest 0",
        "--apply wymaga --expect-merge i --expect-domains z biegu na sucho",
        "--actor-id: potrzebne aktywne konto administratora",
        "--decide: karta nie istnieje albo jest w archiwum",
        "karta z planu zniknęła albo trafiła do archiwum",
    ],
)
def test_known_refusal_is_printed_with_its_numbers(reason: str) -> None:
    message = f"{MARKER}\nOdmowa, nic nie zapisano: {reason}"
    code, printed = _read([_execution(message)], "apply")
    assert code == 2
    assert printed == f"::error::Kod 2: odmowa, nic nie zapisano: {reason}"


@pytest.mark.parametrize(
    "reason",
    [
        f"karta {MARKER} sp. z o.o. ma dwie domeny",
        f"--expect-merge 12, a jest 14 {MARKER}",
        f"example.com {MARKER}",
        "",
    ],
)
def test_unknown_refusal_keeps_its_code_but_not_its_text(reason: str) -> None:
    code, printed = _read([_execution(f"Odmowa, nic nie zapisano: {reason}")])
    assert code == 2
    assert printed.startswith("::error::Kod 2: odmowa, nic nie zapisano: treści")
    assert MARKER not in printed and "example.com" not in printed


def test_result_other_than_the_plan_is_code_3() -> None:
    code, printed = _read([_execution(f"{MARKER}\n{DIFFERS_LINE}")], "apply")
    assert code == 3
    assert printed.startswith("::error::Kod 3:") and MARKER not in printed


def test_script_error_prints_only_the_exception_type() -> None:
    code, printed = _read([_execution(f"{MARKER}\nBłąd: OperationalError")])
    assert code == 1
    assert "(OperationalError)" in printed and MARKER not in printed
    for text in (f"ValueError: {MARKER}", f"{MARKER} sp. z o.o.", ""):
        code, printed = _read([_execution(f"Błąd: {text}")])
        assert code == 1 and printed.startswith("::error::Kod 1:")
        assert MARKER not in printed


def test_failure_line_wins_over_a_report_in_the_same_execution() -> None:
    message = json.dumps(APPLIED) + "\nBłąd: RuntimeError"
    assert _read([_execution(message)], "apply")[0] == 1
    message = json.dumps(APPLIED) + "\n" + DIFFERS_LINE
    assert _read([_execution(message)], "apply")[0] == 3


def test_codes_2_3_and_4_have_different_messages() -> None:
    outcomes = [
        _read([_execution("Odmowa, nic nie zapisano: --expect-merge 1, a jest 2")]),
        _read([_execution(DIFFERS_LINE)]),
        _read([_execution(LOCK_LINE)]),
    ]
    assert [code for code, _ in outcomes] == [2, 3, 4]
    assert len({text for _, text in outcomes}) == 3
    assert all(text.startswith(f"::error::Kod {code}:") for code, text in outcomes)


def test_two_working_executions_with_different_results_are_an_error() -> None:
    code, printed = _read(
        [_execution(json.dumps(REPORT)), _execution("Błąd: RuntimeError")]
    )
    assert code == 1 and "różne wyniki" in printed


def test_report_is_the_last_json_before_the_sentinel() -> None:
    # Logi aplikacji przed raportem mogą zawierać słownik z kluczem „mode”.
    message = json.dumps({"mode": "dry-run"}) + "\n" + json.dumps(REPORT)
    assert _read([_execution(message)])[0] == 0
    # Za znacznikiem nic z komendy już nie pisze; ten tekst nie zmienia wyniku.
    trailing = {"message": f"{json.dumps(REPORT)}\n{SENTINEL}\nBłąd: RuntimeError"}
    assert _read([trailing])[0] == 0


def test_already_ran_inside_a_working_execution_is_not_a_lock() -> None:
    message = f"INFO {MARKER} migration already ran\n" + json.dumps(REPORT)
    code, printed = _read([_execution(message)])
    assert code == 0 and json.loads(printed) == REPORT


def test_filter_crash_prints_only_the_exception_type() -> None:
    def crash(*_: Any) -> None:
        raise RuntimeError(MARKER)

    with patch.object(reporter, "classify", crash):
        code, printed = _read([_execution(json.dumps(REPORT))])
    assert code == 1
    assert printed == "::error::Filtr raportu: RuntimeError"


def test_unknown_mode_or_missing_sentinel_is_an_error() -> None:
    assert reporter.classify([], MARKER, SENTINEL).code == 1
    assert reporter.classify([], "apply", "").code == 1
    assert MARKER not in reporter.classify([], MARKER, SENTINEL).text


# ── Workflow ─────────────────────────────────────────────────────────────────


def _build(mode: str = "dry-run", **inputs: str) -> tuple[int, str, str]:
    """Uruchamia prawdziwy krok „Zbuduj komendę”; zwraca kod, komendę i log."""
    step = _step("Zbuduj komendę")
    with tempfile.TemporaryDirectory() as tmp:
        github_env = Path(tmp) / "github_env"
        github_env.touch()
        env = {name: "" for name in step["env"]}
        env.update(
            PATH=os.environ["PATH"],
            GITHUB_ENV=str(github_env),
            GITHUB_RUN_ID=RUN_ID,
            MODE=mode,
            SENTINEL=SENTINEL,
        )
        env.update({name.upper(): value for name, value in inputs.items()})
        result = subprocess.run(
            ["bash", "-c", step["run"]],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        written = github_env.read_text(encoding="utf-8")
    command = written[len("CMD=") :].rstrip("\n") if written else ""
    return result.returncode, command, result.stdout + result.stderr


def test_dry_run_without_inputs_is_the_bare_command_with_the_run_lock() -> None:
    code, command, log = _build()
    assert code == 0, log
    assert command == (
        "cd /app && python -m scripts.sales_company_merge "
        f"--lock {LOCK} 2>&1 ; echo {SENTINEL}"
    )
    assert command in log


def test_apply_carries_the_accepted_counts_decisions_and_ids() -> None:
    code, command, log = _build(
        "apply",
        expect_merge="3",
        expect_domains="27",
        actor_id="82",
        decide="12:34,35   40:41",
        company_ids="7,8",
        accept_domain="12",
    )
    assert code == 0, log
    assert command == (
        "cd /app && python -m scripts.sales_company_merge --apply --actor-id 82 "
        "--expect-merge 3 --expect-domains 27 --decide 12:34,35 --decide 40:41 "
        f"--company-ids 7,8 --accept-domain 12 --lock {LOCK} 2>&1 ; echo {SENTINEL}"
    )
    assert len(command) <= 255


@pytest.mark.parametrize("missing", ["expect_merge", "expect_domains", "actor_id"])
def test_apply_without_counts_or_actor_is_refused_in_the_workflow(
    missing: str,
) -> None:
    inputs = {"expect_merge": "3", "expect_domains": "27", "actor_id": "82"}
    del inputs[missing]
    code, command, log = _build("apply", **inputs)
    assert (code, command) == (1, "")
    assert "apply wymaga expect_merge" in log


@pytest.mark.parametrize("given", ["expect_merge", "expect_domains", "actor_id"])
def test_dry_run_with_apply_inputs_is_refused_instead_of_silently_dry(
    given: str,
) -> None:
    code, command, log = _build("dry-run", **{given: "1"})
    assert (code, command) == (1, "")
    assert "tylko z mode=apply" in log


def test_unknown_mode_is_refused() -> None:
    assert _build("verify")[:2] == (1, "")


_HOSTILE = [
    "1; id",
    "$(id)",
    "`id`",
    "1'",
    '1"',
    "1|id",
    "1&&id",
    "1>x",
    "a",
    "--apply",
    "1\n2",
    "1\t2",
    "1.5",
    "-1",
    "1234567890",
]


@pytest.mark.parametrize(
    "name", ["expect_merge", "expect_domains", "actor_id", "company_ids"]
)
@pytest.mark.parametrize("value", [*_HOSTILE, "1 2", "1:2", "1,", ",1", "1,,2"])
def test_only_digits_and_commas_reach_the_command(name: str, value: str) -> None:
    inputs = {"expect_merge": "3", "expect_domains": "27", "actor_id": "82"}
    inputs[name] = value
    code, command, log = _build("apply", **inputs)
    assert (code, command) == (1, ""), log
    assert f"wejście {name} ma niedozwolony kształt" in log


@pytest.mark.parametrize("name", ["decide", "accept_domain"])
@pytest.mark.parametrize("value", _HOSTILE)
def test_hostile_text_never_reaches_the_command(name: str, value: str) -> None:
    code, command, log = _build(**{name: value})
    assert (code, command) == (1, ""), log
    assert f"wejście {name} ma niedozwolony kształt" in log


@pytest.mark.parametrize("value", ["12", "12:", ":12", "12:34,", "12:34:56", "1,2"])
def test_decision_must_be_target_colon_sources(value: str) -> None:
    code, command, log = _build(decide=value)
    assert (code, command) == (1, ""), log


def test_command_over_255_characters_asks_to_split_the_decisions() -> None:
    decisions = " ".join(f"{1000 + i}:{2000 + i},{3000 + i}" for i in range(9))
    code, command, log = _build(decide=decisions)
    assert (code, command) == (1, "")
    assert "VARCHAR(255)" in log and "Podziel decyzje na kilka biegów" in log


def test_inputs_reach_the_scripts_only_through_env() -> None:
    for step in JOB["steps"]:
        assert "${{" not in step.get("run", ""), step.get("name")
    build = _step("Zbuduj komendę")
    assert {value.strip("${} ") for value in build["env"].values()} == {
        "inputs.expect_merge",
        "inputs.expect_domains",
        "inputs.actor_id",
        "inputs.decide",
        "inputs.company_ids",
        "inputs.accept_domain",
    }
    assert "secrets." not in yaml.safe_dump(build)


def test_job_runs_only_from_main_in_its_own_concurrency_group() -> None:
    assert JOB["if"] == "${{ github.ref == 'refs/heads/main' }}"
    assert JOB["concurrency"] == {
        "group": "coolify-sales-company-merge",
        "cancel-in-progress": False,
    }
    ops = yaml.safe_load((WORKFLOWS / "coolify-ops.yml").read_text(encoding="utf-8"))
    taken = {
        (job.get("concurrency") or {}).get("group") for job in ops["jobs"].values()
    }
    assert JOB["concurrency"]["group"] not in taken
    names = {(job.get("env") or {}).get("TASK_NAME") for job in ops["jobs"].values()}
    assert JOB["env"]["TASK_NAME"] not in names


def test_raw_execution_text_goes_only_into_the_filter() -> None:
    run = _step("Uruchom zadanie i odczytaj raport")["run"]
    uses = re.findall(r".{0,13}\$\{?execs\b.{0,3}", run)
    assert uses and all(use.startswith("printf '%s' \"$execs\" |") for use in uses)
    assert "python3 .github/scripts/sales_company_merge_report.py" in run
    assert "$msg" not in run and ".message" not in run.replace(".message // .error", "")
    assert 'exit "$rc"' in run


# Coolify z pliku: lista zadań w $STUB/tasks.json, kolejne odpowiedzi z wykonaniami
# w $STUB/exec_<n>.json (po ostatniej powtarza się ostatnia), każde wywołanie
# zapisane w $STUB/calls. `date` przesuwa zegar o 5 minut na każde `+%s`, więc
# 20 minut oczekiwania to trzy odczyty wykonań, a `sleep` nie czeka.
_CURL_STUB = r"""#!/bin/bash
out=""; fmt=""; method="GET"; url=""; fail=""
while [ $# -gt 0 ]; do
  case "$1" in
    -o) out="$2"; shift 2;;
    -w) fmt="$2"; shift 2;;
    -X) method="$2"; shift 2;;
    -H|-d) shift 2;;
    -fsS) fail=1; shift;;
    http*) url="$1"; shift;;
    *) shift;;
  esac
done
echo "$method ${url#https://coolify.example}" >> "$STUB/calls"
code=200
body=""
case "$method $url" in
  "GET "*/scheduled-tasks)
    [ -e "$STUB/list_down" ] && exit 7
    if [ -e "$STUB/list_body" ]; then body=$(cat "$STUB/list_body"); else body=$(cat "$STUB/tasks.json"); fi;;
  "POST "*)
    jq -c --arg n "$TASK_NAME" '. + [{name: $n, uuid: "task-1"}]' "$STUB/tasks.json" > "$STUB/t"
    mv "$STUB/t" "$STUB/tasks.json"
    body='{"uuid":"task-1"}';;
  "DELETE "*)
    code=$(cat "$STUB/delete_code" 2>/dev/null || echo 200)
    if [ "$code" = 000 ]; then [ -n "$fmt" ] && printf 000; exit 7; fi
    if [ "$code" -lt 300 ]; then
      jq -c --arg u "${url##*/}" 'map(select(.uuid != $u))' "$STUB/tasks.json" > "$STUB/t"
      mv "$STUB/t" "$STUB/tasks.json"
    fi;;
  "GET "*/executions)
    n=$(( $(cat "$STUB/exec_n" 2>/dev/null || echo 0) + 1 ))
    echo "$n" > "$STUB/exec_n"
    last=$(ls "$STUB" | grep -c '^exec_[0-9]*\.json$')
    [ "$n" -le "$last" ] || n=$last
    body=$(cat "$STUB/exec_$n.json");;
esac
if [ -n "$fail" ] && [ "$code" -ge 400 ]; then exit 22; fi
if [ -n "$out" ]; then printf '%s' "$body" > "$out"; else printf '%s' "$body"; fi
[ -n "$fmt" ] && printf '%s' "$code"
exit 0
"""
_DATE_STUB = r"""#!/bin/bash
t=$(cat "$STUB/clock" 2>/dev/null || echo 1800000000)
case "$*" in
  *%s*) t=$((t + 300)); echo "$t" > "$STUB/clock"; echo "$t";;
  *) echo 12:00:00;;
esac
"""
TASK = {"name": JOB["env"]["TASK_NAME"], "uuid": "task-1"}
PENDING = [{"status": "running", "message": f"{MARKER} postęp"}]
LOCKED = [_execution(f"{MARKER}\n{LOCK_LINE}"), *PENDING]


def _run_step(name: str, stub: Path, env: dict[str, str]) -> tuple[int, str]:
    result = subprocess.run(
        ["bash", "-c", _step(name)["run"]],
        cwd=ROOT,
        env={
            "PATH": f"{stub}:{os.environ['PATH']}",
            "STUB": str(stub),
            "CO_URL": "https://coolify.example/",
            "CO_TOKEN": "t",
            "APP_UUID": "app",
            "TASK_NAME": JOB["env"]["TASK_NAME"],
            "SENTINEL": SENTINEL,
            "CMD": "cd /app && true",
            **env,
        },
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def _job(
    responses: list[list[dict]],
    mode: str = "dry-run",
    *,
    tasks: Sequence[dict] = (),
    delete_code: str = "",
    before_cleanup: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Krok odczytu i krok sprzątania jak w jobie, z podstawionym Coolify."""
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp)
        for name, body in (
            ("curl", _CURL_STUB),
            ("date", _DATE_STUB),
            ("sleep", "#!/bin/bash\nexit 0\n"),
        ):
            (stub / name).write_text(body, encoding="utf-8")
            (stub / name).chmod(0o755)
        (stub / "tasks.json").write_text(json.dumps(list(tasks)), encoding="utf-8")
        for n, payload in enumerate(responses, start=1):
            (stub / f"exec_{n}.json").write_text(json.dumps(payload), encoding="utf-8")
        if delete_code:
            (stub / "delete_code").write_text(delete_code, encoding="utf-8")
        github_env = stub / "github_env"
        github_env.touch()
        run_code, run_log = _run_step(
            "Uruchom zadanie i odczytaj raport",
            stub,
            {"MODE": mode, "GITHUB_ENV": str(github_env)},
        )
        for name, body in (before_cleanup or {}).items():
            (stub / name).write_text(body, encoding="utf-8")
        carried = dict(
            line.split("=", 1) for line in github_env.read_text().splitlines()
        )
        cleanup_code, cleanup_log = _run_step(
            "Skasuj zadanie jednorazowe", stub, carried
        )
        return {
            "run": (run_code, run_log),
            "cleanup": (cleanup_code, cleanup_log),
            "carried": carried,
            "calls": (stub / "calls").read_text().splitlines(),
            "tasks": json.loads((stub / "tasks.json").read_text()),
        }


@pytest.mark.parametrize(
    ("text", "mode", "expected"),
    [
        (json.dumps(REPORT, indent=2), "dry-run", 0),
        (json.dumps(APPLIED, indent=2), "apply", 0),
        ("Błąd: OperationalError", "apply", 1),
        ("Odmowa, nic nie zapisano: --expect-merge 3, a jest 4", "apply", 2),
        (DIFFERS_LINE, "apply", 3),
        (LOCK_LINE, "apply", 4),
    ],
)
def test_job_waits_ends_with_the_script_code_and_deletes_the_task(
    text: str, mode: str, expected: int
) -> None:
    final = [_execution(f"{MARKER}\n{text}")]
    if expected != 4:
        final += LOCKED
    job = _job([[], PENDING, final], mode)
    code, log = job["run"]
    assert code == expected, log
    assert MARKER not in log
    assert sum(call.endswith("/executions") for call in job["calls"]) == 3
    if expected == 0:
        assert f'"mode": "{mode}"' in log and '"domains_to_set": 27' in log
    else:
        assert f"::error::Kod {expected}:" in log
    assert job["carried"] == {"TASK_REQUESTED": "1", "TASK_UUID": "task-1"}
    assert job["cleanup"][0] == 0 and "skasowane" in job["cleanup"][1]
    assert job["tasks"] == []


def test_no_result_in_20_minutes_is_red_and_the_task_is_still_deleted() -> None:
    job = _job([PENDING], "apply")
    code, log = job["run"]
    assert code == 1
    assert "brak wyniku w 20 minut" in log and MARKER not in log
    assert sum(call.endswith("/executions") for call in job["calls"]) == 3
    assert job["cleanup"][0] == 0 and job["tasks"] == []


@pytest.mark.parametrize(
    "broken",
    [
        {"delete_code": "500"},
        {"delete_code": "000"},
        {"before_cleanup": {"list_down": ""}},
        {"before_cleanup": {"list_body": '{"message": "Unauthenticated."}'}},
    ],
)
def test_cleanup_is_red_unless_the_task_is_gone_from_the_list(broken: dict) -> None:
    job = _job([[_execution(json.dumps(REPORT))]], **broken)
    assert job["run"][0] == 0, job["run"][1]
    code, log = job["cleanup"]
    assert code == 1, log
    assert "::error::" in log and "skasuj je w panelu Coolify" in log
    assert "skasowane" not in log


def test_cleanup_finds_the_task_by_name_when_its_uuid_is_unknown() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp)
        (stub / "curl").write_text(_CURL_STUB, encoding="utf-8")
        (stub / "curl").chmod(0o755)
        (stub / "tasks.json").write_text(json.dumps([TASK]), encoding="utf-8")
        code, log = _run_step(
            "Skasuj zadanie jednorazowe", stub, {"TASK_REQUESTED": "1"}
        )
        assert code == 0, log
        assert (
            "DELETE /api/v1/applications/app/scheduled-tasks/task-1"
            in (stub / "calls").read_text()
        )
        assert json.loads((stub / "tasks.json").read_text()) == []


def test_leftover_of_an_earlier_run_is_deleted_before_a_new_task() -> None:
    leftover = {**TASK, "uuid": "old-1"}
    job = _job([[_execution(json.dumps(REPORT))]], tasks=[leftover])
    assert job["run"][0] == 0, job["run"][1]
    calls = job["calls"]
    deleted = calls.index("DELETE /api/v1/applications/app/scheduled-tasks/old-1")
    created = calls.index("POST /api/v1/applications/app/scheduled-tasks")
    assert deleted < created
    assert job["tasks"] == []


@pytest.mark.parametrize(
    "broken",
    [{"delete_code": "500"}, {"delete_code": "000"}],
)
def test_leftover_that_stays_blocks_a_second_task(broken: dict) -> None:
    leftover = {**TASK, "uuid": "old-1"}
    job = _job([[_execution(json.dumps(REPORT))]], tasks=[leftover], **broken)
    code, log = job["run"]
    assert code == 1 and "nie dała się skasować" in log
    assert not any(call.startswith("POST") for call in job["calls"])
    assert "TASK_REQUESTED" not in job["carried"]
    assert job["cleanup"][0] == 0 and "nie zakładał" in job["cleanup"][1]


def test_unreadable_task_list_creates_nothing() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        stub = Path(tmp)
        (stub / "curl").write_text(_CURL_STUB, encoding="utf-8")
        (stub / "curl").chmod(0o755)
        (stub / "tasks.json").write_text("[]", encoding="utf-8")
        (stub / "list_body").write_text('{"message": "x"}', encoding="utf-8")
        github_env = stub / "github_env"
        github_env.touch()
        code, log = _run_step(
            "Uruchom zadanie i odczytaj raport",
            stub,
            {"MODE": "apply", "GITHUB_ENV": str(github_env)},
        )
        assert code == 1 and "nic nie założono" in log
        assert "POST" not in (stub / "calls").read_text()
        assert github_env.read_text() == ""


def test_one_shot_task_is_deleted_on_every_result() -> None:
    cleanup = JOB["steps"][-1]
    assert cleanup["if"] == "${{ always() }}"


# ── Zgodność ze skryptem ─────────────────────────────────────────────────────


def _script() -> ast.Module:
    return ast.parse(SCRIPT.read_text(encoding="utf-8"))


def _text(node: ast.expr) -> str:
    """Treść komunikatu; wartości wstawiane w f-stringu to u nas same liczby."""
    if isinstance(node, ast.JoinedStr):
        return "".join(
            part.value if isinstance(part, ast.Constant) else "7"
            for part in node.values
        )
    assert isinstance(node, ast.Constant) and isinstance(node.value, str)
    return node.value


def test_filter_knows_exactly_the_fields_of_the_script_report() -> None:
    report = next(
        node
        for node in ast.walk(_script())
        if isinstance(node, ast.ClassDef) and node.name == "Report"
    )
    fields = {
        item.target.id: ast.unparse(item.annotation)
        for item in report.body
        if isinstance(item, ast.AnnAssign)
    }
    assert fields.pop("mode") == "str"
    assert {k for k, kind in fields.items() if kind == "int"} == reporter.COUNTERS
    assert {
        k for k, kind in fields.items() if kind == "dict[str, int]"
    } == reporter.BREAKDOWNS


def test_filter_knows_every_refusal_the_workflow_can_trigger() -> None:
    reasons = {
        _text(node.args[0])
        for node in ast.walk(_script())
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "Refused"
    }
    assert reasons, "skrypt nie ma już odmów albo zmienił nazwę wyjątku"
    # Workflow nie podaje pliku z nazwami ani pliku listy.
    reachable = {
        re.sub(r"\d+", "N", reason)
        for reason in reasons
        if not reason.startswith(("--names-file", "--list-out"))
    }
    assert reachable == reporter.KNOWN_REFUSALS


def test_filter_reads_the_lines_and_codes_the_script_really_prints() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    constants = {
        node.targets[0].id: node.value.value
        for node in _script().body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.startswith("EXIT_")
    }
    assert constants == {
        "EXIT_OK": reporter.EXIT_OK,
        "EXIT_ERROR": reporter.EXIT_ERROR,
        "EXIT_REFUSED": reporter.EXIT_REFUSED,
        "EXIT_RESULT_DIFFERS": reporter.EXIT_RESULT_DIFFERS,
        "EXIT_ALREADY_RAN": reporter.EXIT_ALREADY_RAN,
    }
    assert reporter.EXIT_PENDING not in constants.values()
    for printed in (
        'f"lock {lock} exists — already ran"',
        'f"Odmowa, nic nie zapisano: {exc}"',
        f'"{DIFFERS_LINE}"',
        'f"Błąd: {type(exc).__name__}"',
    ):
        assert printed in source, printed
    assert r'r"/tmp/nexus-sales-company-merge-\d+"' in source


def test_every_flag_of_the_command_exists_in_the_script() -> None:
    _, command, _ = _build(
        "apply",
        expect_merge="3",
        expect_domains="27",
        actor_id="82",
        decide="12:34",
        company_ids="7",
        accept_domain="12",
    )
    source = SCRIPT.read_text(encoding="utf-8")
    flags = set(re.findall(r"--[a-z-]+", command))
    assert flags == {
        "--apply",
        "--actor-id",
        "--expect-merge",
        "--expect-domains",
        "--decide",
        "--company-ids",
        "--accept-domain",
        "--lock",
    }
    for flag in flags:
        assert f'add_argument("{flag}"' in source, flag
    assert "python -m scripts.sales_company_merge " in command
