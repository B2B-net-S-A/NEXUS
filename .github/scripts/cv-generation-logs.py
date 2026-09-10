"""Read bounded CV/provider diagnostics; never export source text or raw logs."""

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


if __name__ == "__main__":
    try:
        main()
    except ops.OpsError as exc:
        print(json.dumps({"error": str(exc)}))
        raise SystemExit(2) from None
