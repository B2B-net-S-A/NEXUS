#!/usr/bin/env python3
"""Set, verify and deploy an exact application SHA through the Coolify API."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from _common import ValidationError, require_https_url, require_sha, write_json

SUCCESS_STATES = {"finished", "succeeded", "success", "completed"}
FAILURE_STATES = {"failed", "error", "cancelled", "canceled"}
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")


@dataclass(frozen=True)
class DeploymentResult:
    application_uuid: str
    requested_sha: str
    previous_sha: str | None
    deployment_id: str


class CoolifyClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 20, opener: Callable[..., Any] | None = None):
        require_https_url(base_url, "Coolify base URL", allow_local_http=True)
        if not token:
            raise ValidationError("COOLIFY_TOKEN is required")
        root = base_url.rstrip("/")
        self.api_base = root if root.endswith("/api/v1") else root + "/api/v1"
        self.token = token
        self.timeout = timeout
        self.opener = opener or urllib.request.urlopen

    def request(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        data = None if payload is None else json.dumps(payload, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            self.api_base + endpoint,
            data=data,
            method=method,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "User-Agent": "dynaminds-exact-sha-release/1",
            },
        )
        try:
            response = self.opener(request, timeout=self.timeout)
        except urllib.error.HTTPError as exc:
            # Deliberately do not echo the response body; it may contain sensitive configuration.
            raise ValidationError(f"Coolify API returned HTTP {exc.code} for {method} {endpoint.split('?')[0]}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise ValidationError(f"Coolify API unavailable for {method} {endpoint.split('?')[0]}") from exc
        try:
            raw = response.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise ValidationError("Coolify API response is unexpectedly large")
            if not raw:
                return {}
            try:
                return json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValidationError("Coolify API returned invalid JSON") from exc
        finally:
            response.close()

    def get_application(self, application_uuid: str) -> dict[str, Any]:
        value = self.request("GET", f"/applications/{urllib.parse.quote(application_uuid, safe='')}")
        if not isinstance(value, dict):
            raise ValidationError("Coolify application response is not an object")
        return value

    def set_sha(self, application_uuid: str, sha: str) -> None:
        require_sha(sha)
        endpoint = f"/applications/{urllib.parse.quote(application_uuid, safe='')}"
        self.request("PATCH", endpoint, {"git_commit_sha": sha})
        confirmed = _read_application_sha(self.get_application(application_uuid), allow_missing=False)
        if confirmed != sha:
            raise ValidationError("Coolify did not persist the requested exact git_commit_sha")

    def trigger_deploy(self, application_uuid: str, method: str = "GET") -> str:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "POST"}:
            raise ValidationError("deploy method must be GET or POST")
        query = urllib.parse.urlencode({"uuid": application_uuid, "force": "false"})
        value = self.request(normalized_method, f"/deploy?{query}")
        deployment_id = _find_deployment_id(value)
        if not deployment_id:
            raise ValidationError("Coolify deploy response did not contain a deployment UUID")
        return _require_deployment_id(deployment_id)

    def deployment_status(self, deployment_id: str) -> str:
        value = self.request("GET", f"/deployments/{urllib.parse.quote(deployment_id, safe='')}")
        if not isinstance(value, dict):
            raise ValidationError("Coolify deployment response is not an object")
        for key in ("status", "deployment_status"):
            if isinstance(value.get(key), str):
                return value[key].strip().lower()
        raise ValidationError("Coolify deployment response has no status")


def _find_deployment_id(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in ("deployment_uuid", "deployment_id", "uuid"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()
        for key in ("deployments", "data"):
            candidate = _find_deployment_id(value.get(key))
            if candidate:
                return candidate
    elif isinstance(value, list):
        for item in value:
            candidate = _find_deployment_id(item)
            if candidate:
                return candidate
    return None


def _require_deployment_id(value: str) -> str:
    candidate = value.strip()
    if not DEPLOYMENT_ID_RE.fullmatch(candidate):
        raise ValidationError("Coolify deployment UUID contains invalid characters")
    return candidate


def _read_application_sha(value: dict[str, Any], *, allow_missing: bool) -> str | None:
    current = value.get("git_commit_sha")
    if current is None or current == "":
        if allow_missing:
            return None
        raise ValidationError("Coolify application has no exact git_commit_sha")
    if not isinstance(current, str):
        raise ValidationError("Coolify application git_commit_sha is not a string")
    return require_sha(current, "current_sha")


def wait_for_deployment(
    client: CoolifyClient,
    deployment_id: str,
    *,
    timeout: float,
    poll_interval: float,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        status = client.deployment_status(deployment_id)
        if status in SUCCESS_STATES:
            return
        if status in FAILURE_STATES:
            raise ValidationError(f"Coolify deployment ended with status {status}")
        sleeper(poll_interval)
    raise ValidationError("Coolify deployment polling timed out")


def deploy_exact_sha(
    client: CoolifyClient,
    *,
    application_uuid: str,
    sha: str,
    expected_previous_sha: str | None = None,
    deploy_method: str = "GET",
    deployment_timeout: float = 1800,
    poll_interval: float = 5,
    on_started: Callable[[DeploymentResult], None] | None = None,
) -> DeploymentResult:
    require_sha(sha)
    if not application_uuid.strip():
        raise ValidationError("application UUID cannot be empty")
    previous_sha = _read_application_sha(client.get_application(application_uuid), allow_missing=True)
    if expected_previous_sha:
        require_sha(expected_previous_sha, "expected_previous_sha")
        if previous_sha != expected_previous_sha:
            raise ValidationError("Coolify current SHA changed after preflight; refusing deployment")
    client.set_sha(application_uuid, sha)
    deployment_id = client.trigger_deploy(application_uuid, deploy_method)
    result = DeploymentResult(application_uuid, sha, previous_sha, deployment_id)
    if on_started:
        on_started(result)
    wait_for_deployment(
        client,
        deployment_id,
        timeout=deployment_timeout,
        poll_interval=poll_interval,
    )
    confirmed = _read_application_sha(client.get_application(application_uuid), allow_missing=False)
    if confirmed != sha:
        raise ValidationError("Coolify application SHA changed while deployment was running")
    return result


def write_github_output(path: Path, result: DeploymentResult) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(f"deployment_id={result.deployment_id}\n")
        handle.write(f"previous_sha={result.previous_sha or ''}\n")
        handle.write(f"requested_sha={result.requested_sha}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--application-uuid", required=True)
    parser.add_argument("--sha")
    parser.add_argument("--expected-previous-sha")
    parser.add_argument("--inspect-only", action="store_true")
    parser.add_argument("--deploy-method", choices=("GET", "POST"), default="GET")
    parser.add_argument("--deployment-timeout", type=float, default=1800)
    parser.add_argument("--poll-interval", type=float, default=5)
    parser.add_argument("--state-output", type=Path)
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args(argv)
    try:
        client = CoolifyClient(args.base_url, os.environ.get("COOLIFY_TOKEN", ""))
        github_output = args.github_output or (Path(os.environ["GITHUB_OUTPUT"]) if os.environ.get("GITHUB_OUTPUT") else None)
        if args.inspect_only:
            current = _read_application_sha(client.get_application(args.application_uuid), allow_missing=False)
            assert current is not None
            if github_output:
                with github_output.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(f"current_sha={current}\n")
            print(f"Coolify exact SHA inspected: application={args.application_uuid} sha={current}")
            return 0
        if not args.sha:
            raise ValidationError("--sha is required unless --inspect-only is used")

        def record_started(started: DeploymentResult) -> None:
            if args.state_output:
                write_json(
                    args.state_output,
                    {
                        "application_uuid": started.application_uuid,
                        "requested_sha": started.requested_sha,
                        "previous_sha": started.previous_sha,
                        "deployment_id": started.deployment_id,
                    },
                )
            if github_output:
                write_github_output(github_output, started)

        result = deploy_exact_sha(
            client,
            application_uuid=args.application_uuid,
            sha=args.sha,
            expected_previous_sha=args.expected_previous_sha,
            deploy_method=args.deploy_method,
            deployment_timeout=args.deployment_timeout,
            poll_interval=args.poll_interval,
            on_started=record_started,
        )
    except ValidationError as exc:
        print(f"exact-SHA deploy failed: {exc}", file=sys.stderr)
        return 1
    print(f"exact-SHA deploy succeeded: application={args.application_uuid} sha={args.sha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
