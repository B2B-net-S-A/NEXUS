"""Audit/apply the manifest-scoped August 2026 duplicate-contract cleanup.

Audit is read-only.  Apply requires the exact fingerprint emitted by audit and
rebuilds the plan under ``FOR UPDATE`` locks before touching any row.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.services.contract_merge import (  # noqa: E402
    ContractMergeError,
    apply_contract_merge_plan,
    build_contract_merge_plan,
    load_contract_merge_manifest,
    parse_field_source_map,
    parse_rate_source_map,
    redact_contract_merge_report,
)

DEFAULT_MANIFEST = BACKEND_ROOT / "app" / "data" / "contract_merge_2026_08.json"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("audit", "apply"), required=True)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--redacted-output", type=Path)
    parser.add_argument("--fingerprint")
    parser.add_argument("--approval-fingerprint")
    parser.add_argument("--candidate-rate-sources", default="")
    parser.add_argument("--client-rate-sources", default="")
    parser.add_argument("--framework-rate-sources", default="")
    parser.add_argument("--rate-metadata-sources", default="")
    parser.add_argument("--field-sources", default="")
    parser.add_argument(
        "--allow-rate-empty-metadata", choices=("NO", "ALLOW"), default="NO"
    )
    return parser


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)
        + "\n",
        encoding="utf-8",
    )


async def _run(args: argparse.Namespace) -> dict[str, Any]:
    manifest = load_contract_merge_manifest(args.manifest)
    async with AsyncSessionLocal() as db:
        try:
            if args.mode == "audit":
                if args.fingerprint:
                    raise ContractMergeError(
                        "--fingerprint is valid only in apply mode"
                    )
                if args.approval_fingerprint:
                    raise ContractMergeError(
                        "--approval-fingerprint is valid only in apply mode"
                    )
                if (
                    args.candidate_rate_sources
                    or args.client_rate_sources
                    or args.framework_rate_sources
                    or args.rate_metadata_sources
                    or args.field_sources
                    or args.allow_rate_empty_metadata != "NO"
                ):
                    raise ContractMergeError(
                        "rate decisions are valid only in apply mode"
                    )
                report = await build_contract_merge_plan(db, manifest)
                # An explicit rollback documents and enforces audit's read-only
                # contract even if a later helper accidentally flushes state.
                await db.rollback()
                return report

            if not args.fingerprint:
                raise ContractMergeError("apply mode requires --fingerprint")
            if not args.approval_fingerprint:
                raise ContractMergeError("apply mode requires --approval-fingerprint")
            report = await apply_contract_merge_plan(
                db,
                manifest,
                expected_fingerprint=args.fingerprint,
                expected_approval_fingerprint=args.approval_fingerprint,
                candidate_rate_sources=parse_rate_source_map(
                    args.candidate_rate_sources
                ),
                client_rate_sources=parse_rate_source_map(args.client_rate_sources),
                framework_rate_sources=parse_rate_source_map(
                    args.framework_rate_sources
                ),
                rate_metadata_sources=parse_rate_source_map(args.rate_metadata_sources),
                allow_rate_empty_metadata=(args.allow_rate_empty_metadata == "ALLOW"),
                field_sources=parse_field_source_map(args.field_sources),
            )
            await db.commit()
            return report
        except Exception:
            await db.rollback()
            raise


def main() -> int:
    args = _parser().parse_args()
    report: dict[str, Any]
    try:
        report = asyncio.run(_run(args))
    except Exception as exc:
        # Keep the detailed error only in the ephemeral full output.  The
        # redacted artifact deliberately carries no values from exception text.
        report = {
            "mode": args.mode,
            "ok": False,
            "fingerprint": args.fingerprint if args.fingerprint else None,
            "summary": {},
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        _write_json(args.output, report)
        if args.redacted_output:
            _write_json(args.redacted_output, redact_contract_merge_report(report))
        print(
            f"contract merge {args.mode} failed ({type(exc).__name__})", file=sys.stderr
        )
        return 2

    _write_json(args.output, report)
    if args.redacted_output:
        _write_json(args.redacted_output, redact_contract_merge_report(report))
    summary = report.get("summary", {})
    print(
        f"contract merge {args.mode} ok fingerprint={report['fingerprint']} "
        f"groups={summary.get('groups', summary.get('groups_applied', 0))}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
