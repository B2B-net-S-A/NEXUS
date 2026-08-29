"""Build a closed APPLY receipt from pre-commit intent and a fresh audit.

This helper performs no database work.  The APPLY CLI fsyncs a redacted intent
before COMMIT; the container wrapper then always runs a new read-only audit and
uses this module to prove whether the requested end state is present.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any, Mapping

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONTRACT_FIELDS = (
    "contract_type",
    "start_date",
    "end_date",
    "client_order_end_date",
    "rate_client",
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intent", type=Path, required=True)
    parser.add_argument("--apply-report", type=Path, required=True)
    parser.add_argument("--post-audit-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan-fingerprint", required=True)
    parser.add_argument("--apply-exit-code", type=int, required=True)
    parser.add_argument("--post-audit-exit-code", type=int, required=True)
    return parser


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_write(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            separators=(",", ": "),
        )
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


def _valid_sha256(value: Any) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _is_nonnegative_int(value: Any) -> bool:
    return type(value) is int and value >= 0


def _valid_redacted_report(
    payload: Mapping[str, Any] | None,
    *,
    mode: str,
    fingerprint: str | None = None,
) -> bool:
    if payload is None or payload.get("mode") != mode:
        return False
    if type(payload.get("ok")) is not bool:
        return False
    if not _valid_sha256(payload.get("fingerprint")):
        return False
    if fingerprint is not None and payload.get("fingerprint") != fingerprint:
        return False
    if not isinstance(payload.get("summary"), dict):
        return False
    return all(
        isinstance(payload.get(key), list)
        for key in ("contracts", "orders", "legacy_null_orders", "blockers")
    )


def _desired_state_verified(
    payload: Mapping[str, Any] | None, post_audit_exit_code: int
) -> bool:
    if post_audit_exit_code != 0 or not _valid_redacted_report(payload, mode="audit"):
        return False
    assert payload is not None
    summary = payload["summary"]
    required_zero_counts = (
        "contracts_with_changes",
        "periodic_orders_to_delete",
        "disallowed_standalone_order_types",
        "disallowed_group_order_types",
        "blockers",
    )
    return (
        payload["ok"] is True
        and all(
            _is_nonnegative_int(summary.get(key)) and summary[key] == 0
            for key in required_zero_counts
        )
        and payload["contracts"] == []
        and payload["orders"] == []
        and payload["blockers"] == []
    )


def _empty_failure_report(plan_fingerprint: str) -> dict[str, Any]:
    return {
        "mode": "apply",
        "ok": False,
        "fingerprint": plan_fingerprint,
        "summary": {
            "manifest_contracts": 0,
            "contracts_found": 0,
            "contracts_with_changes": 0,
            "contract_field_changes": {field: 0 for field in _CONTRACT_FIELDS},
            "periodic_orders_to_delete": 0,
            "legacy_null_orders_preserved": 0,
            "disallowed_standalone_order_types": 0,
            "disallowed_group_order_types": 0,
            "dependency_rows": 0,
            "set_null_dependency_rows": 0,
            "set_null_deleted_dependency_rows": 0,
            "legacy_null_dependency_rows": 0,
            "blockers": 1,
        },
        "contracts": [],
        "orders": [],
        "legacy_null_orders": [],
        "blockers": [{"code": "apply_reconciliation_failed"}],
    }


def build_reconciliation_receipt(
    *,
    intent: Mapping[str, Any] | None,
    apply_report: Mapping[str, Any] | None,
    post_audit_report: Mapping[str, Any] | None,
    plan_fingerprint: str,
    apply_exit_code: int,
    post_audit_exit_code: int,
) -> tuple[dict[str, Any], bool]:
    """Return the redacted receipt and whether the exact end state is proved."""

    if not _valid_sha256(plan_fingerprint):
        raise ValueError("invalid plan fingerprint")
    if apply_exit_code < 0 or post_audit_exit_code < 0:
        raise ValueError("exit codes must be non-negative")

    intent_valid = (
        _valid_redacted_report(
            intent,
            mode="apply",
            fingerprint=plan_fingerprint,
        )
        and intent is not None
        and intent["ok"] is True
        and intent["blockers"] == []
    )
    apply_report_valid = _valid_redacted_report(
        apply_report,
        mode="apply",
        fingerprint=plan_fingerprint,
    )
    apply_report_matches_intent = bool(
        intent_valid and apply_report_valid and apply_report == intent
    )
    apply_report_consistent = not apply_report_valid or apply_report_matches_intent
    desired_state = _desired_state_verified(post_audit_report, post_audit_exit_code)
    verified = bool(intent_valid and apply_report_consistent and desired_state)

    if intent_valid:
        receipt = dict(intent)
    elif apply_report_valid:
        receipt = dict(apply_report)
    else:
        receipt = _empty_failure_report(plan_fingerprint)

    if verified:
        receipt["ok"] = True
        status = (
            "verified"
            if apply_exit_code == 0 and apply_report_matches_intent
            else "verified_after_cli_failure"
        )
    else:
        receipt["ok"] = False
        status = "verification_failed" if intent_valid else "not_committed"
        blockers = [
            item
            for item in receipt.get("blockers", [])
            if isinstance(item, dict) and item.get("code")
        ]
        if not any(
            item.get("code") == "apply_reconciliation_failed" for item in blockers
        ):
            blockers.append({"code": "apply_reconciliation_failed"})
        receipt["blockers"] = blockers
        summary = dict(receipt.get("summary", {}))
        summary["blockers"] = len(blockers)
        receipt["summary"] = summary

    post_fingerprint = (
        post_audit_report.get("fingerprint")
        if _valid_redacted_report(post_audit_report, mode="audit")
        else None
    )
    receipt["reconciliation"] = {
        "status": status,
        "precommit_intent": bool(intent_valid),
        "apply_report_present": bool(apply_report_valid),
        "apply_report_matches_intent": apply_report_matches_intent,
        "apply_exit_code": apply_exit_code,
        "post_apply_audit_exit_code": post_audit_exit_code,
        "post_apply_fingerprint": post_fingerprint,
        "desired_state_verified": desired_state,
    }
    return receipt, verified


def main() -> int:
    args = _parser().parse_args()
    try:
        receipt, verified = build_reconciliation_receipt(
            intent=_read_json(args.intent),
            apply_report=_read_json(args.apply_report),
            post_audit_report=_read_json(args.post_audit_report),
            plan_fingerprint=args.plan_fingerprint,
            apply_exit_code=args.apply_exit_code,
            post_audit_exit_code=args.post_audit_exit_code,
        )
    except Exception:
        if not _valid_sha256(args.plan_fingerprint):
            return 2
        receipt = _empty_failure_report(args.plan_fingerprint)
        receipt["reconciliation"] = {
            "status": "verification_failed",
            "precommit_intent": False,
            "apply_report_present": False,
            "apply_report_matches_intent": False,
            "apply_exit_code": max(0, args.apply_exit_code),
            "post_apply_audit_exit_code": max(0, args.post_audit_exit_code),
            "post_apply_fingerprint": None,
            "desired_state_verified": False,
        }
        verified = False
    _atomic_write(args.output, receipt)
    return 0 if verified else 2


if __name__ == "__main__":
    raise SystemExit(main())
