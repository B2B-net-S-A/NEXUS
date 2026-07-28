"""Strict, read-only Traffit intake for candidate contact opportunities.

This poller is intentionally separate from the daily importer:

* it only reads ``/employees/recruitment_history``;
* it never writes a Traffit stage, webhook, outbox or remote contact status;
* HTTP 400 for ``X-Request-Filter`` is terminal for the tick (no full scan);
* a durable tuple cursor plus event ledger makes overlap/restarts idempotent.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate
from app.models.candidate_contact import (
    CandidateContactOpportunity,
    CandidateContactTraffitCursor,
    CandidateContactTraffitLedger,
)
from app.models.job import Job
from app.services.candidate_contact import (
    close_contact_opportunity,
    ensure_contact_opportunity,
)
from app.services.traffit.client import TraffitClient, TraffitConfig

logger = logging.getLogger(__name__)

_STREAM = "recruitment_history_contact"
_LOCK_NAME = "nexus:candidate-contact:traffit-intake:v1"
_OVERDUE_POLL_BACKOFF_SECONDS = 1.0
_PAYLOAD_CONFLICT_MARKER = "_candidate_contact_payload_conflict"
_PAYLOAD_CONFLICT_ERROR = "conflicting_payloads_for_external_event_id"


@dataclass
class TraffitContactIntakeStats:
    fetched: int = 0
    processed: int = 0
    closed: int = 0
    duplicates: int = 0
    ignored_non_start: int = 0
    exceptions: int = 0
    malformed: int = 0
    ignored_stale_start: int = 0
    lock_contended: bool = False
    filter_rejected: bool = False


_TERMINAL_WORKFLOW_TYPES = {"end-good", "end-bad", "wait"}


def _workflow_contact_action(raw: dict[str, Any]) -> str | None:
    workflow_state = raw.get("workflow_state")
    if not isinstance(workflow_state, dict):
        return None
    workflow_type = str(workflow_state.get("type") or "").strip()
    if not workflow_type:
        return None
    if (
        bool(workflow_state.get("is_rejection"))
        or workflow_type in _TERMINAL_WORKFLOW_TYPES
    ):
        return "close"
    return "ensure"


def _poll_sleep_seconds(interval: float, elapsed: float) -> float:
    """Keep start-to-start cadence bounded without creating a hot loop."""

    remaining = interval - max(0.0, elapsed)
    if remaining > 0:
        return remaining
    return _OVERDUE_POLL_BACKOFF_SECONDS


def _parse_source_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            parsed = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
    else:
        raise ValueError("recruitment_history missing created_at/date")
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _external_id_key(value: str) -> tuple[int, int | str]:
    """Numeric Traffit ids sort numerically; opaque future ids sort as text."""

    try:
        return (0, int(value))
    except (TypeError, ValueError):
        return (1, value)


def _event_sort_key(raw: dict[str, Any]) -> tuple[datetime, tuple[int, int | str]]:
    created_at = _parse_source_datetime(raw.get("created_at") or raw.get("date"))
    external_id = raw.get("id")
    if external_id is None:
        raise ValueError("recruitment_history missing id")
    return (created_at, _external_id_key(str(external_id)))


def _exception_retry_statement(*, limit: int = 100):
    """Select the least-recently attempted durable exceptions first."""

    return (
        select(CandidateContactTraffitLedger)
        .where(CandidateContactTraffitLedger.status == "exception")
        .order_by(
            CandidateContactTraffitLedger.last_attempt_at.asc().nulls_first(),
            CandidateContactTraffitLedger.source_created_at.asc(),
            CandidateContactTraffitLedger.id.asc(),
        )
        .limit(limit)
    )


async def _latest_processed_pair_event(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
) -> CandidateContactTraffitLedger | None:
    """Return the source-latest processed event for one mapped pair."""

    latest_at = await db.scalar(
        select(func.max(CandidateContactTraffitLedger.source_created_at)).where(
            CandidateContactTraffitLedger.status == "processed",
            CandidateContactTraffitLedger.candidate_id == candidate_id,
            CandidateContactTraffitLedger.job_id == job_id,
        )
    )
    if latest_at is None:
        return None
    rows = (
        (
            await db.execute(
                select(CandidateContactTraffitLedger).where(
                    CandidateContactTraffitLedger.status == "processed",
                    CandidateContactTraffitLedger.candidate_id == candidate_id,
                    CandidateContactTraffitLedger.job_id == job_id,
                    CandidateContactTraffitLedger.source_created_at == latest_at,
                )
            )
        )
        .scalars()
        .all()
    )
    return (
        max(rows, key=lambda row: _external_id_key(row.external_event_id))
        if rows
        else None
    )


async def _has_newer_processed_terminal(
    db: AsyncSession,
    *,
    candidate_id: int,
    job_id: int,
    source_created_at: datetime,
    external_event_id: str,
) -> bool:
    """Fence a late start when the durable pair watermark is terminal."""

    latest = await _latest_processed_pair_event(
        db,
        candidate_id=candidate_id,
        job_id=job_id,
    )
    if latest is None or _workflow_contact_action(latest.raw_payload) != "close":
        return False
    latest_key = (
        latest.source_created_at,
        _external_id_key(latest.external_event_id),
    )
    incoming_key = (
        source_created_at,
        _external_id_key(external_event_id),
    )
    return latest_key > incoming_key


def _payload_hash(raw: dict[str, Any]) -> str:
    canonical = json.dumps(
        raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _nested_external_id(raw: dict[str, Any], field: str) -> str | None:
    value = raw.get(field)
    if not isinstance(value, dict) or value.get("id") is None:
        return None
    return str(value["id"])


def _deduplicate_event_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], int, int]:
    """Collapse one fetched page-set before any DB/domain side effect."""

    grouped: dict[str, list[dict[str, Any]]] = {}
    for raw in rows:
        grouped.setdefault(str(raw["id"]), []).append(raw)

    output: list[dict[str, Any]] = []
    duplicate_count = 0
    conflict_count = 0
    for external_id, variants in grouped.items():
        duplicate_count += len(variants) - 1
        existing_conflicts = [
            raw for raw in variants if raw.get(_PAYLOAD_CONFLICT_MARKER) is True
        ]
        hashes = {_payload_hash(raw) for raw in variants}
        if len(hashes) == 1 and not existing_conflicts:
            output.append(variants[0])
            continue

        conflict_count += 1
        if existing_conflicts and len(variants) == 1:
            output.append(existing_conflicts[0])
            continue

        latest_at = max(_event_sort_key(raw)[0] for raw in variants)
        payload: dict[str, Any] = {
            "id": external_id,
            "created_at": latest_at.isoformat(),
            _PAYLOAD_CONFLICT_MARKER: True,
            "payload_hashes": sorted(hashes),
        }
        candidate_ids = {
            value
            for value in (_nested_external_id(raw, "employee") for raw in variants)
            if value is not None
        }
        job_ids = {
            value
            for value in (_nested_external_id(raw, "recruitment") for raw in variants)
            if value is not None
        }
        if len(candidate_ids) == 1:
            payload["employee"] = {"id": next(iter(candidate_ids))}
        if len(job_ids) == 1:
            payload["recruitment"] = {"id": next(iter(job_ids))}
        output.append(payload)
    return output, duplicate_count, conflict_count


async def _exact_external_match(
    db: AsyncSession,
    model,
    external_id: str | None,
):
    if external_id is None:
        return None, "missing_external_id"
    rows = (
        (
            await db.execute(
                select(model)
                .where(
                    model.external_source == "traffit",
                    model.external_id == external_id,
                )
                .limit(2)
            )
        )
        .scalars()
        .all()
    )
    if not rows:
        return None, "mapping_not_found"
    if len(rows) > 1:
        return None, "mapping_ambiguous"
    return rows[0], None


async def _get_or_create_cursor(
    db: AsyncSession, *, activation_at: datetime, now: datetime
) -> CandidateContactTraffitCursor:
    cursor = await db.scalar(
        select(CandidateContactTraffitCursor)
        .where(CandidateContactTraffitCursor.stream == _STREAM)
        .with_for_update()
    )
    if cursor is None:
        cursor = CandidateContactTraffitCursor(
            stream=_STREAM,
            cursor_created_at=activation_at,
            cursor_external_id="0",
            status="idle",
        )
        db.add(cursor)
        await db.flush()
    cursor.last_attempt_at = now
    return cursor


async def _upsert_ledger(
    db: AsyncSession,
    *,
    raw: dict[str, Any],
    source_created_at: datetime,
    status: str,
    error: str | None,
    candidate_external_id: str | None,
    job_external_id: str | None,
    candidate_id: int | None = None,
    job_id: int | None = None,
    case_id: int | None = None,
    opportunity_id: int | None = None,
    processed_at: datetime | None = None,
    attempted_at: datetime | None = None,
) -> CandidateContactTraffitLedger:
    external_event_id = str(raw["id"])
    ledger = await db.scalar(
        select(CandidateContactTraffitLedger).where(
            CandidateContactTraffitLedger.external_event_id == external_event_id
        )
    )
    if ledger is None:
        ledger = CandidateContactTraffitLedger(
            external_event_id=external_event_id,
            source_created_at=source_created_at,
            candidate_external_id=candidate_external_id,
            job_external_id=job_external_id,
            status=status,
            payload_hash=_payload_hash(raw),
            raw_payload=raw,
        )
        db.add(ledger)
    ledger.source_created_at = source_created_at
    ledger.candidate_external_id = candidate_external_id
    ledger.job_external_id = job_external_id
    ledger.candidate_id = candidate_id
    ledger.job_id = job_id
    ledger.case_id = case_id
    ledger.opportunity_id = opportunity_id
    ledger.status = status
    ledger.payload_hash = _payload_hash(raw)
    ledger.raw_payload = raw
    ledger.attempts = int(ledger.attempts or 0) + 1
    ledger.last_attempt_at = attempted_at or datetime.now(timezone.utc)
    ledger.error = error
    ledger.processed_at = processed_at
    return ledger


def _strict_filter(since: datetime) -> dict[str, dict[str, str]]:
    # Traffit's documented filter is day-granular.  The local tuple cursor and
    # ledger perform the precise boundary check after the overlapping read.
    return {
        "created_at": {
            "value": since.strftime("%Y-%m-%d"),
            "comparison": ">=",
        }
    }


async def run_traffit_contact_intake_once(
    db: AsyncSession,
    client: TraffitClient,
    *,
    now: datetime | None = None,
) -> TraffitContactIntakeStats:
    """Fetch and apply one strict intake page-set inside the caller transaction."""

    stats = TraffitContactIntakeStats()
    if not (
        settings.CANDIDATE_CONTACT_ENABLED
        and settings.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED
    ):
        return stats

    activation_raw = settings.CANDIDATE_CONTACT_ACTIVATION_AT
    if activation_raw is None:
        logger.error(
            "Candidate contact Traffit intake enabled without activation timestamp"
        )
        return stats
    activation_at = (
        activation_raw.replace(tzinfo=timezone.utc)
        if activation_raw.tzinfo is None
        else activation_raw.astimezone(timezone.utc)
    )
    tick_now = now or datetime.now(timezone.utc)
    if tick_now.tzinfo is None:
        tick_now = tick_now.replace(tzinfo=timezone.utc)
    else:
        tick_now = tick_now.astimezone(timezone.utc)

    # Multiple uvicorn processes may start the same loop.  The transaction
    # advisory lock makes one poll the sole owner without blocking the others.
    lock_acquired = await db.scalar(
        text("SELECT pg_try_advisory_xact_lock(hashtext(:name))"),
        {"name": _LOCK_NAME},
    )
    if not lock_acquired:
        stats.lock_contended = True
        return stats

    cursor = await _get_or_create_cursor(db, activation_at=activation_at, now=tick_now)
    cursor_at = cursor.cursor_created_at or activation_at
    overlap = timedelta(
        minutes=max(
            1, min(int(settings.CANDIDATE_CONTACT_TRAFFIT_OVERLAP_MINUTES), 1440)
        )
    )
    since = max(activation_at, cursor_at - overlap)

    # Fetch completely before changing any ledger/cursor rows.  Therefore a
    # rejected filter or a later-page HTTP failure cannot partially advance
    # the durable position.
    try:
        fetched = [
            raw
            async for raw in client.get_paginated(
                "/employees/recruitment_history",
                page_size=100,
                filter_=_strict_filter(since),
                fallback_on_filter_rejection=False,
            )
        ]
    except Exception as exc:  # noqa: BLE001 - persist every remote tick failure
        cursor.status = "error"
        cursor.last_error = str(exc)[:2000]
        if "HTTP 400" in str(exc):
            stats.filter_rejected = True
        return stats

    stats.fetched = len(fetched)
    fetched_ids = {
        str(raw["id"]) for raw in fetched if isinstance(raw, dict) and "id" in raw
    }
    retry_rows = (await db.execute(_exception_retry_statement())).scalars().all()
    fetched.extend(
        row.raw_payload
        for row in retry_rows
        if row.raw_payload and row.external_event_id not in fetched_ids
    )
    sortable: list[dict[str, Any]] = []
    for raw in fetched:
        try:
            _event_sort_key(raw)
        except (TypeError, ValueError):
            stats.malformed += 1
            continue
        sortable.append(raw)
    sortable, within_batch_duplicates, payload_conflicts = _deduplicate_event_rows(
        sortable
    )
    stats.duplicates += within_batch_duplicates
    sortable.sort(key=_event_sort_key)

    safe_cursor_created_at = cursor_at
    safe_cursor_external_id = cursor.cursor_external_id or "0"
    first_error: str | None = (
        "malformed recruitment_history row" if stats.malformed else None
    )
    if payload_conflicts and first_error is None:
        first_error = _PAYLOAD_CONFLICT_ERROR
    allow_cursor_advance = not stats.malformed and not payload_conflicts

    def advance_cursor(source_created_at: datetime, external_event_id: str) -> None:
        nonlocal safe_cursor_created_at, safe_cursor_external_id
        if not allow_cursor_advance:
            return
        if source_created_at > safe_cursor_created_at or (
            source_created_at == safe_cursor_created_at
            and _external_id_key(external_event_id)
            > _external_id_key(safe_cursor_external_id)
        ):
            safe_cursor_created_at = source_created_at
            safe_cursor_external_id = external_event_id

    for raw in sortable:
        source_created_at, _ = _event_sort_key(raw)
        if source_created_at < activation_at:
            continue
        external_event_id = str(raw["id"])
        candidate_external_id = _nested_external_id(raw, "employee")
        job_external_id = _nested_external_id(raw, "recruitment")

        if raw.get(_PAYLOAD_CONFLICT_MARKER) is True:
            await _upsert_ledger(
                db,
                raw=raw,
                source_created_at=source_created_at,
                status="exception",
                error=_PAYLOAD_CONFLICT_ERROR,
                candidate_external_id=candidate_external_id,
                job_external_id=job_external_id,
                attempted_at=tick_now,
            )
            stats.exceptions += 1
            first_error = first_error or _PAYLOAD_CONFLICT_ERROR
            continue

        existing = await db.scalar(
            select(CandidateContactTraffitLedger).where(
                CandidateContactTraffitLedger.external_event_id == external_event_id
            )
        )
        if existing is not None and existing.status == "processed":
            stats.duplicates += 1
            advance_cursor(source_created_at, external_event_id)
            continue

        action = _workflow_contact_action(raw)
        if action is None:
            error = "missing_or_invalid_workflow_state"
            await _upsert_ledger(
                db,
                raw=raw,
                source_created_at=source_created_at,
                status="exception",
                error=error,
                candidate_external_id=candidate_external_id,
                job_external_id=job_external_id,
                attempted_at=tick_now,
            )
            stats.exceptions += 1
            first_error = first_error or error
            advance_cursor(source_created_at, external_event_id)
            continue

        candidate, candidate_error = await _exact_external_match(
            db, Candidate, candidate_external_id
        )
        job, job_error = await _exact_external_match(db, Job, job_external_id)
        mapping_errors = [
            value
            for value in (
                f"candidate:{candidate_error}" if candidate_error else None,
                f"job:{job_error}" if job_error else None,
            )
            if value
        ]
        if mapping_errors:
            error = ",".join(mapping_errors)
            await _upsert_ledger(
                db,
                raw=raw,
                source_created_at=source_created_at,
                status="exception",
                error=error,
                candidate_external_id=candidate_external_id,
                job_external_id=job_external_id,
                attempted_at=tick_now,
            )
            stats.exceptions += 1
            first_error = first_error or error
            # The complete payload is durable in the exception ledger, so the
            # remote tuple cursor may advance.  Future ticks retry ledger
            # exceptions independently of the overlap window.
            advance_cursor(source_created_at, external_event_id)
            continue

        if action == "ensure" and await _has_newer_processed_terminal(
            db,
            candidate_id=candidate.id,
            job_id=job.id,
            source_created_at=source_created_at,
            external_event_id=external_event_id,
        ):
            # A terminal may legitimately arrive after activation for a
            # process that began earlier, so it remains a processed watermark
            # instead of a permanent exception. A delayed/retried older start
            # is then acknowledged without creating an orphan open case.
            await _upsert_ledger(
                db,
                raw=raw,
                source_created_at=source_created_at,
                status="processed",
                error=None,
                candidate_external_id=candidate_external_id,
                job_external_id=job_external_id,
                candidate_id=candidate.id,
                job_id=job.id,
                processed_at=tick_now,
                attempted_at=tick_now,
            )
            stats.processed += 1
            stats.ignored_stale_start += 1
            advance_cursor(source_created_at, external_event_id)
            continue

        if action == "close":
            workflow_state = raw["workflow_state"]
            workflow_type = str(workflow_state.get("type") or "").strip()
            reason = (
                "traffit_pipeline_terminal:rejected"
                if workflow_state.get("is_rejection")
                else f"traffit_pipeline_terminal:{workflow_type}"
            )
            case = await close_contact_opportunity(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                reason=reason,
                occurred_at=source_created_at,
                source="traffit",
                source_external_ref=external_event_id,
            )
        else:
            case = await ensure_contact_opportunity(
                db,
                candidate_id=candidate.id,
                job_id=job.id,
                source="traffit",
                source_external_ref=external_event_id,
                occurred_at=source_created_at,
                assign_if_possible=(settings.CANDIDATE_CONTACT_ASSIGNMENT_ENABLED),
            )
        await db.flush()
        opportunity = await db.scalar(
            select(CandidateContactOpportunity).where(
                CandidateContactOpportunity.candidate_id == candidate.id,
                CandidateContactOpportunity.job_id == job.id,
            )
        )
        if (
            action == "close"
            and opportunity is not None
            and opportunity.closed_at is not None
        ):
            stats.closed += 1
        await _upsert_ledger(
            db,
            raw=raw,
            source_created_at=source_created_at,
            status="processed",
            error=None,
            candidate_external_id=candidate_external_id,
            job_external_id=job_external_id,
            candidate_id=candidate.id,
            job_id=job.id,
            case_id=case.id if case is not None else None,
            opportunity_id=opportunity.id if opportunity is not None else None,
            processed_at=tick_now,
            attempted_at=tick_now,
        )
        stats.processed += 1
        advance_cursor(source_created_at, external_event_id)

    cursor.cursor_created_at = safe_cursor_created_at
    cursor.cursor_external_id = safe_cursor_external_id
    cursor.status = "exception" if stats.exceptions or stats.malformed else "ok"
    cursor.last_error = first_error
    if stats.exceptions == 0 and stats.malformed == 0:
        cursor.last_success_at = tick_now
    return stats


async def traffit_contact_intake_loop() -> None:
    """Run the strict read-only poll at a clamped cadence."""

    if not (
        settings.CANDIDATE_CONTACT_ENABLED
        and settings.CANDIDATE_CONTACT_TRAFFIT_INTAKE_ENABLED
    ):
        logger.info("Candidate contact Traffit intake disabled")
        return
    if settings.CANDIDATE_CONTACT_ACTIVATION_AT is None:
        logger.error(
            "Candidate contact Traffit intake not started: activation timestamp missing"
        )
        return

    interval = max(
        30,
        min(int(settings.CANDIDATE_CONTACT_TRAFFIT_POLL_INTERVAL_SECONDS), 300),
    )
    while True:
        loop = asyncio.get_running_loop()
        tick_started_at = loop.time()
        try:
            config = TraffitConfig.from_env()
            async with TraffitClient(config) as client, AsyncSessionLocal() as db:
                stats = await run_traffit_contact_intake_once(db, client)
                await db.commit()
                logger.info("Candidate contact Traffit intake stats=%s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("Candidate contact Traffit intake tick failed")
        elapsed = loop.time() - tick_started_at
        await asyncio.sleep(_poll_sleep_seconds(interval, elapsed))


__all__ = [
    "TraffitContactIntakeStats",
    "run_traffit_contact_intake_once",
    "traffit_contact_intake_loop",
]
