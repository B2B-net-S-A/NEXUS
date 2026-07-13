#!/usr/bin/env python3
"""Build a deterministic, schema-compatible exact-SHA release manifest."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from _common import ValidationError, parse_utc, require_sha, utc_now_string, write_json

SNAPSHOT_REFERENCE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@+-]{0,511}$")
DEPLOYMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
RUN_ID_RE = re.compile(r"^[1-9][0-9]*$")
APPLICATION_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
MIGRATION_HEAD_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+/-]{0,255}$")
APPLICATION_UUID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


def build_manifest(
    *,
    application: str,
    environment: str,
    sha: str,
    standards_ref: str,
    migration_head: str,
    previous_sha: str | None,
    rollback_floor_sha: str,
    deployment_id: str | None,
    snapshot_reference: str | None,
    quality_gate_run_id: str,
    coolify_application_uuid: str | None = None,
    outcome: str = "succeeded",
    rollback_to_sha: str | None = None,
    rollback_deployment_id: str | None = None,
    released_at: str | None = None,
) -> dict[str, object]:
    if not APPLICATION_RE.fullmatch(application):
        raise ValidationError("application must be a lowercase slug")
    if not MIGRATION_HEAD_RE.fullmatch(migration_head):
        raise ValidationError("migration_head contains invalid characters")
    if environment not in {"staging", "production"}:
        raise ValidationError("environment must be staging or production")
    if outcome not in {"succeeded", "rolled_back", "failed"}:
        raise ValidationError("invalid release outcome")
    require_sha(sha)
    require_sha(standards_ref, "standards_ref")
    require_sha(rollback_floor_sha, "rollback_floor_sha")
    if previous_sha:
        require_sha(previous_sha, "previous_sha")
    if rollback_to_sha:
        require_sha(rollback_to_sha, "rollback_to_sha")
    if not RUN_ID_RE.fullmatch(quality_gate_run_id):
        raise ValidationError("quality_gate_run_id must be a positive integer string")
    if coolify_application_uuid is not None and not APPLICATION_UUID_RE.fullmatch(coolify_application_uuid):
        raise ValidationError("coolify_application_uuid contains invalid characters")
    for field, value, pattern in (
        ("deployment_id", deployment_id, DEPLOYMENT_ID_RE),
        ("rollback_deployment_id", rollback_deployment_id, DEPLOYMENT_ID_RE),
        ("snapshot_reference", snapshot_reference, SNAPSHOT_REFERENCE_RE),
    ):
        if value is not None and not pattern.fullmatch(value):
            raise ValidationError(f"{field} contains invalid characters")
    if outcome in {"succeeded", "rolled_back"} and not deployment_id:
        raise ValidationError(f"{outcome} outcome requires deployment_id")
    if outcome in {"succeeded", "rolled_back"} and not snapshot_reference:
        raise ValidationError(f"{outcome} outcome requires snapshot_reference")
    if outcome == "rolled_back":
        if not rollback_to_sha or not rollback_deployment_id:
            raise ValidationError("rolled_back outcome requires rollback target and deployment ID")
    if outcome == "succeeded" and (rollback_to_sha or rollback_deployment_id):
        raise ValidationError("succeeded outcome cannot contain rollback fields")
    if rollback_deployment_id and not rollback_to_sha:
        raise ValidationError("rollback_deployment_id requires rollback_to_sha")
    if rollback_to_sha:
        if not previous_sha:
            raise ValidationError("rollback_to_sha requires previous_sha")
        if rollback_to_sha != previous_sha:
            raise ValidationError("automatic rollback target must equal previous_sha")
    finalized_at = released_at or utc_now_string()
    parse_utc(finalized_at, "released_at")

    manifest: dict[str, object] = {
        "$schema": "https://standards.dynaminds.pl/schemas/release-manifest.schema.json",
        "schema_version": 2,
        "application": application,
        "environment": environment,
        "sha": sha,
        "standards_ref": standards_ref,
        "released_at": finalized_at,
        "migration_head": migration_head,
        "previous_sha": previous_sha,
        "rollback_floor_sha": rollback_floor_sha,
        "deployment_id": deployment_id,
        "snapshot_reference": snapshot_reference,
        "quality_gate_run_id": quality_gate_run_id,
        "outcome": outcome,
        "rollback_to_sha": rollback_to_sha,
        "rollback_deployment_id": rollback_deployment_id,
    }
    if coolify_application_uuid:
        manifest["coolify_application_uuid"] = coolify_application_uuid
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--application", required=True)
    parser.add_argument("--environment", choices=("staging", "production"), required=True)
    parser.add_argument("--sha", required=True)
    parser.add_argument("--standards-ref", required=True)
    parser.add_argument("--migration-head", required=True)
    parser.add_argument("--previous-sha")
    parser.add_argument("--rollback-floor-sha", required=True)
    parser.add_argument("--deployment-id")
    parser.add_argument("--snapshot-reference")
    parser.add_argument("--coolify-application-uuid")
    parser.add_argument("--quality-gate-run-id", required=True)
    parser.add_argument("--outcome", choices=("succeeded", "rolled_back", "failed"), default="succeeded")
    parser.add_argument("--rollback-to-sha")
    parser.add_argument("--rollback-deployment-id")
    parser.add_argument("--output", type=Path, default=Path("release-manifest.json"))
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(
            application=args.application,
            environment=args.environment,
            sha=args.sha,
            standards_ref=args.standards_ref,
            migration_head=args.migration_head,
            previous_sha=args.previous_sha,
            rollback_floor_sha=args.rollback_floor_sha,
            deployment_id=args.deployment_id,
            snapshot_reference=args.snapshot_reference,
            coolify_application_uuid=args.coolify_application_uuid,
            quality_gate_run_id=args.quality_gate_run_id,
            outcome=args.outcome,
            rollback_to_sha=args.rollback_to_sha,
            rollback_deployment_id=args.rollback_deployment_id,
        )
        write_json(args.output, manifest)
    except ValidationError as exc:
        print(f"release manifest failed: {exc}", file=sys.stderr)
        return 1
    print(f"release manifest written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
