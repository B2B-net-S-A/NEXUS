#!/usr/bin/env python3
"""Export and explicitly clear deprecated candidate monthly-rate values.

This script is intentionally not wired into Alembic or application startup.
Run without mutation flags for a dry-run count. Production apply additionally
requires an encrypted export, its exact SHA-256, the expected row count, and an
explicit approval acknowledgement.

Examples:
  python scripts/retire_candidate_monthly_salary.py
  python scripts/retire_candidate_monthly_salary.py --export /secure/candidates.bin
  python scripts/retire_candidate_monthly_salary.py \
      --verify-export /secure/candidates.bin --expected-sha256 <sha256>
  python scripts/retire_candidate_monthly_salary.py \
      --apply --export /secure/candidates.bin --expected-count 12 \
      --expected-sha256 <sha256> \
      --confirm-production-cleanup I_HAVE_EXPLICIT_APPROVAL

The Fernet key is read only from ``CANDIDATE_SALARY_EXPORT_KEY``.
Never place the key or the export inside the repository or application logs.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import hmac
import json
import os
import stat
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import func, select, text, update
from sqlalchemy.exc import SQLAlchemyError

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402

_KEY_ENV = "CANDIDATE_SALARY_EXPORT_KEY"
_APPROVAL_PHRASE = "I_HAVE_EXPLICIT_APPROVAL"
_FORMAT_VERSION = 1
_CANDIDATE_WRITE_LOCK_SQL = "LOCK TABLE candidates IN SHARE ROW EXCLUSIVE MODE NOWAIT"


class CleanupSafetyError(RuntimeError):
    """Raised before mutation whenever an invariant cannot be proven."""


def _fernet() -> Fernet:
    key = os.environ.get(_KEY_ENV)
    if not key:
        raise CleanupSafetyError(f"{_KEY_ENV} is required")
    try:
        return Fernet(key.encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise CleanupSafetyError(f"{_KEY_ENV} is not a valid Fernet key") from exc


def _ciphertext_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _validate_expected_sha256(expected_sha256: str) -> str:
    normalized = expected_sha256.strip().lower()
    if len(normalized) != 64 or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise CleanupSafetyError("--expected-sha256 must be 64 hexadecimal characters")
    return normalized


def _validated_artifact_path(path: Path, *, must_exist: bool) -> Path:
    """Resolve an artifact without ever accepting repo-local or linked files."""

    if not path.is_absolute():
        raise CleanupSafetyError("artifact path must be absolute and outside the repo")
    if path.is_symlink():
        raise CleanupSafetyError("artifact path must not be a symbolic link")
    try:
        resolved = path.resolve(strict=must_exist)
    except (OSError, RuntimeError) as exc:
        raise CleanupSafetyError("artifact path cannot be resolved safely") from exc

    repo_root = Path(__file__).resolve().parents[2]
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        pass
    else:
        raise CleanupSafetyError("encrypted export must be outside the repository")

    if must_exist:
        try:
            metadata = resolved.stat()
        except OSError as exc:
            raise CleanupSafetyError("encrypted export cannot be opened") from exc
        if not stat.S_ISREG(metadata.st_mode):
            raise CleanupSafetyError("encrypted export must be a regular file")
        if metadata.st_mode & 0o077:
            raise CleanupSafetyError(
                "encrypted export permissions must not allow group or other access"
            )
    elif resolved.exists():
        raise CleanupSafetyError("encrypted export already exists")

    return resolved


def _record_from_row(row: Any) -> dict[str, Any]:
    return {
        "candidate_id": int(row.id),
        "salary_expectation": (
            str(row.salary_expectation) if row.salary_expectation is not None else None
        ),
        "salary_currency": row.salary_currency,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _canonical_payload(records: list[dict[str, Any]]) -> bytes:
    manifest = {
        "format_version": _FORMAT_VERSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "records": records,
    }
    return json.dumps(
        manifest,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _write_exclusive_private(path: Path, payload: bytes) -> None:
    resolved = _validated_artifact_path(path, must_exist=False)
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(resolved, flags, stat.S_IRUSR)
    except OSError as exc:
        raise CleanupSafetyError("encrypted export cannot be created safely") from exc
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except Exception:
        try:
            resolved.unlink(missing_ok=True)
        except OSError:
            pass
        raise CleanupSafetyError(
            "encrypted export could not be written completely"
        ) from None


def _read_private_bytes(path: Path) -> bytes:
    resolved = _validated_artifact_path(path, must_exist=True)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(resolved, flags)
        with os.fdopen(fd, "rb") as handle:
            metadata = os.fstat(handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise CleanupSafetyError("encrypted export must be a regular file")
            if metadata.st_mode & 0o077:
                raise CleanupSafetyError(
                    "encrypted export permissions must not allow group or other access"
                )
            return handle.read()
    except CleanupSafetyError:
        raise
    except OSError as exc:
        raise CleanupSafetyError("encrypted export cannot be opened") from exc


def _read_manifest(path: Path, expected_sha256: str | None) -> tuple[dict, str]:
    normalized_expected = (
        _validate_expected_sha256(expected_sha256) if expected_sha256 else None
    )
    ciphertext = _read_private_bytes(path)
    digest = _ciphertext_sha256(ciphertext)
    if normalized_expected and not hmac.compare_digest(digest, normalized_expected):
        raise CleanupSafetyError("encrypted export SHA-256 does not match")
    try:
        plaintext = _fernet().decrypt(ciphertext)
    except InvalidToken as exc:
        raise CleanupSafetyError("encrypted export cannot be decrypted") from exc
    try:
        manifest = json.loads(plaintext)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CleanupSafetyError("decrypted export is not valid JSON") from exc
    if not isinstance(manifest, dict):
        raise CleanupSafetyError("decrypted export manifest is invalid")
    if manifest.get("format_version") != _FORMAT_VERSION:
        raise CleanupSafetyError("unsupported export format version")
    records = manifest.get("records")
    if not isinstance(records, list):
        raise CleanupSafetyError("export records are missing")
    if any(not isinstance(record, dict) for record in records):
        raise CleanupSafetyError("export contains an invalid record")
    ids = [record.get("candidate_id") for record in records]
    if any(
        isinstance(candidate_id, bool) or not isinstance(candidate_id, int)
        for candidate_id in ids
    ):
        raise CleanupSafetyError("export contains an invalid candidate id")
    if len(ids) != len(set(ids)):
        raise CleanupSafetyError("export contains duplicate candidate ids")
    return manifest, digest


async def _current_rows() -> list[Any]:
    async with AsyncSessionLocal() as session:
        statement = (
            select(
                Candidate.id,
                Candidate.salary_expectation,
                Candidate.salary_currency,
                Candidate.updated_at,
            )
            .where(Candidate.salary_expectation.is_not(None))
            .order_by(Candidate.id)
        )
        return list((await session.execute(statement)).all())


async def dry_run() -> dict[str, Any]:
    async with AsyncSessionLocal() as session:
        count = await session.scalar(
            select(func.count(Candidate.id)).where(
                Candidate.salary_expectation.is_not(None)
            )
        )
    return {"mode": "dry-run", "count": int(count or 0)}


async def export_encrypted(path: Path) -> dict[str, Any]:
    # Reject unsafe destinations before reading any candidate values.
    _validated_artifact_path(path, must_exist=False)
    rows = await _current_rows()
    records = [_record_from_row(row) for row in rows]
    ciphertext = _fernet().encrypt(_canonical_payload(records))
    _write_exclusive_private(path, ciphertext)

    # Immediate read/decrypt validates that the retained artifact is usable.
    manifest, digest = _read_manifest(path, _ciphertext_sha256(ciphertext))
    return {
        "mode": "export",
        "count": len(manifest["records"]),
        "sha256": digest,
        "verified_read": True,
    }


async def apply_cleanup(
    *,
    path: Path,
    expected_count: int,
    expected_sha256: str,
    approval: str,
) -> dict[str, Any]:
    if approval != _APPROVAL_PHRASE:
        raise CleanupSafetyError("explicit production approval acknowledgement missing")
    if isinstance(expected_count, bool) or expected_count < 0:
        raise CleanupSafetyError("--expected-count must be a non-negative integer")

    manifest, digest = _read_manifest(path, expected_sha256)
    exported = manifest["records"]
    if len(exported) != expected_count:
        raise CleanupSafetyError("export count does not match --expected-count")
    expected_by_id = {record["candidate_id"]: record for record in exported}

    async with AsyncSessionLocal() as session:
        try:
            # This lock is acquired only after the export has been read and
            # decrypted. It blocks concurrent INSERT/UPDATE/DELETE operations
            # for the short snapshot -> compare -> clear -> verify transaction,
            # while ordinary SELECTs remain available. NOWAIT makes contention
            # fail closed instead of extending a production maintenance window.
            try:
                await session.execute(text(_CANDIDATE_WRITE_LOCK_SQL))
            except SQLAlchemyError:
                raise CleanupSafetyError(
                    "candidate data is being modified; retry cleanup later"
                ) from None

            statement = (
                select(
                    Candidate.id,
                    Candidate.salary_expectation,
                    Candidate.salary_currency,
                    Candidate.updated_at,
                )
                .where(Candidate.salary_expectation.is_not(None))
                .order_by(Candidate.id)
                .with_for_update()
            )
            current_rows = list((await session.execute(statement)).all())
            current = [_record_from_row(row) for row in current_rows]
            current_by_id = {record["candidate_id"]: record for record in current}

            if len(current) != expected_count:
                raise CleanupSafetyError(
                    "current database count does not match --expected-count"
                )
            if current_by_id != expected_by_id:
                raise CleanupSafetyError(
                    "database values changed after export; create a new export"
                )

            result = await session.execute(
                update(Candidate)
                .where(Candidate.id.in_(list(expected_by_id)))
                .where(Candidate.salary_expectation.is_not(None))
                .values(salary_expectation=None, salary_currency=None)
            )
            changed = int(result.rowcount or 0)
            if changed != expected_count:
                raise CleanupSafetyError("updated row count does not match expectation")

            remaining = await session.scalar(
                select(func.count(Candidate.id)).where(
                    Candidate.salary_expectation.is_not(None)
                )
            )
            if int(remaining or 0) != 0:
                raise CleanupSafetyError("monthly candidate values remain after update")
            await session.commit()
        except Exception:
            await session.rollback()
            raise

    return {
        "mode": "apply",
        "changed": changed,
        "remaining": 0,
        "sha256": digest,
    }


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--verify-export", type=Path)
    parser.add_argument("--export", type=Path)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--confirm-production-cleanup")
    args = parser.parse_args(argv)
    if args.apply:
        missing = [
            name
            for name, value in (
                ("--export", args.export),
                ("--expected-count", args.expected_count),
                ("--expected-sha256", args.expected_sha256),
            )
            if value is None
        ]
        if missing:
            parser.error(f"--apply requires {', '.join(missing)}")
    if args.verify_export and not args.expected_sha256:
        parser.error("--verify-export requires --expected-sha256")
    return args


async def _main(args: argparse.Namespace) -> dict[str, Any]:
    if args.verify_export:
        manifest, digest = _read_manifest(args.verify_export, args.expected_sha256)
        return {
            "mode": "verify-export",
            "count": len(manifest["records"]),
            "sha256": digest,
            "verified_read": True,
        }
    if args.apply:
        return await apply_cleanup(
            path=args.export,
            expected_count=args.expected_count,
            expected_sha256=args.expected_sha256,
            approval=args.confirm_production_cleanup or "",
        )
    if args.export:
        return await export_encrypted(args.export)
    return await dry_run()


if __name__ == "__main__":
    try:
        print(json.dumps(asyncio.run(_main(_parse_args())), sort_keys=True))
    except CleanupSafetyError as exc:
        print(json.dumps({"error": str(exc)}), file=sys.stderr)
        raise SystemExit(2) from None
