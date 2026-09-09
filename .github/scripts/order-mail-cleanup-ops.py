"""Use the established Coolify scheduled-task transport, with a one-shot guard."""

import base64
import gzip
import json
import os
from pathlib import Path
import re
import time
import urllib.request

base = os.environ["CO_URL"].rstrip("/")
app = os.environ["APP_UUID"]
fp = os.environ.get("PLAN_FINGERPRINT", "")
if fp and not re.fullmatch(r"[0-9a-f]{64}", fp):
    raise ValueError("Invalid audit fingerprint")
run = os.environ["OPS_RUN_ID"] + "-" + os.environ["OPS_RUN_ATTEMPT"]
if not re.fullmatch(r"[0-9]+-[0-9]+", run):
    raise ValueError("Invalid run identity")
name = "order-mail-cleanup-20260909-" + run
endpoint = f"/api/v1/applications/{app}/scheduled-tasks"


def request(path, method="GET", data=None):
    req = urllib.request.Request(
        base + path,
        method=method,
        headers={
            "Authorization": "Bearer " + os.environ["CO_TOKEN"],
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        data=json.dumps(data).encode() if data is not None else None,
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        body = response.read()
        return json.loads(body) if body else None


def matching_tasks():
    return [t for t in request(endpoint) if t.get("name") == name]


if matching_tasks():
    raise RuntimeError("This run already has a task; inspect it before retrying")
command = f"if mkdir /tmp/{name}; then cd /app && python -m scripts.order_mail_cleanup"
if fp:
    command += " --fingerprint " + fp
command += "; fi"
try:
    request(
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
    tasks = matching_tasks()
    if len(tasks) != 1:
        raise RuntimeError("Cannot resolve the exact task")
    task_id = tasks[0]["uuid"]
    if not re.fullmatch(r"[A-Za-z0-9_-]+", task_id):
        raise ValueError("Invalid task identifier")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        executions = request(endpoint + "/" + task_id + "/executions")
        for entry in executions:
            message = entry.get("message") or ""
            if "===ORDER-MAIL-CLEANUP-END===" in message:
                encoded = (
                    message.split("===ORDER-MAIL-CLEANUP-PAYLOAD===", 1)[1]
                    .split("===ORDER-MAIL-CLEANUP-END===", 1)[0]
                    .strip()
                )
                report = json.loads(gzip.decompress(base64.b64decode(encoded)))
                directory = Path(os.environ["RUNNER_TEMP"]) / "order-mail-cleanup"
                directory.mkdir(parents=True, exist_ok=True)
                (directory / "report.json").write_text(
                    json.dumps(report, ensure_ascii=False, indent=2)
                )
                print("Report saved; fingerprint=" + report["fingerprint"])
                raise SystemExit(0)
            if entry.get("status") == "failed":
                # No raw process output: a DB exception may include business data.
                raise RuntimeError(
                    "Backend cleanup failed; inspect its private execution log"
                )
        time.sleep(15)
    raise TimeoutError("Cleanup produced no complete receipt within ten minutes")
finally:
    for task in matching_tasks():
        request(endpoint + "/" + task["uuid"], "DELETE")
    if matching_tasks():
        raise RuntimeError("One-shot task cleanup could not be verified")
