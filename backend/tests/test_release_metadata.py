"""Fail-closed contract for Coolify source-build release metadata."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_COMPOSE = REPOSITORY_ROOT / "docker-compose.yml"
TARGET_SHA = "d" * 40
BUILD_TIMESTAMP = "2026-07-14T12:34:56Z"


def _compose_environment(
    release: dict[str, str], *, include_built_at: bool = True
) -> dict[str, str]:
    environment = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", ""),
        "POSTGRES_PASSWORD": "compose-contract-only",
        "GRAFANA_LOKI_URL": "",
        "GRAFANA_LOKI_USER": "",
        "GRAFANA_LOKI_TOKEN": "",
        **release,
    }
    if os.environ.get("DOCKER_CONFIG"):
        environment["DOCKER_CONFIG"] = os.environ["DOCKER_CONFIG"]
    if include_built_at:
        environment["BUILT_AT"] = BUILD_TIMESTAMP
    return environment


def _render_compose(
    release: dict[str, str], *, include_built_at: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            "/dev/null",
            "--project-directory",
            str(REPOSITORY_ROOT),
            "-f",
            str(PRODUCTION_COMPOSE),
            "config",
            "--no-env-resolution",
            "--format",
            "json",
        ],
        cwd=REPOSITORY_ROOT,
        env=_compose_environment(release, include_built_at=include_built_at),
        text=True,
        capture_output=True,
        check=False,
    )


def _require_rendered_compose(release: dict[str, str]) -> dict:
    result = _render_compose(release)
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _assert_release_wiring(rendered: dict) -> None:
    services = rendered["services"]

    for service_name in ("backend", "migrate"):
        build_args = services[service_name]["build"]["args"]
        assert build_args["GIT_SHA"] == TARGET_SHA
        assert build_args["BUILT_AT"] == BUILD_TIMESTAMP

    assert services["frontend"]["build"]["args"]["NEXT_PUBLIC_GIT_SHA"] == TARGET_SHA
    assert services["backend"]["healthcheck"]["test"] == [
        "CMD",
        "curl",
        "-fsS",
        "http://localhost:8000/api/livez",
    ]


def test_compose_wires_explicit_release_metadata_and_process_liveness():
    _assert_release_wiring(_require_rendered_compose({"GIT_SHA": TARGET_SHA}))


def test_compose_rejects_ambiguous_source_commit_fallback():
    result = _render_compose({"SOURCE_COMMIT": TARGET_SHA})

    assert result.returncode != 0
    assert "GIT_SHA must be a full 40-character commit SHA" in (
        result.stderr + result.stdout
    )


def test_compose_fails_closed_without_exact_source_identifier():
    result = _render_compose({})

    assert result.returncode != 0
    assert "GIT_SHA must be a full 40-character commit SHA" in (
        result.stderr + result.stdout
    )


def test_compose_fails_closed_without_build_timestamp():
    result = _render_compose({"GIT_SHA": TARGET_SHA}, include_built_at=False)

    assert result.returncode != 0
    assert "BUILT_AT must be an ISO-8601 UTC timestamp" in (
        result.stderr + result.stdout
    )


def test_dockerfiles_reject_malformed_release_sha():
    backend_dockerfile = (REPOSITORY_ROOT / "backend" / "Dockerfile").read_text()
    frontend_dockerfile = (REPOSITORY_ROOT / "frontend" / "Dockerfile").read_text()

    assert "re.fullmatch(r'[0-9a-f]{40}', sha)" in backend_dockerfile
    assert "datetime.datetime.strptime" in backend_dockerfile
    assert "/^[0-9a-f]{40}$/" in frontend_dockerfile
    assert "process.exit(1)" in frontend_dockerfile
