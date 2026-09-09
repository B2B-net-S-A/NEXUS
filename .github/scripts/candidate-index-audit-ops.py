"""Run fixed index audit/repair commands through Coolify's scheduled-task API."""

import json
import math
import os
import re
import time
import urllib.request
from pathlib import Path

PREFIX = "NEXUS_INDEX_AUDIT_RESULT="
REPAIR_PREFIX = "NEXUS_INDEX_REPAIR_RESULT="
DIAGNOSTICS_PREFIX = "NEXUS_SEARCH_DIAGNOSTICS_RESULT="


def extract_diagnostics_report(executions):
    def number(value):
        if value is not None and (
            type(value) not in (int, float) or not math.isfinite(value) or value < 0
        ):
            raise ValueError("Invalid diagnostic number")
        return value

    def boolean(value):
        if value is not None and type(value) is not bool:
            raise ValueError("Invalid diagnostic flag")
        return value

    def label(value):
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value):
            raise ValueError("Invalid diagnostic label")
        return value

    def metrics(value):
        return {
            **{
                key: number(value.get(key))
                for key in (
                    "elapsed_ms",
                    "estimated_cost_usd",
                    "query_calls",
                    "query_failed",
                    "provider_calls",
                    "provider_failed",
                    "observed_tokens",
                    "unpriced_calls",
                )
            },
            **{
                key: boolean(value.get(key))
                for key in (
                    "cost_complete",
                    "accounting_complete",
                )
            },
        }

    def counters(value, allowed):
        if not isinstance(value, dict) or set(value) - set(allowed):
            raise ValueError("Unexpected diagnostic counter")
        if any(type(n) is not int or n < 0 for n in value.values()):
            raise ValueError("Invalid diagnostic count")
        return dict(value)

    for execution in executions:
        for line in (execution.get("message") or "").splitlines():
            if not line.startswith(DIAGNOSTICS_PREFIX):
                continue
            data = json.loads(line[len(DIAGNOSTICS_PREFIX) :])
            if data.get("ok") is not True:
                raise RuntimeError("Runtime diagnostics failed")
            runtime, queue, probe = (
                data["runtime"],
                data["queue"],
                data["synthetic_query_probe"],
            )
            recent = data["recent_runs"]
            if not isinstance(recent, list) or len(recent) > 10:
                raise ValueError("Unbounded diagnostic runs")
            runs = []
            for run in recent:
                if run["state"] not in {"queued", "running", "complete", "partial"}:
                    raise ValueError("Invalid search state")
                if not re.fullmatch(r"[0-9a-f-]{36}", run["run_id"]):
                    raise ValueError("Invalid diagnostic run ID")
                runs.append(
                    {
                        "run_id": run["run_id"],
                        "state": run["state"],
                        "population": number(run["population"]),
                        "query_characters": number(run["query_characters"]),
                        "measurement_counts": counters(
                            run["measurement_counts"],
                            (
                                "measured",
                                "unavailable",
                                "stale",
                                "missing_index",
                                "pending",
                            ),
                        ),
                        **metrics(run),
                    }
                )
            summary = data["metrics_24h"]
            return {
                "runtime": {
                    **{
                        key: label(runtime[key])
                        for key in ("embedding_model", "collection")
                    },
                    **{
                        key: boolean(runtime[key])
                        for key in ("key_present", "worker_enabled")
                    },
                    **{
                        key: number(runtime[key])
                        for key in (
                            "worker_batch",
                            "worker_interval_seconds",
                            "usd_per_million_tokens",
                        )
                    },
                },
                "queue": {
                    "by_status": counters(
                        queue["by_status"],
                        (
                            "pending",
                            "processing",
                            "failed",
                            "done",
                            "dead",
                        ),
                    ),
                    **{
                        key: number(queue[key])
                        for key in (
                            "queue_depth",
                            "oldest_pending_age_seconds",
                            "dead",
                        )
                    },
                },
                "recent_runs": runs,
                "metrics_24h": {
                    **{
                        key: number(summary[key])
                        for key in (
                            "runs",
                            "partial_runs",
                            "latency_unknown_runs",
                            "cost_unknown_runs",
                            "known_cost_subtotal_usd",
                            "elapsed_p95_ms",
                            "latency_samples",
                            "fully_priced_runs",
                            "mean_estimated_cost_usd_for_priced_runs",
                            "estimated_total_cost_usd",
                            "sample_limit",
                        )
                    },
                    "sample_truncated": boolean(summary["sample_truncated"]),
                },
                "synthetic_query_probe": {
                    "ok": boolean(probe["ok"]),
                    "dimensions": number(probe["dimensions"]),
                    "error_type": label(probe["error_type"]),
                    **metrics(probe),
                },
            }
    return None


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
    if mode not in {"audit", "repair", "diagnostics"}:
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
        module = (
            "run_candidate_search_diagnostics_once"
            if mode == "diagnostics"
            else "run_candidate_index_audit_once"
        )
        command = f"cd /app && python -m scripts.{module} --run-identity {identity}"
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
                extract_diagnostics_report(executions)
                if mode == "diagnostics"
                else extract_report(executions)
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
