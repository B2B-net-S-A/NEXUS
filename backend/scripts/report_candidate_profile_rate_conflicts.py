#!/usr/bin/env python3
"""Read-only report for legacy non-PLN candidate-global profile rates.

The runtime never interprets an explicit foreign currency as PLN. This tool
lists those conflicts for manual correction without converting values. By
default it prints only the count. ``--output`` writes an encrypted, private
artifact outside the repository and prints only its count and SHA-256.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

from cryptography.fernet import Fernet
from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.services.candidate_profile_rate import (  # noqa: E402
    conflicting_profile_rate_currency_clause,
)

_KEY_ENV = "CANDIDATE_RATE_CONFLICT_EXPORT_KEY"
_REPO_ROOT = Path(__file__).resolve().parents[2]


class ConflictReportSafetyError(RuntimeError):
    pass


def _validated_output_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        raise ConflictReportSafetyError("output path must be absolute")
    resolved_parent = path.parent.resolve(strict=True)
    resolved = resolved_parent / path.name
    if resolved == _REPO_ROOT or _REPO_ROOT in resolved.parents:
        raise ConflictReportSafetyError("output path must be outside the repository")
    if path.is_symlink() or path.exists():
        raise ConflictReportSafetyError("output path must be new and not a symlink")
    return resolved


def _encrypt(payload: bytes) -> bytes:
    raw_key = os.environ.get(_KEY_ENV, "").encode("ascii")
    if not raw_key:
        raise ConflictReportSafetyError(f"{_KEY_ENV} is required with --output")
    try:
        return Fernet(raw_key).encrypt(payload)
    except (TypeError, ValueError) as exc:
        raise ConflictReportSafetyError(
            f"{_KEY_ENV} is not a valid Fernet key"
        ) from exc


def _write_private(path: Path, ciphertext: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(ciphertext)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


async def build_report() -> list[dict[str, object]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    Candidate.id,
                    Candidate.expected_rate_hourly,
                    Candidate.expected_rate_currency,
                    Candidate.updated_at,
                )
                .where(Candidate.expected_rate_hourly.is_not(None))
                .where(
                    conflicting_profile_rate_currency_clause(
                        Candidate.expected_rate_currency
                    )
                )
                .order_by(Candidate.id)
            )
        ).all()
    return [
        {
            "candidate_id": row.id,
            "amount": str(row.expected_rate_hourly),
            "currency": row.expected_rate_currency,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
        for row in rows
    ]


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        help="absolute path outside the repository for an encrypted report",
    )
    args = parser.parse_args()

    records = await build_report()
    evidence: dict[str, object] = {"conflict_count": len(records)}
    if args.output:
        output_path = _validated_output_path(args.output)
        plaintext = json.dumps(
            {"version": 1, "records": records},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ciphertext = _encrypt(plaintext)
        _write_private(output_path, ciphertext)
        evidence["sha256"] = hashlib.sha256(ciphertext).hexdigest()
    print(json.dumps(evidence, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
