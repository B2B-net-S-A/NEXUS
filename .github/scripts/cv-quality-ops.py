"""Run only the checked-in synthetic CV diagnostic through Coolify's task API.

No candidate inputs, arbitrary commands, raw remote logs or provider credentials
cross this interface. A missing/partial execution is not a quality verdict.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import time
import urllib.error
import urllib.request


PREFIX = "nexus-cv-quality-eval-"
BEGIN = "===NEXUS-CV-QUALITY-PAYLOAD-BEGIN==="
END = "===NEXUS-CV-QUALITY-PAYLOAD-END==="
DONE = "===NEXUS-CV-QUALITY-END==="
HEALTH = "https://api.nexus.dynaminds.pl/api/health"


class OpsError(Exception):
    """Only fixed error codes may be printed; never remote bodies or URLs."""


class Interrupted(OpsError):
    """Cancellation must escape the transient network retry loop."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        # Do not forward the Coolify bearer token to a redirect target.
        return None


def checked(value, pattern):
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise OpsError("invalid_input")
    return value


def configuration(env):
    run = checked(env.get("OPS_RUN_ID"), r"[1-9][0-9]{0,19}")
    attempt = checked(env.get("OPS_RUN_ATTEMPT"), r"[1-9][0-9]{0,2}")
    models = checked(env.get("EVAL_MODELS"), r"primary|all")
    count = checked(env.get("EVAL_CASES"), r"[1-9][0-9]?")
    if int(count) > 40:
        raise OpsError("invalid_case_count")
    sha = checked(env.get("EXPECTED_SHA"), r"[a-f0-9]{40}")
    identity = run + "-" + attempt
    # No interpolated shell syntax: inputs are numbers, enum values or a SHA.
    command = (
        f"if mkdir /tmp/nexus-cv-quality-once-{identity} 2>/dev/null; then "
        f"cd /app && bash scripts/run_cv_quality_once.sh {run} {attempt} {models} {count} {sha}; fi"
    )
    return {
        "name": PREFIX + identity,
        "identity": identity,
        "sha": sha,
        "count": int(count),
        "models": models,
        "command": command,
    }


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


class Api:
    def __init__(self, env):
        self.base = env.get("CO_URL", "").rstrip("/")
        self.token = env.get("CO_TOKEN", "")
        app = checked(env.get("APP_UUID"), r"[A-Za-z0-9-]{1,80}")
        self.tasks = f"/api/v1/applications/{app}/scheduled-tasks"
        if not self.base.startswith("https://") or not self.token:
            raise OpsError("missing_credentials")

    def request(self, method, path, payload=None):
        request = urllib.request.Request(
            self.base + path,
            method=method,
            headers={
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload).encode() if payload is not None else None,
        )
        try:
            with urllib.request.build_opener(NoRedirect).open(
                request, timeout=30
            ) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as error:
            raise OpsError("http_" + str(error.code)) from None
        except (OSError, TimeoutError):
            raise OpsError("transport_unknown") from None
        # Successful creation/deletion establishes ownership even if Coolify
        # returns no JSON. Never retry POST after an ambiguous response.
        try:
            return json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            if method in {"POST", "DELETE"}:
                return None
            raise OpsError("invalid_api_response") from None

    def inventory(self):
        value = self.request("GET", self.tasks)
        if not isinstance(value, list) or any(
            not isinstance(row, dict) for row in value
        ):
            raise OpsError("invalid_task_inventory")
        return value


def health_sha():
    try:
        with urllib.request.urlopen(HEALTH, timeout=15) as response:
            data = json.load(response)
        if data.get("status") != "healthy":
            raise OpsError("unhealthy_runtime")
        return data.get("version")
    except (OSError, ValueError):
        raise OpsError("health_unavailable") from None


def metric_report(message, config, corpus_hash):
    if not isinstance(message, str) or DONE not in message:
        return None
    try:
        encoded = message.split(BEGIN, 1)[1].split(END, 1)[0]
        raw = json.loads(base64.b64decode("".join(encoded.split()), validate=True))
        exit_code = int(re.search(r"CV_QUALITY_EXIT=([0-9]{1,3})", message).group(1))
        if not isinstance(raw, dict) or not isinstance(raw.get("results"), list):
            raise ValueError
        rows = []
        for row in raw["results"]:
            # Explicit metric projection: no source text or model explanations.
            selected = {
                key: row[key]
                for key in (
                    "case_id",
                    "requested_model",
                    "actual_models",
                    "operation_id",
                    "expected_supported",
                    "outcome",
                    "passed",
                    "elapsed_ms",
                    "provider_calls",
                    "metering_complete",
                    "input_tokens",
                    "output_tokens",
                    "estimated_cost_usd",
                )
            }
            checked(selected["case_id"], r"[a-z0-9_-]{1,100}")
            checked(selected["requested_model"], r"[A-Za-z0-9._:/-]{1,150}")
            if not isinstance(selected["actual_models"], list):
                raise ValueError
            for model in selected["actual_models"]:
                checked(model, r"[A-Za-z0-9._:/-]{1,150}")
            if selected["operation_id"] is not None:
                checked(selected["operation_id"], r"[A-Za-z0-9-]{1,80}")
            if selected["outcome"] not in {
                "accepted",
                "semantic_rejection",
                "invalid_review",
                "invalid_json",
                "invalid_schema",
                "invalid_coverage",
                "invalid_evidence",
                "provider_error",
            }:
                raise ValueError
            for field in ("expected_supported", "passed", "metering_complete"):
                if type(selected[field]) is not bool:
                    raise ValueError
            for field in (
                "elapsed_ms",
                "provider_calls",
                "input_tokens",
                "output_tokens",
            ):
                if selected[field] is not None and (
                    type(selected[field]) is not int or selected[field] < 0
                ):
                    raise ValueError
            cost = selected["estimated_cost_usd"]
            if cost is not None:
                checked(cost, r"[0-9]+(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
            rows.append(selected)
        if (
            raw.get("runtime_sha") != config["sha"]
            or raw.get("run_identity") != config["identity"]
        ):
            raise OpsError("runtime_revision_or_identity_mismatch")
        if (
            raw.get("corpus_sha256") != corpus_hash
            or raw.get("cases_per_model") != config["count"]
        ):
            raise OpsError("corpus_or_case_count_mismatch")
        models = raw["requested_models"]
        if (
            not isinstance(models, list)
            or not models
            or len(set(models)) != len(models)
        ):
            raise ValueError
        for model in models:
            checked(model, r"[A-Za-z0-9._:/-]{1,150}")
        if config["models"] == "primary" and len(models) != 1:
            raise ValueError
        complete = raw.get("complete") is True
        if complete and (
            len(rows) != len(models) * config["count"]
            or len({(row["requested_model"], row["case_id"]) for row in rows})
            != len(rows)
        ):
            raise ValueError
        # Recompute classifications rather than trusting a remote success flag.
        success = (
            complete
            and exit_code == 0
            and all(
                row["metering_complete"]
                and row["outcome"]
                == ("accepted" if row["expected_supported"] else "semantic_rejection")
                for row in rows
            )
        )
        return {
            "runtime_sha": config["sha"],
            "run_identity": config["identity"],
            "corpus_sha256": corpus_hash,
            "prompt_sha256": checked(raw["prompt_sha256"], r"[a-f0-9]{64}"),
            "requested_models": models,
            "cases_per_model": config["count"],
            "complete": complete,
            "success": success,
            "exit_code": exit_code,
            "replayed_receipt": raw.get("replayed_receipt") is True,
            "results": rows,
        }
    except (ValueError, KeyError, IndexError, AttributeError, TypeError):
        raise OpsError("invalid_metric_report") from None


def run(
    api,
    config,
    directory,
    corpus_hash,
    *,
    clock=time.monotonic,
    sleep=time.sleep,
    health=health_sha,
):
    state = {
        "task_name": config["name"],
        "task_uuid": None,
        "creation": "not_attempted",
        "cleanup": "not_needed",
        "outcome": "unknown",
        "run_identity": config["identity"],
    }
    state_path = directory / "transport.json"
    owned = False
    task_id = None

    def own_task():
        matches = [
            row
            for row in api.inventory()
            if row.get("name") == config["name"]
            and row.get("command") == config["command"]
        ]
        if len(matches) != 1:
            raise OpsError("created_task_identity_unknown")
        return checked(matches[0].get("uuid"), r"[A-Za-z0-9-]{1,80}")

    try:
        atomic_json(state_path, state)
        if health() != config["sha"]:
            raise OpsError("deployment_revision_mismatch")
        if any(str(row.get("name", "")).startswith(PREFIX) for row in api.inventory()):
            raise OpsError("previous_eval_task_requires_inspection")
        state["creation"] = "attempting"
        atomic_json(state_path, state)
        api.request(
            "POST",
            api.tasks,
            {
                "name": config["name"],
                "command": config["command"],
                "frequency": "* * * * *",
                "container": "backend",
                "enabled": True,
            },
        )
        owned = True
        state["creation"] = "confirmed"
        task_id = own_task()
        state["task_uuid"] = task_id
        atomic_json(state_path, state)
        deadline = clock() + 2100
        while clock() < deadline:
            try:
                executions = api.request("GET", f"{api.tasks}/{task_id}/executions")
            except Interrupted:
                raise
            except OpsError:
                sleep(20)
                continue  # Same handle; never launch again after transport failure.
            if not isinstance(executions, list):
                raise OpsError("invalid_executions")
            for execution in executions:
                report = metric_report(execution.get("message"), config, corpus_hash)
                if report:
                    atomic_json(directory / "report.json", report)
                    state["outcome"] = (
                        "passed" if report["success"] else "measurement_failed"
                    )
                    return 0 if report["success"] else 1
            sleep(20)
        raise OpsError("execution_timeout_unknown")
    except OpsError as error:
        state["outcome"] = str(error)
        return 2
    finally:
        if owned:
            try:
                task_id = task_id or own_task()
                state["task_uuid"] = task_id
                api.request("DELETE", f"{api.tasks}/{task_id}")
                if any(row.get("uuid") == task_id for row in api.inventory()):
                    raise OpsError("task_still_exists")
                state["cleanup"] = "confirmed"
            except OpsError:
                state["cleanup"] = "unknown_requires_inspection"
        elif state["creation"] == "attempting":
            state["cleanup"] = "creation_unknown_requires_inspection"
        atomic_json(state_path, state)
        print(json.dumps(state))


def main():
    directory = Path(os.environ["RUNNER_TEMP"]) / "cv-quality"
    try:
        config = configuration(os.environ)
        api = Api(os.environ)
        corpus = (
            Path(__file__).resolve().parents[2]
            / "backend/app/data/cv_quality/factual_gate_v1.json"
        )
        fingerprint = hashlib.sha256(corpus.read_bytes()).hexdigest()

        def interrupted(_signum, _frame):
            raise Interrupted("runner_interrupted")

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        result = run(api, config, directory, fingerprint)
        state = json.loads((directory / "transport.json").read_text())
        return 2 if "unknown" in state["cleanup"] else result
    except OpsError as error:
        atomic_json(directory / "error.json", {"error": str(error)})
        print("CV diagnostic: " + str(error))
        return 2
    except Exception:
        # API failures may carry their response in an exception; no raw logs.
        atomic_json(directory / "error.json", {"error": "unexpected_transport_error"})
        print("CV diagnostic: unexpected_transport_error")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
