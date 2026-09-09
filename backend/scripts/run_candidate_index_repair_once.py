"""Enqueue the exact reviewed manifest; never accepts arbitrary paths or code."""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PREFIX = "NEXUS_INDEX_REPAIR_RESULT="
IDENTITY = r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}"


def repair_once(identity, audit_identity, fingerprint, *, root=Path("/tmp")):
    if not re.fullmatch(IDENTITY, identity) or not re.fullmatch(
        IDENTITY, audit_identity
    ):
        raise ValueError("Invalid run identity")
    if not re.fullmatch(r"[0-9a-f]{64}", fingerprint):
        raise ValueError("Invalid reviewed fingerprint")
    manifest = root / f"nexus-index-audit-{audit_identity}" / "manifest.json"
    # An unavailable/replaced container requires a fresh audit, never an
    # automatically regenerated manifest under an old approval fingerprint.
    if not manifest.is_file():
        return {"ok": False, "error": "reviewed_manifest_missing"}
    directory = root / f"nexus-index-repair-{identity}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        return None
    try:
        operation = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.audit_candidate_index",
                "--apply",
                str(manifest),
                "--fingerprint",
                fingerprint,
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=720,
            check=False,
        )
        if operation.returncode:
            return {
                "ok": False,
                "error": "repair_enqueue_failed",
                "exit_code": operation.returncode,
            }
        result = json.loads(operation.stdout.splitlines()[-1])
        counters = ("queued", "already_pending", "deleted", "orphans_reported_only")
        if (
            any(type(result.get(key)) is not int or result[key] < 0 for key in counters)
            or result["deleted"] != 0
        ):
            raise ValueError("Invalid enqueue receipt")
        return {
            "ok": True,
            "state": "enqueued",
            "fingerprint": fingerprint,
            "audit_identity": audit_identity,
            **{key: result[key] for key in counters},
        }
    except subprocess.TimeoutExpired:
        # The child may have committed just before timeout. Do not claim no
        # mutation; inspect outbox/fresh audit before any new operation.
        return {"ok": False, "error": "repair_outcome_unknown"}
    except (OSError, ValueError, KeyError, IndexError):
        return {"ok": False, "error": "repair_receipt_invalid"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-identity", required=True)
    parser.add_argument("--audit-identity", required=True)
    parser.add_argument("--fingerprint", required=True)
    args = parser.parse_args()
    result = repair_once(args.run_identity, args.audit_identity, args.fingerprint)
    if result is not None:
        print(PREFIX + json.dumps(result, separators=(",", ":")), flush=True)
        sys.exit(0 if result["ok"] else 1)
