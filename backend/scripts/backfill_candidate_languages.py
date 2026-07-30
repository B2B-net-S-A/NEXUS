#!/usr/bin/env python3
"""Backfill legacy ``candidates.languages`` into normalized language facts.

This script is deliberately not invoked by Alembic or application startup.
It is read-only by default.  ``--apply`` commits one bounded batch at a time
and writes a non-PII checkpoint so an interrupted run can resume explicitly.

Examples:
  python scripts/backfill_candidate_languages.py
  python scripts/backfill_candidate_languages.py --apply
  python scripts/backfill_candidate_languages.py --apply --resume
  python scripts/backfill_candidate_languages.py --batch-size 100 --max-candidates 500
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select

BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.core.database import AsyncSessionLocal  # noqa: E402
from app.models.candidate import Candidate  # noqa: E402
from app.models.candidate_language import CandidateLanguage  # noqa: E402
from app.services.candidate_language_writer import (  # noqa: E402
    NormalizedLanguage,
    normalize_language_payload,
    sync_candidate_languages_from_source,
)

DEFAULT_CHECKPOINT = Path("/tmp/nexus_candidate_languages_backfill.checkpoint.json")


class BackfillSafetyError(RuntimeError):
    """Raised before a run whose resume/apply intent is ambiguous."""


@dataclass
class BackfillCounters:
    scanned: int = 0
    with_legacy_values: int = 0
    parsed_facts: int = 0
    invalid_entries: int = 0
    inserted: int = 0
    updated: int = 0
    protected_manual: int = 0
    protected_tombstone: int = 0
    parity_exact: int = 0
    parity_conflict: int = 0
    last_candidate_id: int = 0
    conflict_samples: list[int] = field(default_factory=list)

    def add_conflict(self, candidate_id: int) -> None:
        self.parity_conflict += 1
        if len(self.conflict_samples) < 20:
            self.conflict_samples.append(candidate_id)


def _normalized_signature(
    values: Iterable[NormalizedLanguage],
) -> set[tuple[str, str | None, bool, bool]]:
    return {
        (
            value.language_code,
            value.cefr_level,
            value.is_native,
            value.is_level_unknown,
        )
        for value in values
    }


def _row_signature(
    rows: Iterable[CandidateLanguage],
) -> set[tuple[str, str | None, bool, bool]]:
    return {
        (
            row.language_code,
            row.cefr_level,
            row.is_native,
            row.is_level_unknown,
        )
        for row in rows
        if row.deleted_at is None
    }


def parity_matches(
    expected: Iterable[NormalizedLanguage],
    actual: Iterable[CandidateLanguage],
) -> bool:
    """Exact fact parity, intentionally ignoring display-name spelling."""

    return _normalized_signature(expected) == _row_signature(actual)


def _read_checkpoint(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BackfillSafetyError("checkpoint cannot be read") from exc
    if raw.get("format_version") != 1:
        raise BackfillSafetyError("unsupported checkpoint format")
    cursor = raw.get("last_candidate_id")
    if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
        raise BackfillSafetyError("checkpoint cursor is invalid")
    return raw


def _write_checkpoint(path: Path, counters: BackfillCounters) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format_version": 1,
        "last_candidate_id": counters.last_candidate_id,
        "counters": asdict(counters),
    }
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _restore_counters(raw: dict[str, Any]) -> BackfillCounters:
    stored = raw.get("counters")
    if not isinstance(stored, dict):
        return BackfillCounters(last_candidate_id=int(raw["last_candidate_id"]))
    allowed = BackfillCounters.__dataclass_fields__.keys()
    values = {key: value for key, value in stored.items() if key in allowed}
    counters = BackfillCounters(**values)
    counters.last_candidate_id = int(raw["last_candidate_id"])
    return counters


async def run_backfill(
    *,
    apply: bool,
    resume: bool,
    batch_size: int,
    max_candidates: int | None,
    checkpoint_path: Path,
) -> BackfillCounters:
    if batch_size < 1 or batch_size > 5000:
        raise BackfillSafetyError("batch size must be between 1 and 5000")
    if max_candidates is not None and max_candidates < 1:
        raise BackfillSafetyError("max candidates must be positive")
    if resume and not apply:
        raise BackfillSafetyError("--resume requires --apply")
    if resume:
        counters = _restore_counters(_read_checkpoint(checkpoint_path))
    else:
        if apply and checkpoint_path.exists():
            raise BackfillSafetyError(
                "checkpoint already exists; use --resume or a new checkpoint path"
            )
        counters = BackfillCounters()

    processed_this_run = 0
    async with AsyncSessionLocal() as db:
        while True:
            remaining = (
                None if max_candidates is None else max_candidates - processed_this_run
            )
            if remaining is not None and remaining <= 0:
                break
            limit = batch_size if remaining is None else min(batch_size, remaining)
            batch = list(
                (
                    await db.execute(
                        select(Candidate.id, Candidate.languages)
                        .where(Candidate.id > counters.last_candidate_id)
                        .order_by(Candidate.id.asc())
                        .limit(limit)
                    )
                ).all()
            )
            if not batch:
                break

            candidate_ids = [int(row.id) for row in batch]
            current_rows = list(
                (
                    await db.scalars(
                        select(CandidateLanguage).where(
                            CandidateLanguage.candidate_id.in_(candidate_ids)
                        )
                    )
                ).all()
            )
            rows_by_candidate: dict[int, list[CandidateLanguage]] = defaultdict(list)
            for language_row in current_rows:
                rows_by_candidate[language_row.candidate_id].append(language_row)

            for candidate_row in batch:
                candidate_id = int(candidate_row.id)
                expected, invalid = normalize_language_payload(candidate_row.languages)
                counters.scanned += 1
                counters.last_candidate_id = candidate_id
                counters.invalid_entries += invalid
                counters.parsed_facts += len(expected)
                if expected:
                    counters.with_legacy_values += 1

                actual = rows_by_candidate.get(candidate_id, [])
                if apply and expected:
                    result = await sync_candidate_languages_from_source(
                        db,
                        candidate_id=candidate_id,
                        raw_languages=candidate_row.languages,
                        provenance="legacy",
                        source_ref="legacy-jsonb-backfill-v1",
                        replace_source_snapshot=False,
                    )
                    counters.inserted += result.inserted
                    counters.updated += result.updated
                    counters.protected_manual += result.protected_manual
                    counters.protected_tombstone += result.protected_tombstone
                    actual = list(
                        (
                            await db.scalars(
                                select(CandidateLanguage).where(
                                    CandidateLanguage.candidate_id == candidate_id
                                )
                            )
                        ).all()
                    )

                if parity_matches(expected, actual):
                    counters.parity_exact += 1
                else:
                    counters.add_conflict(candidate_id)

            processed_this_run += len(batch)
            if apply:
                await db.commit()
                _write_checkpoint(checkpoint_path, counters)
            else:
                await db.rollback()

    return counters


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Persist normalized facts. Without this flag the run is read-only.",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an --apply run from the checkpoint cursor.",
    )
    parser.add_argument("--batch-size", type=int, default=250)
    parser.add_argument("--max-candidates", type=int)
    parser.add_argument(
        "--checkpoint-file",
        type=Path,
        default=DEFAULT_CHECKPOINT,
    )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    counters = asyncio.run(
        run_backfill(
            apply=args.apply,
            resume=args.resume,
            batch_size=args.batch_size,
            max_candidates=args.max_candidates,
            checkpoint_path=args.checkpoint_file,
        )
    )
    print(
        json.dumps(
            {
                "mode": "apply" if args.apply else "dry-run",
                **asdict(counters),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":  # pragma: no cover
    main()
