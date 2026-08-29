"""Audit/apply the manifest-scoped Nexus.xlsx and periodic-order correction."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import text

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.nexus_data_correction import (  # noqa: E402
    NexusDataCorrectionError,
    apply_nexus_data_correction_plan,
    build_nexus_data_correction_plan,
    load_nexus_data_correction_manifest,
    redact_nexus_data_correction_report,
)

DEFAULT_MANIFEST = (
    BACKEND_ROOT / "app" / "data" / "nexus_contract_correction_2026_08.json"
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("audit", "apply"), required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--redacted-output", type=Path)
    parser.add_argument("--intent-output", type=Path)
    parser.add_argument("--fingerprint")
    parser.add_argument("--approval-fingerprint")
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        + "\n"
    )
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name == "posix":
            directory_fd = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    if args.mode == "audit" and args.intent_output is not None:
        raise NexusDataCorrectionError("intent output is valid only in apply mode")
    if args.mode == "apply" and args.intent_output is None:
        raise NexusDataCorrectionError("apply mode requires --intent-output")

    manifest = load_nexus_data_correction_manifest(args.manifest)
    async with AsyncSessionLocal() as db:
        try:
            if args.mode == "audit":
                if args.fingerprint or args.approval_fingerprint:
                    raise NexusDataCorrectionError(
                        "fingerprints are valid only in apply mode"
                    )
                await db.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                )
                report = await build_nexus_data_correction_plan(db, manifest)
                # Enforce audit's read-only contract even if a helper later
                # starts flushing state.
                await db.rollback()
                return report

            if not args.fingerprint:
                raise NexusDataCorrectionError("apply mode requires --fingerprint")
            if not args.approval_fingerprint:
                raise NexusDataCorrectionError(
                    "apply mode requires --approval-fingerprint"
                )
            report = await apply_nexus_data_correction_plan(
                db,
                manifest,
                expected_fingerprint=args.fingerprint,
                expected_approval_fingerprint=args.approval_fingerprint,
            )
            # This fsynced, redacted intent is durable before COMMIT.  If the
            # process dies after PostgreSQL commits but before the normal
            # report is written, the wrapper can run a fresh read-only audit
            # and reconcile the exact planned mutation without exposing data.
            _write_json(
                args.intent_output,
                redact_nexus_data_correction_report(report),
            )
            await db.commit()
            return report
        except Exception:
            await db.rollback()
            raise


def main() -> int:
    args = _parser().parse_args()
    try:
        report = asyncio.run(_run(args))
    except Exception as exc:
        report = {
            "mode": args.mode,
            "ok": False,
            "fingerprint": args.fingerprint,
            "summary": {},
            "error_type": type(exc).__name__,
            # Detailed text stays in the ephemeral full report only.
            "error": str(exc),
        }
        _write_json(args.output, report)
        if args.redacted_output:
            _write_json(
                args.redacted_output,
                redact_nexus_data_correction_report(report),
            )
        print(
            f"Nexus data correction {args.mode} failed ({type(exc).__name__})",
            file=sys.stderr,
        )
        return 2

    _write_json(args.output, report)
    if args.redacted_output:
        _write_json(
            args.redacted_output,
            redact_nexus_data_correction_report(report),
        )
    summary = report["summary"]
    if not report.get("ok"):
        print(
            f"Nexus data correction {args.mode} blocked "
            f"fingerprint={report.get('fingerprint')} "
            f"blockers={summary.get('blockers', 0)}",
            file=sys.stderr,
        )
        return 2
    print(
        f"Nexus data correction {args.mode} ok "
        f"fingerprint={report['fingerprint']} "
        f"contracts={summary['contracts_with_changes']} "
        f"orders={summary['periodic_orders_to_delete']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
