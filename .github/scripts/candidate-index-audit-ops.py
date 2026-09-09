"""Run fixed index audit/repair commands through Coolify's scheduled-task API."""

import json
import os
import re
import time
import urllib.request
from pathlib import Path

PREFIX = "NEXUS_INDEX_AUDIT_RESULT="
REPAIR_PREFIX = "NEXUS_INDEX_REPAIR_RESULT="


def extract_repair_report(executions, fingerprint, audit_identity):
    for execution in executions:
        for line in (execution.get("message") or "").splitlines():
            if not line.startswith(REPAIR_PREFIX):
                continue
            report = json.loads(line[len(REPAIR_PREFIX) :])
            if report.get("ok") is not True:
                raise RuntimeError("Repair did not produce a verified enqueue receipt")
            if (
                report.get("fingerprint") != fingerprint
                or report.get("audit_identity") != audit_identity
            ):
                raise ValueError("Repair receipt does not match the reviewed audit")
            counters = ("queued", "already_pending", "deleted", "orphans_reported_only")
            if any(
                type(report.get(key)) is not int or report[key] < 0 for key in counters
            ):
                raise ValueError("Invalid repair counters")
            if report["deleted"] != 0 or report.get("state") != "enqueued":
                raise ValueError("Unexpected repair operation")
            return {
                key: report[key]
                for key in (*counters, "fingerprint", "audit_identity", "state")
            }
    return None


def extract_report(executions):
    for execution in executions:
        for line in (execution.get("message") or "").splitlines():
            if not line.startswith(PREFIX):
                continue
            report = json.loads(line[len(PREFIX) :])
            if report.get("ok") is not True:
                raise RuntimeError(
                    "Production audit failed or database changed during scan"
                )
            if not re.fullmatch(r"[0-9a-f]{64}", report.get("fingerprint", "")):
                raise ValueError("Invalid report fingerprint")
            numeric = ("population", "index_points", "orphan_points")
            if any(
                type(report.get(key)) is not int or report[key] < 0 for key in numeric
            ):
                raise ValueError("Invalid report counts")
            counts = report.get("counts")
            if not isinstance(counts, dict) or any(
                not re.fullmatch(r"[a-z_]+", key) or type(value) is not int or value < 0
                for key, value in counts.items()
            ):
                raise ValueError("Invalid classification counts")
            if (
                sum(counts.values()) != report["population"]
                or report.get("database_unchanged") is not True
            ):
                raise ValueError("Incomplete population report")
            # A closed projection prevents remote output from exporting extra data.
            return {
                key: report[key]
                for key in (*numeric, "fingerprint", "counts", "database_unchanged")
            }
    return None


def main():
    identity = f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"
    if not re.fullmatch(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}", identity):
        raise ValueError("Invalid run identity")
    mode = os.environ.get("INDEX_MODE", "audit")
    if mode not in {"audit", "repair"}:
        raise ValueError("Unknown index operation")
    audit_identity = os.environ.get("INDEX_AUDIT_IDENTITY", "")
    fingerprint = os.environ.get("INDEX_FINGERPRINT", "")
    if mode == "repair":
        if not re.fullmatch(
            r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}", audit_identity
        ) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
            raise ValueError("Repair requires exact audit identity and fingerprint")
        command = f"cd /app && python -m scripts.run_candidate_index_repair_once --run-identity {identity} --audit-identity {audit_identity} --fingerprint {fingerprint}"
    else:
        if audit_identity or fingerprint:
            raise ValueError("Audit does not accept repair inputs")
        command = f"cd /app && python -m scripts.run_candidate_index_audit_once --run-identity {identity}"
    base = os.environ["CO_URL"].rstrip("/") + "/api/v1"
    app = os.environ["APP_UUID"]
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", app):
        raise ValueError("Invalid application identifier")
    endpoint = f"/applications/{app}/scheduled-tasks"
    name = f"nexus-index-{mode}-{identity}"

    def api(path, method="GET", data=None):
        request = urllib.request.Request(
            base + path,
            data=json.dumps(data).encode() if data is not None else None,
            headers={
                "Authorization": "Bearer " + os.environ["CO_TOKEN"],
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read()
        return json.loads(body) if body else None

    def owned():
        return [task for task in api(endpoint) if task.get("name") == name]

    if owned():
        raise RuntimeError(
            "This run already has a scheduled task; inspect it before retrying"
        )
    try:
        api(
            endpoint,
            "POST",
            {
                "name": name,
                "command": command,
                "frequency": "* * * * *",
                "container": "backend",
                "enabled": True,
            },
        )
        tasks = owned()
        if len(tasks) != 1:
            raise RuntimeError("Cannot identify the created audit task")
        task_id = tasks[0]["uuid"]
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            executions = api(endpoint + f"/{task_id}/executions")
            report = (
                extract_report(executions)
                if mode == "audit"
                else extract_repair_report(executions, fingerprint, audit_identity)
            )
            if report is not None:
                report["run_identity"] = identity
                output = Path(os.environ["RUNNER_TEMP"]) / f"candidate-index-{mode}"
                output.mkdir(exist_ok=True)
                (output / "report.json").write_text(json.dumps(report, indent=2))
                print(json.dumps(report), flush=True)
                return
            time.sleep(20)
        raise TimeoutError("No complete index audit report within 15 minutes")
    finally:
        # Unique identity: never delete another run or an application cron.
        for task in owned():
            api(endpoint + "/" + task["uuid"], "DELETE")
        if owned():
            raise RuntimeError("Audit task cleanup failed")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Network response bodies/provider output may contain sensitive data.
        print(
            f"::error::Index audit did not complete ({type(error).__name__}); inspect task status."
        )
        raise SystemExit(1)
