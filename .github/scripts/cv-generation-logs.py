"""Read bounded CV/provider diagnostics; never export source text or raw logs."""

import importlib.util
import ast
import base64
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.parse
import urllib.request

spec = importlib.util.spec_from_file_location(
    "cv_ops", Path(__file__).with_name("cv-quality-ops.py")
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


def project(logs):
    events = []
    for line in logs.splitlines():
        if not any(tag in line for tag in ("[cv_b2b]", "[claude_client]", "CV durable job", "CV job recovery")):
            continue
        item = {}
        timestamp = re.search(r"\d{4}-\d{2}-\d{2}[T ][\d:.,]+Z?", line)
        if timestamp:
            item["at"] = timestamp.group()
        request = re.search(r"\[cv_b2b\]\[([a-zA-Z0-9_:-]{1,100})\]", line)
        if request:
            item["request"] = request.group(1)
        model = re.search(r"model=([a-zA-Z0-9_.-]{1,100})", line)
        if model:
            item["model"] = model.group(1)
        attempt = re.search(r"próba (\d+)/(\d+)", line)
        if attempt:
            item["attempt"] = [int(v) for v in attempt.groups()]
        elapsed = re.search(r"sukces w (\d+)ms", line)
        if elapsed:
            item["elapsed_ms"] = int(elapsed.group(1))
        codes = []
        for literal, code in (
            ("start model=", "started"),
            ("sukces w", "succeeded"),
            ("Request timed out", "timeout"),
            ("Connection error", "connection_error"),
            ("Error code: 529", "overloaded_529"),
            ("Error code: 429", "rate_limit_429"),
            ("Error code: 400", "request_400"),
            ("Error code: 404", "model_404"),
            ("wyczerpany", "fallback"),
            ("stop_reason=max_tokens", "truncated"),
            ("source extraction rejected:", "source_rejected"),
            ("invalid_extraction", "invalid_extraction"),
            ("invalid_evidence_path", "invalid_evidence_path"),
            ("invalid_evidence", "invalid_evidence"),
            ("unbound_fact", "unbound_fact"),
            ("CV durable job failed", "worker_failed"),
            ("CV job recovery iteration failed", "recovery_failed"),
        ):
            if literal in line:
                codes.append(code)
        item["signals"] = codes
        if codes:
            events.append(item)
    return {"events": events[-250:], "matching_events": len(events)}


def backend_events(api, app):
    """Use the existing log sink; never return credentials or raw log lines."""
    rows = api.request("GET", f"/api/v1/applications/{app}/envs")
    if not isinstance(rows, list):
        raise ops.OpsError("invalid_environment_response")
    wanted = {"GRAFANA_LOKI_URL", "GRAFANA_LOKI_USER", "GRAFANA_LOKI_TOKEN"}
    settings = {row.get("key"): row.get("value") for row in rows if row.get("key") in wanted}
    if not all(isinstance(settings.get(key), str) and settings[key] for key in wanted):
        raise ops.OpsError("log_sink_unconfigured")
    base = settings["GRAFANA_LOKI_URL"].rstrip("/")
    if not re.fullmatch(r"https://[a-zA-Z0-9.-]+\.grafana\.net", base):
        raise ops.OpsError("unexpected_log_sink")
    query = urllib.parse.urlencode({
        "query": '{app="nexus",service="backend"} |~ "source extraction rejected|final factual review rejected"',
        "since": "6h", "limit": 250, "direction": "backward",
    })
    credential = base64.b64encode((settings["GRAFANA_LOKI_USER"] + ":" + settings["GRAFANA_LOKI_TOKEN"]).encode()).decode()
    request = urllib.request.Request(base + "/loki/api/v1/query_range?" + query, headers={"Authorization": "Basic " + credential})
    try:
        with urllib.request.build_opener(ops.NoRedirect).open(request, timeout=30) as response:
            raw = response.read(2_000_001)
        if len(raw) > 2_000_000:
            raise ops.OpsError("log_sink_response_too_large")
        result = json.loads(raw)
        lines = [value[1] for stream in result["data"]["result"] for value in stream["values"]]
    except urllib.error.HTTPError as error:
        raise ops.OpsError("log_sink_http_" + str(error.code)) from None
    except (OSError, ValueError, KeyError, TypeError):
        raise ops.OpsError("log_sink_unavailable") from None
    return project("\n".join(lines))


def main():
    api = ops.Api(os.environ)
    app = ops.checked(os.environ["APP_UUID"], r"[A-Za-z0-9-]{1,80}")
    try:
        print(json.dumps({"backend": backend_events(api, app)}, indent=2))
    except ops.OpsError as error:
        print(json.dumps({"backend": str(error)}))
    return
    response = api.request("GET", f"/api/v1/applications/{app}/logs?lines=10000")
    if not isinstance(response, dict) or not isinstance(response.get("logs"), str):
        raise ops.OpsError("invalid_log_response")
    print(json.dumps(project(response["logs"]), indent=2))
    # The task command column is limited to 255 characters. Both fixed probes
    # only SELECT bounded metadata; no source content or arbitrary SQL input.
    queries = {
        "jobs": "select id,generated_id,status,created_at::text from cv_generation_jobs order by id desc limit 6",
        "calls": "select model,latency_ms,input_tokens,output_tokens from ai_provider_calls order by created_at desc limit 6",
    }
    identity = ops.checked(os.environ["GITHUB_RUN_ID"], r"[1-9][0-9]{0,19}")
    owned_ids = {}
    try:
        for label, query in queries.items():
            name = "nexus-cv-state-" + identity + "-" + label
            code = 'import os,psycopg2;c=psycopg2.connect(os.environ["DATABASE_URL"].replace("+asyncpg","")).cursor();c.execute("' + query + '");print(c.fetchall())'
            command = "python -c '" + code + "'"
            if len(command) > 255:
                raise ops.OpsError("probe_command_too_long")
            api.request("POST", api.tasks, {"name": name, "command": command, "frequency": "* * * * *", "container": "backend", "enabled": True})
            owned = [t for t in api.inventory() if t.get("name") == name and t.get("command") == command]
            if len(owned) != 1:
                raise ops.OpsError("ambiguous_probe_task")
            owned_ids[label] = ops.checked(owned[0]["uuid"], r"[A-Za-z0-9-]{1,80}")
        deadline = time.monotonic() + 100
        found = set()
        while time.monotonic() < deadline:
            for label, task_id in owned_ids.items():
                if label in found:
                    continue
                executions = api.request("GET", f"{api.tasks}/{task_id}/executions")
                for execution in executions:
                    for line in (execution.get("message") or "").splitlines():
                        if not line.startswith("[("):
                            continue
                        try:
                            rows = ast.literal_eval(line)
                        except (ValueError, SyntaxError):
                            raise ops.OpsError("invalid_metadata") from None
                        if not isinstance(rows, list) or len(rows) > 6:
                            raise ops.OpsError("invalid_metadata")
                        print(json.dumps({label: rows}), flush=True)
                        found.add(label)
            if len(found) == len(queries):
                return
            time.sleep(10)
        raise ops.OpsError("probe_timeout")
    finally:
        for task_id in owned_ids.values():
            api.request("DELETE", f"{api.tasks}/{task_id}")


if __name__ == "__main__":
    try:
        main()
    except ops.OpsError as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(2) from None
