"""Read execution metadata for one known CV diagnostic; never run or delete it."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re

spec = importlib.util.spec_from_file_location(
    "cv_ops", Path(__file__).with_name("cv-quality-ops.py")
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


def inspect(api, identity):
    identity = ops.checked(identity, r"[1-9][0-9]{0,19}-[1-9][0-9]{0,2}")
    name = ops.PREFIX + identity
    rows = [row for row in api.inventory() if row.get("name") == name]
    if len(rows) != 1:
        raise ops.OpsError("task_missing_or_ambiguous")
    task_id = ops.checked(rows[0].get("uuid"), r"[A-Za-z0-9-]{1,80}")
    executions = api.request("GET", f"{api.tasks}/{task_id}/executions")
    if not isinstance(executions, list):
        raise ops.OpsError("invalid_executions")
    result = []
    for execution in executions:
        message = execution.get("message") or ""
        if not isinstance(message, str):
            raise ops.OpsError("invalid_execution_message")
        status = execution.get("status")
        exit_match = re.search(r"CV_QUALITY_EXIT=([0-9]{1,3})", message)
        reasons = [
            label
            for literal, label in [
                ("No such file", "file_missing"),
                ("not found", "command_missing"),
                ("Permission denied", "permission_denied"),
                ("syntax error", "shell_syntax"),
                ("restarting", "container_restarting"),
                ("not running", "container_not_running"),
                ("no such container", "container_missing"),
                ("cannot cd", "working_directory_missing"),
                ("can't cd", "working_directory_missing"),
                ("exit code", "execution_failed"),
                ("terminated", "terminated"),
                ("timed out", "timeout"),
                ("killed", "killed"),
                ("Traceback", "python_exception"),
                ("deployment_revision_mismatch", "revision_mismatch"),
            ]
            if literal.lower() in message.lower()
        ]
        result.append(
            {
                "status": status
                if status in {"success", "failed", "running", "in_progress", "pending"}
                else "unknown",
                "message_bytes": len(message.encode()),
                "message_sha256": hashlib.sha256(message.encode()).hexdigest(),
                "has_payload": ops.BEGIN in message and ops.END in message,
                "has_completion": ops.DONE in message,
                "exit_code": int(exit_match.group(1)) if exit_match else None,
                "diagnostic_signals": reasons,
            }
        )
    return {
        "task_name": name,
        "task_uuid": task_id,
        "returned_executions": len(result),
        "executions": result,
    }


def main():
    try:
        result = inspect(ops.Api(os.environ), os.environ.get("INSPECT_RUN_ID"))
    except ops.OpsError as error:
        print(json.dumps({"outcome": str(error)}))
        return 2
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
