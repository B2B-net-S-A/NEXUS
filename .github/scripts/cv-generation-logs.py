"""Read bounded CV/provider diagnostics; never export source text or raw logs."""

import importlib.util
import base64
import json
import os
from pathlib import Path
import re
import time

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


def main():
    api = ops.Api(os.environ)
    app = ops.checked(os.environ["APP_UUID"], r"[A-Za-z0-9-]{1,80}")
    response = api.request("GET", f"/api/v1/applications/{app}/logs?lines=10000")
    if not isinstance(response, dict) or not isinstance(response.get("logs"), str):
        raise ops.OpsError("invalid_log_response")
    print(json.dumps(project(response["logs"]), indent=2))
    # Coolify's application-log API selects only the first compose container.
    # Read the backend state using its established scheduled-task route.
    identity = ops.checked(os.environ["GITHUB_RUN_ID"], r"[1-9][0-9]{0,19}")
    name = "nexus-cv-state-" + identity
    code = base64.b64encode(Path(__file__).with_name("cv-generation-state.py").read_bytes()).decode()
    command = f"if mkdir /tmp/{name} 2>/dev/null; then cd /app && echo {code} | base64 -d | python; fi"
    task_id = None
    try:
        api.request("POST", api.tasks, {"name": name, "command": command, "frequency": "* * * * *", "container": "backend", "enabled": True})
        owned = [t for t in api.inventory() if t.get("name") == name and t.get("command") == command]
        if len(owned) != 1:
            raise ops.OpsError("ambiguous_probe_task")
        task_id = ops.checked(owned[0]["uuid"], r"[A-Za-z0-9-]{1,80}")
        deadline = time.monotonic() + 100
        while time.monotonic() < deadline:
            executions = api.request("GET", f"{api.tasks}/{task_id}/executions")
            for execution in executions:
                for line in (execution.get("message") or "").splitlines():
                    if line.startswith("CV_GENERATION_STATE="):
                        data = json.loads(line.split("=", 1)[1])
                        print(json.dumps(data, indent=2))
                        return
            time.sleep(10)
        raise ops.OpsError("probe_timeout")
    finally:
        if task_id is not None:
            api.request("DELETE", f"{api.tasks}/{task_id}")


if __name__ == "__main__":
    try:
        main()
    except ops.OpsError as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(2) from None
