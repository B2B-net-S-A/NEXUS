"""Fixed read-only production audit entry point for Coolify Ops.

The private manifest remains in the backend container for exact repair review.
Only aggregate counts and its fingerprint leave the container. A repeated cron
tick cannot rerun an audit with the same GitHub run identity.
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PREFIX = "NEXUS_INDEX_AUDIT_RESULT="


def audit_once(identity: str, *, root=Path("/tmp")) -> dict | None:
    if not re.fullmatch(r"[1-9][0-9]{0,19}-[1-9][0-9]{0,5}", identity):
        raise ValueError("Invalid run identity")
    directory = root / f"nexus-index-audit-{identity}"
    try:
        directory.mkdir(mode=0o700)
    except FileExistsError:
        return None
    manifest = directory / "manifest.json"
    # Suppress provider logs and traceback details; the parent emits a bounded
    # machine-readable failure, never an apparently successful empty report.
    try:
        operation = subprocess.run(
            [
                sys.executable,
                "-m",
                "scripts.audit_candidate_index",
                "--output",
                str(manifest),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=720,
            check=False,
        )
        if operation.returncode:
            return {
                "ok": False,
                "error": "audit_failed",
                "exit_code": operation.returncode,
            }
        data = json.loads(manifest.read_text())
        report = {
            key: data[key]
            for key in (
                "fingerprint",
                "database_unchanged",
                "population",
                "index_points",
                "counts",
            )
        }
        report.update(
            ok=bool(data["database_unchanged"]),
            orphan_points=len(data["orphan_point_ids"]),
            run_identity=identity,
        )
        return report
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "audit_timeout"}
    except (OSError, ValueError, KeyError):
        return {"ok": False, "error": "audit_report_invalid"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-identity", required=True)
    args = parser.parse_args()
    result = audit_once(args.run_identity)
    if result is not None:
        print(PREFIX + json.dumps(result, separators=(",", ":")), flush=True)
        sys.exit(0 if result["ok"] else 1)
