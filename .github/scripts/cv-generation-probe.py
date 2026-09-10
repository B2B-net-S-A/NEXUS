"""Run the selected source module in a disposable process, without publishing CVs."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import time
import urllib.parse
import urllib.request

spec = importlib.util.spec_from_file_location(
    "cv_ops", Path(__file__).with_name("cv-quality-ops.py")
)
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)


def main():
    api = ops.Api(os.environ)
    identity = ops.checked(os.environ["GITHUB_RUN_ID"], r"[1-9][0-9]{0,19}")
    scope = ops.checked(os.environ["PROBE_SCOPE"], r"[1-9][0-9]{0,19}:[a-f0-9]{64}")
    job, fingerprint = scope.split(":")
    sha = ops.checked(os.environ["GITHUB_SHA"], r"[a-f0-9]{40}")
    module = "backend/app/services/cv_generator_b2b/source_facts.py"
    repository = "B2B-net-S-A/NEXUS"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/contents/{module}?ref={sha}",
        headers={
            "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "Accept": "application/vnd.github+json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            download = json.load(response)["download_url"]
    except Exception:
        raise ops.OpsError("source_download_unavailable") from None
    parsed = urllib.parse.urlparse(download)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "raw.githubusercontent.com"
        or parsed.path != f"/{repository}/{sha}/{module}"
    ):
        raise ops.OpsError("unexpected_source_url")
    # The short-lived, file-scoped download URL stays inside the trusted task
    # transport. Never print the command, remote logs, URL or bearer tokens.
    command = f"curl -fsS {shlex.quote(download)}|python - {job} {identity} {fingerprint[:16]}"
    if len(command) > 255:
        raise ops.OpsError("probe_command_too_long")
    name = "nexus-cv-probe-" + identity
    if any(task.get("name") == name for task in api.inventory()):
        raise ops.OpsError("probe_already_exists")
    registered = False
    owned_ids = set()
    try:
        registered = True
        api.request(
            "POST",
            api.tasks,
            {
                "name": name,
                "command": command,
                "frequency": "* * * * *",
                "container": "backend",
                "enabled": True,
                "timeout": 1200,
            },
        )
        owned = [
            task
            for task in api.inventory()
            if task.get("name") == name and task.get("command") == command
        ]
        if len(owned) != 1:
            raise ops.OpsError("ambiguous_probe_task")
        task_id = ops.checked(owned[0]["uuid"], r"[A-Za-z0-9-]{1,80}")
        owned_ids.add(task_id)
        print(
            json.dumps(
                {
                    "probe_dispatched": True,
                    "job_id": int(job),
                    "code_sha": sha,
                    "module_sha256": hashlib.sha256(
                        Path(module).read_bytes()
                    ).hexdigest(),
                }
            ),
            flush=True,
        )
        deadline = time.monotonic() + 1150
        while time.monotonic() < deadline:
            executions = api.request("GET", f"{api.tasks}/{task_id}/executions")
            for execution in executions:
                for line in (execution.get("message") or "").splitlines():
                    if not line.startswith("CV_PROBE="):
                        continue
                    report = json.loads(line.removeprefix("CV_PROBE="))
                    if not isinstance(report, dict) or set(report) - {
                        "outcome",
                        "job_id",
                        "cv_sha256",
                        "runtime_sha",
                        "code",
                        "fields",
                        "source_version",
                        "source_roles",
                        "rendered_roles",
                        "verified",
                        "verified_claims",
                        "docx_bytes",
                        "docx_sha256",
                    }:
                        raise ops.OpsError("invalid_probe_report")
                    if report.get("cv_sha256") not in (None, fingerprint):
                        raise ops.OpsError("probe_source_mismatch")
                    print(json.dumps({"code_sha": sha, "report": report}), flush=True)
                    return
            time.sleep(15)
        raise ops.OpsError("probe_timeout")
    finally:
        try:
            if registered:
                owned_ids.update(
                    ops.checked(task["uuid"], r"[A-Za-z0-9-]{1,80}")
                    for task in api.inventory()
                    if task.get("name") == name and task.get("command") == command
                )
        finally:
            failures = []
            for task_id in owned_ids:
                try:
                    api.request("DELETE", f"{api.tasks}/{task_id}")
                except ops.OpsError:
                    failures.append(task_id)
            if failures:
                raise ops.OpsError("probe_cleanup_failed")


if __name__ == "__main__":
    try:
        main()
    except ops.OpsError as error:
        print(json.dumps({"error": str(error)}))
        raise SystemExit(2) from None
    except Exception:
        print(json.dumps({"error": "probe_internal_error"}))
        raise SystemExit(2) from None
