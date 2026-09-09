"""Remove only a stopped, fixed-command synthetic CV diagnostic task."""

from __future__ import annotations

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


def cleanup(api, identity):
    identity = ops.checked(identity, r"[1-9][0-9]{0,19}-[1-9][0-9]{0,2}")
    name = ops.PREFIX + identity
    rows = [row for row in api.inventory() if row.get("name") == name]
    if not rows:
        return {"task_name": name, "cleanup": "already_absent"}
    if len(rows) != 1:
        raise ops.OpsError("ambiguous_task")
    command = rows[0].get("command", "")
    run, attempt = identity.split("-")
    match = re.search(
        r"bash scripts/run_cv_quality_once.sh ([1-9][0-9]*) ([1-9][0-9]*) (primary|all) ([1-9][0-9]?) ([a-f0-9]{40}); fi$",
        command,
    )
    if not match or match.group(1, 2) != (run, attempt):
        raise ops.OpsError("foreign_command")
    config = ops.configuration(
        {
            "OPS_RUN_ID": run,
            "OPS_RUN_ATTEMPT": attempt,
            "EVAL_MODELS": match[3],
            "EVAL_CASES": match[4],
            "EXPECTED_SHA": match[5],
        }
    )
    if command != config["command"]:
        raise ops.OpsError("foreign_command")
    task_id = ops.checked(rows[0].get("uuid"), r"[A-Za-z0-9-]{1,80}")
    executions = api.request("GET", f"{api.tasks}/{task_id}/executions")
    if (
        not isinstance(executions, list)
        or not executions
        or any(row.get("status") not in {"success", "failed"} for row in executions)
    ):
        raise ops.OpsError("execution_not_proven_stopped")
    api.request("DELETE", f"{api.tasks}/{task_id}")
    if any(row.get("uuid") == task_id for row in api.inventory()):
        raise ops.OpsError("cleanup_unconfirmed")
    return {"task_name": name, "task_uuid": task_id, "cleanup": "confirmed"}


def main():
    try:
        result = cleanup(ops.Api(os.environ), os.environ.get("INSPECT_RUN_ID"))
    except ops.OpsError as error:
        print(json.dumps({"outcome": str(error)}))
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
