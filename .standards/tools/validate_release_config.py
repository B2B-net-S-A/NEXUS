#!/usr/bin/env python3
"""Validate non-secret exact-SHA release inputs before any environment is mutated."""

from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import urlsplit

from _common import ValidationError, require_https_url, require_sha

APPLICATION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
APPLICATION_UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def validate_release_config(
    *,
    application: str,
    deploy_method: str,
    staging_application_uuid: str,
    production_application_uuid: str,
    candidate_sha: str,
    standards_ref: str,
    rollback_floor_sha: str,
    staging_coolify_base_url: str,
    production_coolify_base_url: str,
    staging_base_url: str,
    staging_health_url: str,
    production_health_url: str,
    production_snapshot_url: str,
) -> None:
    if not APPLICATION_RE.fullmatch(application):
        raise ValidationError("application must be a lowercase slug")
    if deploy_method not in {"GET", "POST"}:
        raise ValidationError("deploy_method must be GET or POST")
    for field, value in {
        "staging_application_uuid": staging_application_uuid,
        "production_application_uuid": production_application_uuid,
    }.items():
        if not APPLICATION_UUID_RE.fullmatch(value):
            raise ValidationError(f"{field} contains invalid characters")
    if staging_application_uuid == production_application_uuid:
        raise ValidationError("staging and production application UUIDs must differ")
    require_sha(candidate_sha, "candidate_sha")
    require_sha(standards_ref, "standards_ref")
    require_sha(rollback_floor_sha, "rollback_floor_sha")
    for field, value in {
        "staging_coolify_base_url": staging_coolify_base_url,
        "production_coolify_base_url": production_coolify_base_url,
        "staging_base_url": staging_base_url,
        "staging_health_url": staging_health_url,
        "production_health_url": production_health_url,
        "production_snapshot_url": production_snapshot_url,
    }.items():
        require_https_url(value, field)
    staging_base = urlsplit(staging_base_url)
    staging_health = urlsplit(staging_health_url)
    if staging_base.path not in {"", "/"}:
        raise ValidationError("staging_base_url must be an application origin, not an endpoint")
    if (staging_base.scheme, staging_base.netloc) != (staging_health.scheme, staging_health.netloc):
        raise ValidationError("staging_health_url must use the staging application origin")
    if staging_health.path in {"", "/"}:
        raise ValidationError("staging_health_url must identify a readiness endpoint")
    if production_snapshot_url == production_health_url:
        raise ValidationError("production_snapshot_url must differ from production_health_url")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", required=True)
    parser.add_argument("--deploy-method", required=True)
    parser.add_argument("--staging-application-uuid", required=True)
    parser.add_argument("--production-application-uuid", required=True)
    parser.add_argument("--candidate-sha", required=True)
    parser.add_argument("--standards-ref", required=True)
    parser.add_argument("--rollback-floor-sha", required=True)
    parser.add_argument("--staging-coolify-base-url", required=True)
    parser.add_argument("--production-coolify-base-url", required=True)
    parser.add_argument("--staging-base-url", required=True)
    parser.add_argument("--staging-health-url", required=True)
    parser.add_argument("--production-health-url", required=True)
    parser.add_argument("--production-snapshot-url", required=True)
    args = parser.parse_args(argv)
    try:
        validate_release_config(
            application=args.application,
            deploy_method=args.deploy_method,
            staging_application_uuid=args.staging_application_uuid,
            production_application_uuid=args.production_application_uuid,
            candidate_sha=args.candidate_sha,
            standards_ref=args.standards_ref,
            rollback_floor_sha=args.rollback_floor_sha,
            staging_coolify_base_url=args.staging_coolify_base_url,
            production_coolify_base_url=args.production_coolify_base_url,
            staging_base_url=args.staging_base_url,
            staging_health_url=args.staging_health_url,
            production_health_url=args.production_health_url,
            production_snapshot_url=args.production_snapshot_url,
        )
    except ValidationError as exc:
        print(f"release configuration failed: {exc}", file=sys.stderr)
        return 1
    print("release configuration passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
