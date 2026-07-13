#!/usr/bin/env python3
"""Validate livez/readiness payloads and bounded deployment observations."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from _common import ValidationError, parse_utc, read_json, require_sha

SENSITIVE_PATTERN = re.compile(
    r"(?:password|secret|token|authorization|postgres(?:ql)?://|select\s+.+\s+from|stack\s*trace|traceback)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class HealthSample:
    status_code: int
    headers: Mapping[str, str]
    payload: Any


def _check_no_sensitive_values(value: Any, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if SENSITIVE_PATTERN.search(str(key)):
                raise ValidationError(f"health payload contains a sensitive key at {path}.{key}")
            _check_no_sensitive_values(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _check_no_sensitive_values(child, f"{path}[{index}]")
    elif isinstance(value, str) and SENSITIVE_PATTERN.search(value):
        raise ValidationError(f"health payload exposes sensitive implementation detail at {path}")


def validate_payload(
    payload: Any,
    *,
    kind: str,
    expected_sha: str,
    status_code: int | None = None,
    headers: Mapping[str, str] | None = None,
) -> None:
    require_sha(expected_sha, "expected_sha")
    if not isinstance(payload, dict):
        raise ValidationError("health response must be a JSON object")
    _check_no_sensitive_values(payload)
    if payload.get("version") != expected_sha:
        raise ValidationError("health version does not match the exact expected SHA")
    cache_control = "" if headers is None else headers.get("cache-control", headers.get("Cache-Control", ""))
    if headers is not None and "no-store" not in cache_control.lower():
        raise ValidationError("Cache-Control must contain no-store")

    if kind == "livez":
        if set(payload) != {"status", "version"} or payload.get("status") != "alive":
            raise ValidationError("livez must contain only status=alive and version")
        if status_code is not None and status_code != 200:
            raise ValidationError("livez must return HTTP 200")
        return
    if kind != "readiness":
        raise ValidationError("kind must be livez or readiness")

    required = {"status", "version", "deployedAt", "checks"}
    if not required.issubset(payload):
        raise ValidationError("readiness is missing status, version, deployedAt or checks")
    if payload["status"] not in {"healthy", "degraded", "unhealthy"}:
        raise ValidationError("invalid readiness status")
    deployed_at = parse_utc(payload["deployedAt"], "deployedAt")
    if deployed_at.year < 2020:
        raise ValidationError("deployedAt is not a real deployment timestamp")
    checks = payload["checks"]
    if not isinstance(checks, dict) or not isinstance(checks.get("database"), dict):
        raise ValidationError("checks.database is mandatory")
    for name, check in checks.items():
        if not isinstance(check, dict) or check.get("status") not in {"healthy", "degraded", "unhealthy"}:
            raise ValidationError(f"checks.{name}.status is invalid")
        latency = check.get("latencyMs")
        if latency is not None and (not isinstance(latency, int) or isinstance(latency, bool) or latency < 0):
            raise ValidationError(f"checks.{name}.latencyMs must be a non-negative integer")
        if "critical" in check and not isinstance(check["critical"], bool):
            raise ValidationError(f"checks.{name}.critical must be boolean")

    database_status = checks["database"].get("status")
    failed_checks = [name for name, check in checks.items() if check.get("status") != "healthy"]
    failed_critical = [
        name
        for name in failed_checks
        if name == "database" or checks[name].get("critical") is True
    ]
    if database_status != "healthy" or failed_critical:
        if payload["status"] != "unhealthy":
            raise ValidationError("critical dependency failure must make top-level status unhealthy")
        if status_code is not None and status_code != 503:
            raise ValidationError("critical dependency failure must return HTTP 503")
        raise ValidationError("readiness reports a critical dependency failure")
    elif failed_checks:
        if payload["status"] != "degraded":
            raise ValidationError("noncritical dependency failure must make top-level status degraded")
        if status_code is not None and status_code != 200:
            raise ValidationError("degraded readiness must return HTTP 200")
    else:
        if payload["status"] != "healthy":
            raise ValidationError("all healthy checks require top-level healthy")
        if status_code is not None and status_code != 200:
            raise ValidationError("healthy readiness must return HTTP 200")


def fetch_json(url: str, timeout: float) -> HealthSample:
    parsed = urlparse(url)
    if parsed.scheme != "https" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValidationError("health URL must use HTTPS")
    request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "dynaminds-health-gate/1"})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        response = exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ValidationError("health endpoint is unavailable") from exc
    try:
        raw = response.read(256 * 1024 + 1)
        if len(raw) > 256 * 1024:
            raise ValidationError("health response is unexpectedly large")
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValidationError("health response is not valid UTF-8 JSON") from exc
        headers = {key.lower(): value for key, value in response.headers.items()}
        return HealthSample(int(response.status), headers, payload)
    finally:
        response.close()


def observe(
    sample_provider,
    *,
    kind: str,
    expected_sha: str,
    samples: int,
    interval: float,
    failure_threshold: int,
    success_threshold: int,
) -> None:
    if samples < 1 or failure_threshold < 1 or success_threshold < 0:
        raise ValidationError("invalid observation thresholds")
    consecutive_failures = 0
    consecutive_successes = 0
    for index in range(samples):
        try:
            sample = sample_provider()
            validate_payload(
                sample.payload,
                kind=kind,
                expected_sha=expected_sha,
                status_code=sample.status_code,
                headers=sample.headers,
            )
        except ValidationError:
            consecutive_failures += 1
            consecutive_successes = 0
            if consecutive_failures >= failure_threshold:
                raise
        else:
            consecutive_failures = 0
            consecutive_successes += 1
            if success_threshold and consecutive_successes >= success_threshold:
                return
        if index + 1 < samples and interval:
            time.sleep(interval)
    if success_threshold and consecutive_successes < success_threshold:
        raise ValidationError(f"did not reach {success_threshold} consecutive successful samples")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url")
    source.add_argument("--file", type=Path)
    parser.add_argument("--kind", choices=("livez", "readiness"), required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0)
    parser.add_argument("--failure-threshold", type=int, default=1)
    parser.add_argument("--success-threshold", type=int, default=1)
    parser.add_argument("--timeout", type=float, default=10)
    args = parser.parse_args(argv)
    try:
        if args.url:
            provider = lambda: fetch_json(args.url, args.timeout)
        else:
            provider = lambda: HealthSample(200, {"cache-control": "no-store"}, read_json(args.file))
        observe(
            provider,
            kind=args.kind,
            expected_sha=args.expected_sha,
            samples=args.samples,
            interval=args.interval,
            failure_threshold=args.failure_threshold,
            success_threshold=args.success_threshold,
        )
    except ValidationError as exc:
        print(f"health validation failed: {exc}", file=sys.stderr)
        return 1
    print(f"health validation passed: {args.kind}, samples={args.samples}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
