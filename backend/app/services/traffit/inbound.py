"""Durable Traffit → Nexus inbox, field merge, polling and reconcile scaffold."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import math
import os
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument
from app.models.job import Job, JobStatus
from app.models.recruitment_pipeline import CandidateStage
from app.models.traffit_integration import (
    TraffitEntityLink,
    TraffitSyncConflict,
    TraffitSyncRun,
    TraffitSyncRunPhase,
    TraffitWebhookEvent,
)
from app.models.traffit_sync_state import TraffitSyncState
from app.services import object_storage
from app.services.traffit.client import TraffitAPIError, TraffitClient
from app.services.traffit.importer import TraffitImporter
from app.services.traffit.mappers import (
    _parse_traffit_datetime,
    traffit_employee_to_candidate,
)
from app.services.traffit.merge import snapshot_hash, three_way_merge
from app.services.traffit.outbox import OutboxCommand, _enqueue_command

logger = logging.getLogger(__name__)

CANDIDATE_SYNC_FIELDS = (
    "name",
    "lastname",
    "email",
    "phone",
    "linkedin",
    "location",
    "status",
    "profile_about",
    "languages",
    "custom_fields",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _effective_reconcile_cursor(
    state: TraffitSyncState,
    *,
    dry_run: bool,
) -> tuple[Optional[datetime], Optional[str]]:
    """Return the live or independently persisted shadow cursor.

    A shadow run must never advance the live cursor, but its next run must
    continue from the previous shadow watermark.  If shadow mode has not run
    yet, start from the live watermark so enabling dry-run does not replay the
    entire tenant unnecessarily.
    """
    if not dry_run:
        return state.cursor_at, state.cursor_external_id

    payload = dict(state.cursor_payload or {})
    if "shadow_cursor_at" not in payload:
        return state.cursor_at, state.cursor_external_id
    shadow_at = _parse_traffit_datetime(payload.get("shadow_cursor_at"))
    if shadow_at is None:
        return state.cursor_at, state.cursor_external_id
    shadow_external_id = payload.get("shadow_cursor_external_id")
    return (
        shadow_at,
        str(shadow_external_id) if shadow_external_id is not None else None,
    )


def _candidate_snapshot(candidate: Candidate) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for name in CANDIDATE_SYNC_FIELDS:
        value = getattr(candidate, name, None)
        result[name] = value.value if hasattr(value, "value") else value
    return result


def _remote_candidate_snapshot(remote: Mapping[str, Any]) -> dict[str, Any]:
    mapped = traffit_employee_to_candidate(dict(remote), None)
    return {name: mapped.get(name) for name in CANDIDATE_SYNC_FIELDS}


async def _candidate_by_remote_id(
    db: AsyncSession, remote_id: str
) -> tuple[Optional[Candidate], Optional[TraffitEntityLink]]:
    link = await db.scalar(
        select(TraffitEntityLink).where(
            TraffitEntityLink.entity_type == "candidate",
            TraffitEntityLink.traffit_entity_id == remote_id,
        )
    )
    if link is not None and link.status == "detached":
        return None, link
    if link and link.nexus_entity_id is not None:
        candidate = await db.get(Candidate, link.nexus_entity_id)
        if candidate is not None:
            return candidate, link
    candidate = await db.scalar(
        select(Candidate).where(
            Candidate.external_source == "traffit",
            Candidate.external_id == remote_id,
        )
    )
    return candidate, link


async def _create_candidate_conflicts(
    db: AsyncSession,
    candidate: Candidate,
    link: TraffitEntityLink,
    merge: Any,
) -> int:
    created = 0
    for item in merge.conflicts:
        existing = await db.scalar(
            select(TraffitSyncConflict).where(
                TraffitSyncConflict.entity_link_id == link.id,
                TraffitSyncConflict.field_path == item.field_path,
                TraffitSyncConflict.status == "open",
            )
        )
        if existing is not None:
            existing.base_value = item.base_value
            existing.nexus_value = item.nexus_value
            existing.traffit_value = item.traffit_value
            continue
        db.add(
            TraffitSyncConflict(
                entity_link_id=link.id,
                entity_type="candidate",
                nexus_entity_id=candidate.id,
                traffit_entity_id=link.traffit_entity_id,
                candidate_id=candidate.id,
                field_path=item.field_path,
                conflict_type=item.conflict_type,
                base_value=item.base_value,
                nexus_value=item.nexus_value,
                traffit_value=item.traffit_value,
                status="open",
            )
        )
        created += 1
    return created


def _apply_candidate_patch(candidate: Candidate, patch: Mapping[str, Any]) -> None:
    for field, value in patch.items():
        if field not in CANDIDATE_SYNC_FIELDS:
            continue
        if field == "status" and value is not None:
            value = CandidateStatus(value)
        setattr(candidate, field, value)


def _snapshot_subset(
    snapshot: Mapping[str, Any], patch: Mapping[str, Any]
) -> dict[str, Any]:
    subset: dict[str, Any] = {}
    for key, value in patch.items():
        if isinstance(value, Mapping):
            original = snapshot.get(key)
            original = original if isinstance(original, Mapping) else {}
            subset[key] = {child_key: original.get(child_key) for child_key in value}
        else:
            subset[key] = snapshot.get(key)
    return subset


async def apply_remote_candidate(
    db: AsyncSession,
    remote: Mapping[str, Any],
    *,
    apply_changes: bool,
) -> dict[str, Any]:
    """Apply a candidate via three-way merge, never emitting an outbox event."""
    remote_id_raw = remote.get("id")
    if remote_id_raw is None:
        raise ValueError("Traffit employee missing id")
    remote_id = str(remote_id_raw)
    remote_snapshot = _remote_candidate_snapshot(remote)
    candidate, link = await _candidate_by_remote_id(db, remote_id)
    if link is not None and link.status == "detached":
        return {"action": "ignored_detached", "remote_id": remote_id}
    now = _utcnow()
    created_candidate = False
    matched_existing_without_link = candidate is not None and link is None
    has_pending_outbound = False
    pending_base_snapshot: dict[str, Any] = {}

    if candidate is None:
        email = str(remote_snapshot.get("email") or "").strip().lower()
        if email:
            candidate = await db.scalar(
                select(Candidate).where(func.lower(Candidate.email) == email)
            )
        if candidate is None:
            if not apply_changes:
                return {"action": "would_create", "remote_id": remote_id}
            mapped = traffit_employee_to_candidate(dict(remote), None)
            candidate = Candidate(**mapped)
            db.add(candidate)
            await db.flush()
            created_candidate = True
        else:
            # Email adoption without a shared baseline is not proof that the
            # remote record owns current values. Preserve both sides and let an
            # admin resolve divergent fields instead of overwriting Nexus.
            matched_existing_without_link = True

    if link is None:
        if not apply_changes:
            return {
                "action": "would_link",
                "remote_id": remote_id,
                "candidate_id": candidate.id,
            }
        link = TraffitEntityLink(
            entity_type="candidate",
            nexus_entity_id=candidate.id,
            traffit_entity_id=remote_id,
            candidate_id=candidate.id,
            status="active",
        )
        db.add(link)
        await db.flush()
        if created_candidate:
            # A genuinely new local row has no competing Nexus history.
            _apply_candidate_patch(candidate, remote_snapshot)
            merged_snapshot = remote_snapshot
            conflicts_created = 0
            has_conflicts = False
        else:
            nexus_snapshot = _candidate_snapshot(candidate)
            differing = [
                field
                for field in CANDIDATE_SYNC_FIELDS
                if nexus_snapshot.get(field) != remote_snapshot.get(field)
            ]
            for field in differing:
                db.add(
                    TraffitSyncConflict(
                        entity_link_id=link.id,
                        entity_type="candidate",
                        nexus_entity_id=candidate.id,
                        traffit_entity_id=remote_id,
                        candidate_id=candidate.id,
                        field_path=field,
                        conflict_type="baseline_divergence",
                        base_value=None,
                        nexus_value=nexus_snapshot.get(field),
                        traffit_value=remote_snapshot.get(field),
                        status="open",
                    )
                )
            merged_snapshot = nexus_snapshot
            conflicts_created = len(differing)
            has_conflicts = bool(differing)
            if matched_existing_without_link and has_conflicts:
                link.status = "conflict"
    else:
        nexus_snapshot = _candidate_snapshot(candidate)
        baseline_conflicts = list(
            (
                await db.scalars(
                    select(TraffitSyncConflict).where(
                        TraffitSyncConflict.entity_link_id == link.id,
                        TraffitSyncConflict.conflict_type == "baseline_divergence",
                        TraffitSyncConflict.status == "open",
                    )
                )
            ).all()
        )
        if baseline_conflicts:
            for conflict in baseline_conflicts:
                if conflict.field_path:
                    conflict.nexus_value = nexus_snapshot.get(conflict.field_path)
                    conflict.traffit_value = remote_snapshot.get(conflict.field_path)
            link.status = "conflict"
            link.last_seen_at = now
            link.traffit_snapshot_hash = snapshot_hash(remote_snapshot)
            await db.flush()
            return {
                "action": "blocked_baseline_conflict",
                "candidate_id": candidate.id,
                "remote_id": remote_id,
                "conflicts": len(baseline_conflicts),
            }
        base = link.base_snapshot or nexus_snapshot
        merge = three_way_merge(base, nexus_snapshot, remote_snapshot)
        await _create_candidate_conflicts(db, candidate, link, merge)
        conflicts_created = len(merge.conflicts)
        has_conflicts = bool(merge.conflicts)
        if apply_changes:
            _apply_candidate_patch(candidate, merge.apply_to_nexus)
        merged_snapshot = merge.merged
        if has_conflicts:
            link.status = "conflict"

        if apply_changes and merge.apply_to_traffit:
            has_pending_outbound = True
            pending_base_snapshot = dict(base)
            await _enqueue_command(
                db,
                OutboxCommand(
                    event_type="candidate.update",
                    aggregate_type="candidate",
                    aggregate_id=candidate.id,
                    candidate_id=candidate.id,
                    entity_link_id=link.id,
                    origin="reconcile",
                    payload={
                        "fields": merge.apply_to_traffit,
                        "base_snapshot": _snapshot_subset(base, merge.apply_to_traffit),
                    },
                    changed_fields=tuple(merge.apply_to_traffit),
                    idempotency_key=(
                        "reconcile:candidate:"
                        + hashlib.sha256(
                            (
                                f"{candidate.id}:"
                                f"{snapshot_hash(merge.apply_to_traffit)}:"
                                f"{snapshot_hash(_snapshot_subset(base, merge.apply_to_traffit))}"
                            ).encode()
                        ).hexdigest()
                    ),
                    priority=20,
                ),
            )

    if apply_changes:
        digest = snapshot_hash(merged_snapshot)
        # Local-only changes are not part of the shared baseline until their
        # outbox event succeeds. Keeping the old base makes retry/conflict
        # detection truthful.
        link.base_snapshot = (
            pending_base_snapshot if has_pending_outbound else merged_snapshot
        )
        link.nexus_snapshot_hash = snapshot_hash(_candidate_snapshot(candidate))
        link.traffit_snapshot_hash = snapshot_hash(remote_snapshot)
        link.shared_snapshot_hash = digest
        link.last_seen_at = now
        link.traffit_updated_at = now
        link.last_direction = "inbound"
        link.last_error = None
        if has_pending_outbound and not has_conflicts:
            link.status = "pending"
        elif not has_conflicts:
            link.status = "synced"
            link.last_synced_at = now
        await db.flush()
    return {
        "action": "applied" if apply_changes else "compared",
        "candidate_id": candidate.id,
        "remote_id": remote_id,
        "conflicts": conflicts_created,
    }


async def sync_candidate_file_manifest(
    db: AsyncSession,
    client: TraffitClient,
    *,
    employee_id: str,
    apply_changes: bool,
) -> dict[str, int]:
    """Add/version files by SHA; disappearance only opens a manual action."""
    candidate, _ = await _candidate_by_remote_id(db, employee_id)
    if candidate is None:
        return {"seen": 0, "added": 0, "missing": 0}
    response = await client.get_json(f"/employees/{employee_id}/files")
    files = (
        [item for item in response if isinstance(item, dict)]
        if isinstance(response, list)
        else []
    )
    seen_remote_ids: set[str] = set()
    added = 0
    now = _utcnow()

    for item in files:
        if item.get("id") is None:
            continue
        file_id = str(item["id"])
        remote_file_key = f"{employee_id}-{file_id}"
        seen_remote_ids.add(remote_file_key)
        link = await db.scalar(
            select(TraffitEntityLink).where(
                TraffitEntityLink.entity_type == "file",
                TraffitEntityLink.candidate_id == candidate.id,
                TraffitEntityLink.traffit_entity_id.in_((file_id, remote_file_key)),
            )
        )
        if link is not None:
            if link.status == "detached":
                continue
            if apply_changes:
                link.traffit_entity_id = remote_file_key
                link.last_seen_at = now
                link.missing_since = None
                link.pending_delete_at = None
            continue
        if not apply_changes:
            added += 1
            continue
        content_response = await client.request(
            "GET",
            f"/employees/{employee_id}/files/{file_id}/content",
            expected_statuses=(200,),
        )
        content = content_response.content
        digest = hashlib.sha256(content).hexdigest()
        document = await db.scalar(
            select(CandidateDocument).where(
                CandidateDocument.candidate_id == candidate.id,
                CandidateDocument.content_sha256 == digest,
                CandidateDocument.source_deleted_at.is_(None),
            )
        )
        filename = str(item.get("filename") or item.get("name") or f"traffit-{file_id}")
        content_type = str(
            item.get("content_type")
            or content_response.headers.get("Content-Type")
            or "application/octet-stream"
        )
        if document is None:
            storage_key: Optional[str] = None
            file_content: Optional[bytes] = content
            if object_storage.is_available():
                storage_key = await asyncio.to_thread(
                    object_storage.upload_cv, content, filename, content_type
                )
                file_content = None
            document = CandidateDocument(
                candidate_id=candidate.id,
                filename=filename,
                file_content=file_content,
                storage_key=storage_key,
                content_type=content_type,
                size_bytes=len(content),
                is_primary=False,
                uploaded_at=now,
                external_source="traffit",
                external_id=f"{employee_id}-{file_id}",
                content_sha256=digest,
            )
            db.add(document)
            await db.flush()
            added += 1
        else:
            document.external_source = "traffit"
            document.external_id = f"{employee_id}-{file_id}"

        db.add(
            TraffitEntityLink(
                entity_type="file",
                nexus_entity_id=document.id,
                traffit_entity_id=remote_file_key,
                candidate_id=candidate.id,
                status="synced",
                base_snapshot={
                    "filename": filename,
                    "size_bytes": len(content),
                    "content_sha256": digest,
                    "missing_scans": 0,
                },
                nexus_snapshot_hash=digest,
                traffit_snapshot_hash=digest,
                shared_snapshot_hash=digest,
                last_seen_at=now,
                last_synced_at=now,
                last_direction="inbound",
            )
        )

    existing_links = list(
        (
            await db.scalars(
                select(TraffitEntityLink).where(
                    TraffitEntityLink.entity_type == "file",
                    TraffitEntityLink.candidate_id == candidate.id,
                    TraffitEntityLink.traffit_entity_id.is_not(None),
                    TraffitEntityLink.status != "detached",
                )
            )
        ).all()
    )
    missing = 0
    for link in existing_links:
        if link.traffit_entity_id in seen_remote_ids:
            continue
        missing += 1
        if not apply_changes:
            continue
        snapshot = dict(link.base_snapshot or {})
        scans = int(snapshot.get("missing_scans", 0)) + 1
        snapshot["missing_scans"] = scans
        link.base_snapshot = snapshot
        if link.missing_since is None:
            link.missing_since = now
        if scans >= 2 and link.missing_since <= now - timedelta(days=7):
            link.pending_delete_at = now
            link.status = "manual_action_required"
            existing_conflict = await db.scalar(
                select(TraffitSyncConflict).where(
                    TraffitSyncConflict.entity_link_id == link.id,
                    TraffitSyncConflict.conflict_type == "remote_file_missing",
                    TraffitSyncConflict.status == "manual_action_required",
                )
            )
            if existing_conflict is None:
                db.add(
                    TraffitSyncConflict(
                        entity_link_id=link.id,
                        entity_type="file",
                        nexus_entity_id=link.nexus_entity_id,
                        traffit_entity_id=link.traffit_entity_id,
                        candidate_id=candidate.id,
                        field_path="source_deleted_at",
                        conflict_type="remote_file_missing",
                        nexus_value={"exists": True},
                        traffit_value={"exists": False},
                        status="manual_action_required",
                    )
                )
    await db.flush()
    return {"seen": len(seen_remote_ids), "added": added, "missing": missing}


async def _active_candidate_targets(
    db: AsyncSession,
) -> list[tuple[int, str]]:
    """Candidates assigned to published Traffit-managed recruitments."""
    candidate_link = TraffitEntityLink.__table__.alias("active_candidate_link")
    rows = (
        await db.execute(
            select(
                Candidate.id,
                func.coalesce(
                    candidate_link.c.traffit_entity_id,
                    Candidate.external_id,
                ),
            )
            .join(CandidateStage, CandidateStage.candidate_id == Candidate.id)
            .join(Job, Job.id == CandidateStage.job_id)
            .outerjoin(
                candidate_link,
                (candidate_link.c.entity_type == "candidate")
                & (candidate_link.c.nexus_entity_id == Candidate.id),
            )
            .where(
                Job.status == JobStatus.published,
                Job.external_source == "traffit",
                or_(
                    candidate_link.c.status.is_(None),
                    candidate_link.c.status != "detached",
                ),
                func.coalesce(
                    candidate_link.c.traffit_entity_id,
                    Candidate.external_id,
                ).is_not(None),
            )
            .distinct()
            .order_by(Candidate.id)
        )
    ).all()
    return [(int(candidate_id), str(remote_id)) for candidate_id, remote_id in rows]


async def _iter_active_remote_candidates(db: AsyncSession, client: TraffitClient):
    for _candidate_id, remote_id in await _active_candidate_targets(db):
        remote = await client.get_json(f"/employees/{remote_id}")
        if not isinstance(remote, Mapping):
            raise RuntimeError(f"Traffit employee {remote_id} returned a non-object")
        yield remote


async def run_active_file_manifest_shard(
    db: AsyncSession,
    client: TraffitClient,
    *,
    apply_changes: bool,
) -> dict[str, Any]:
    """Scan a persisted shard of candidates assigned to published Traffit jobs.

    Two scheduler cycles must cover the active population for a ten-minute
    sweep. The status remains explicitly not-ready until the API budget is
    confirmed and the measured sweep satisfies that bound.
    """
    phase_name = "integration:file_manifest_shard"
    state = await _state_for_phase(db, phase_name)
    targets = await _active_candidate_targets(db)
    payload = dict(state.cursor_payload or {})
    now = _utcnow()
    sweep_key = "sweep_started_at" if apply_changes else "shadow_sweep_started_at"
    cursor_key = "shadow_cursor_external_id"
    try:
        sweep_started = datetime.fromisoformat(payload.get(sweep_key, ""))
        if sweep_started.tzinfo is None:
            sweep_started = sweep_started.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        sweep_started = now
    persisted_cursor = (
        state.cursor_external_id if apply_changes else payload.get(cursor_key)
    )
    last_local_id = int(persisted_cursor or 0)
    original_cursor_external_id = persisted_cursor
    remaining = [(cid, rid) for cid, rid in targets if cid > last_local_id]
    if not remaining and targets:
        last_local_id = 0
        remaining = list(targets)
        sweep_started = now

    control_settings: dict[str, Any] = {}
    try:
        from app.services.traffit.control import get_control_row

        control = await get_control_row(db)
        control_settings = dict(control.settings or {}) if control else {}
    except Exception:  # pragma: no cover - migration rollout compatibility
        control_settings = {}
    confirmed_raw = os.environ.get("TRAFFIT_INTEGRATION_FILE_SLO_RATE_BUDGET_CONFIRMED")
    budget_confirmed = (
        confirmed_raw.strip().lower() in {"1", "true", "yes", "on"}
        if confirmed_raw is not None
        else bool(control_settings.get("file_slo_rate_budget_confirmed", False))
    )
    configured_batch = max(
        1, int(os.environ.get("TRAFFIT_INTEGRATION_FILE_SHARD_SIZE", "500"))
    )
    per_cycle_needed = max(1, math.ceil(len(targets) / 2)) if targets else 0
    # Reserve 20% for webhook/outbox traffic; every candidate needs at least
    # one manifest request and new files need additional content requests.
    per_cycle_capacity = max(1, int(client.config.throttle_rps * 300 * 0.8))
    capacity_sufficient = per_cycle_needed <= per_cycle_capacity
    batch_size = configured_batch
    if budget_confirmed and capacity_sufficient:
        batch_size = max(batch_size, per_cycle_needed)
    batch_size = min(batch_size, per_cycle_capacity)
    selected = remaining[:batch_size]
    totals = {"seen": 0, "added": 0, "missing": 0, "errors": []}
    for _candidate_id, remote_id in selected:
        try:
            result = await sync_candidate_file_manifest(
                db,
                client,
                employee_id=str(remote_id),
                apply_changes=apply_changes,
            )
            for key in ("seen", "added", "missing"):
                totals[key] += result[key]
        except Exception as exc:  # noqa: BLE001 - isolate one candidate
            totals["errors"].append(
                {"employee_id": str(remote_id), "error": str(exc)[:500]}
            )

    finished = _utcnow()
    reached_end = (not targets or len(selected) == len(remaining)) and not totals[
        "errors"
    ]
    next_cursor_external_id = original_cursor_external_id
    if selected and not totals["errors"]:
        next_cursor_external_id = str(selected[-1][0])
    if reached_end:
        sweep_seconds = max(0, int((finished - sweep_started).total_seconds()))
        file_slo_ready = (
            budget_confirmed
            and capacity_sufficient
            and sweep_seconds <= 600
            and not totals["errors"]
        )
        next_cursor_external_id = None
        next_sweep_started = finished
    else:
        sweep_seconds = None
        file_slo_ready = False
        next_sweep_started = sweep_started
    reason = None
    if not budget_confirmed:
        reason = "Traffit file-manifest API budget/rate limit not confirmed"
    elif not capacity_sufficient:
        reason = (
            f"active population requires {per_cycle_needed} manifests/cycle, "
            f"safe capacity is {per_cycle_capacity}"
        )
    elif totals["errors"]:
        reason = "file manifest shard contains errors"
    elif not reached_end:
        reason = "active file manifest sweep incomplete"
    elif sweep_seconds is not None and sweep_seconds > 600:
        reason = f"measured active file sweep took {sweep_seconds}s"

    metrics = {
        "sweep_started_at": next_sweep_started.isoformat(),
        "active_candidates": len(targets),
        "processed_in_shard": len(selected),
        "per_cycle_needed": per_cycle_needed,
        "safe_per_cycle_capacity": per_cycle_capacity,
        "rate_budget_confirmed": budget_confirmed,
        "file_slo_ready": file_slo_ready,
        "file_slo_blocked_reason": reason,
        "last_complete_sweep_seconds": sweep_seconds,
    }
    if apply_changes:
        state.cursor_external_id = next_cursor_external_id
        state.cursor_payload = {**payload, **metrics, "shadow_mode": False}
    else:
        state.cursor_payload = {
            **payload,
            cursor_key: next_cursor_external_id,
            "shadow_sweep_started_at": next_sweep_started.isoformat(),
            "shadow_active_candidates": len(targets),
            "shadow_processed_in_shard": len(selected),
            "shadow_per_cycle_needed": per_cycle_needed,
            "shadow_safe_per_cycle_capacity": per_cycle_capacity,
            "shadow_rate_budget_confirmed": budget_confirmed,
            "shadow_file_slo_ready": file_slo_ready,
            "shadow_file_slo_blocked_reason": reason,
            "shadow_last_complete_sweep_seconds": sweep_seconds,
            "shadow_mode": True,
        }
    if apply_changes:
        state.last_attempt_at = now
        state.last_status = "ok" if not totals["errors"] else "errors"
        state.last_error = str(totals["errors"][:3]) if totals["errors"] else None
        if not totals["errors"]:
            state.last_success_at = finished
        state.next_due_at = finished + timedelta(minutes=5)
        state.stats = {**totals, **metrics, "shadow_mode": False}
    await db.flush()
    return {
        "processed": len(selected),
        "inserted": totals["added"],
        "updated": 0,
        "skipped": 0,
        "errors": totals["errors"],
        **metrics,
        "shadow_mode": not apply_changes,
    }


async def reconcile_entity_absence(
    db: AsyncSession,
    *,
    entity_type: str,
    seen_remote_ids: set[str],
    baseline_only: bool,
) -> dict[str, int]:
    """Two-strike + grace-period absence ledger; never hard-deletes."""
    now = _utcnow()
    links = list(
        (
            await db.scalars(
                select(TraffitEntityLink).where(
                    TraffitEntityLink.entity_type == entity_type,
                    TraffitEntityLink.traffit_entity_id.is_not(None),
                    TraffitEntityLink.status != "detached",
                )
            )
        ).all()
    )
    result = {"seen": 0, "missing": 0, "manual_actions": 0}
    for link in links:
        remote_id = str(link.traffit_entity_id)
        snapshot = dict(link.base_snapshot or {})
        if remote_id in seen_remote_ids:
            result["seen"] += 1
            snapshot["absence_scans"] = 0
            link.base_snapshot = snapshot
            link.last_seen_at = now
            link.missing_since = None
            link.pending_delete_at = None
            if (
                link.status == "manual_action_required"
                and link.last_error == "remote_missing"
            ):
                link.status = "synced"
                link.last_error = None
            continue
        result["missing"] += 1
        if baseline_only:
            continue
        scans = int(snapshot.get("absence_scans", 0)) + 1
        snapshot["absence_scans"] = scans
        link.base_snapshot = snapshot
        if link.missing_since is None:
            link.missing_since = now
        if scans < 2 or link.missing_since > now - timedelta(days=7):
            continue
        link.pending_delete_at = now
        link.status = "manual_action_required"
        link.last_error = "remote_missing"
        conflict = await db.scalar(
            select(TraffitSyncConflict).where(
                TraffitSyncConflict.entity_link_id == link.id,
                TraffitSyncConflict.conflict_type == "remote_entity_missing",
                TraffitSyncConflict.status == "manual_action_required",
            )
        )
        if conflict is None:
            db.add(
                TraffitSyncConflict(
                    entity_link_id=link.id,
                    entity_type=entity_type,
                    nexus_entity_id=link.nexus_entity_id,
                    traffit_entity_id=link.traffit_entity_id,
                    candidate_id=link.candidate_id,
                    field_path="source_deleted_at",
                    conflict_type="remote_entity_missing",
                    nexus_value={"exists": True},
                    traffit_value={"exists": False},
                    status="manual_action_required",
                )
            )
            result["manual_actions"] += 1
    await db.flush()
    return result


async def _backfill_job_links(db: AsyncSession, seen_remote_ids: set[str]) -> None:
    if not seen_remote_ids:
        return
    jobs = list(
        (
            await db.scalars(
                select(Job).where(
                    Job.external_source == "traffit",
                    Job.external_id.in_(seen_remote_ids),
                )
            )
        ).all()
    )
    for job in jobs:
        link = await db.scalar(
            select(TraffitEntityLink).where(
                TraffitEntityLink.entity_type == "job",
                TraffitEntityLink.nexus_entity_id == job.id,
            )
        )
        if link is None:
            db.add(
                TraffitEntityLink(
                    entity_type="job",
                    nexus_entity_id=job.id,
                    traffit_entity_id=str(job.external_id),
                    status="synced",
                    base_snapshot={"external_id": str(job.external_id)},
                    last_seen_at=_utcnow(),
                    last_synced_at=_utcnow(),
                    last_direction="inbound",
                )
            )
        else:
            if link.status == "detached":
                continue
            link.traffit_entity_id = str(job.external_id)
            link.last_seen_at = _utcnow()
    await db.flush()


async def claim_webhook_events(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int = 50,
    include_shadowed: bool = False,
) -> list[TraffitWebhookEvent]:
    now = _utcnow()
    rows = list(
        (
            await db.scalars(
                select(TraffitWebhookEvent)
                .where(
                    TraffitWebhookEvent.status.in_(
                        ("pending", "retry", "shadowed", "dry_run")
                        if include_shadowed
                        else ("pending", "retry")
                    ),
                    or_(
                        TraffitWebhookEvent.next_attempt_at.is_(None),
                        TraffitWebhookEvent.next_attempt_at <= now,
                    ),
                    TraffitWebhookEvent.attempts < TraffitWebhookEvent.max_attempts,
                )
                .order_by(TraffitWebhookEvent.id.asc())
                .with_for_update(skip_locked=True)
                .limit(limit)
            )
        ).all()
    )
    for event in rows:
        event.status = "processing"
        event.attempts += 1
        event.locked_at = now
        event.locked_by = worker_id
    await db.flush()
    return rows


async def recover_stale_webhook_locks(
    db: AsyncSession,
    *,
    stale_after: timedelta = timedelta(minutes=5),
) -> int:
    cutoff = _utcnow() - stale_after
    rows = list(
        (
            await db.scalars(
                select(TraffitWebhookEvent).where(
                    TraffitWebhookEvent.status == "processing",
                    TraffitWebhookEvent.locked_at < cutoff,
                )
            )
        ).all()
    )
    for event in rows:
        if event.attempts >= event.max_attempts:
            event.status = "dead_letter"
            event.processed_at = _utcnow()
            event.next_attempt_at = None
        else:
            event.status = "retry"
            event.next_attempt_at = _utcnow()
        event.locked_at = None
        event.locked_by = None
        event.last_error = "stale worker lock recovered"
    await db.flush()
    return len(rows)


async def scrub_completed_webhook_payloads(
    db: AsyncSession,
    *,
    retention: timedelta = timedelta(days=7),
) -> int:
    """Redact old completed inbox bodies while retaining hashes/audit rows."""
    result = await db.execute(
        update(TraffitWebhookEvent)
        .where(
            TraffitWebhookEvent.status.in_(("succeeded", "ignored", "shadowed")),
            TraffitWebhookEvent.processed_at < _utcnow() - retention,
            TraffitWebhookEvent.payload != {},
        )
        .values(payload={})
    )
    await db.flush()
    return int(result.rowcount or 0)


def _event_employee_id(event: TraffitWebhookEvent) -> Optional[str]:
    if event.remote_entity_type in {"employee", "candidate"}:
        return event.remote_entity_id
    payload = event.payload or {}
    for key in ("employee_id", "candidate_id"):
        if payload.get(key) is not None:
            return str(payload[key])
    employee = payload.get("employee") or payload.get("candidate")
    if isinstance(employee, Mapping) and employee.get("id") is not None:
        return str(employee["id"])
    return None


async def process_webhook_event(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitWebhookEvent,
    *,
    apply_changes: bool,
) -> str:
    try:
        employee_id = _event_employee_id(event)
        event_name = event.event_type.lower()
        is_delete_signal = "deleted" in event_name or "removed" in event_name
        if is_delete_signal:
            if apply_changes:
                candidate_delete = any(
                    marker in event_name
                    for marker in (
                        "candidate_deleted",
                        "candidate_soft_deleted",
                        "employee_deleted",
                        "employee_soft_deleted",
                    )
                )
                candidate_link = None
                if employee_id is not None:
                    candidate_link = await db.scalar(
                        select(TraffitEntityLink).where(
                            TraffitEntityLink.entity_type == "candidate",
                            TraffitEntityLink.traffit_entity_id == employee_id,
                            TraffitEntityLink.status != "detached",
                        )
                    )
                # Assignment/activity/file removal must never tombstone the
                # candidate profile merely because the payload carries an
                # employee id.
                link = candidate_link if candidate_delete else None
                if candidate_delete and candidate_link is not None:
                    candidate_link.pending_delete_at = _utcnow()
                    candidate_link.source_deleted_at = _utcnow()
                    candidate_link.status = "manual_action_required"
                entity_type = (
                    "candidate"
                    if candidate_delete
                    else "file"
                    if "file" in event_name
                    else "assignment"
                    if "job" in event_name or "recruitment" in event_name
                    else "activity"
                )
                existing = await db.scalar(
                    select(TraffitSyncConflict).where(
                        TraffitSyncConflict.entity_link_id
                        == (link.id if link else None),
                        TraffitSyncConflict.entity_type == entity_type,
                        TraffitSyncConflict.traffit_entity_id == employee_id,
                        TraffitSyncConflict.conflict_type == "remote_delete_signal",
                        TraffitSyncConflict.status == "manual_action_required",
                    )
                )
                if existing is None:
                    db.add(
                        TraffitSyncConflict(
                            entity_link_id=link.id if link else None,
                            entity_type=entity_type,
                            nexus_entity_id=(
                                candidate_link.nexus_entity_id
                                if candidate_link
                                else None
                            ),
                            traffit_entity_id=employee_id,
                            candidate_id=(
                                candidate_link.candidate_id if candidate_link else None
                            ),
                            field_path="source_deleted_at",
                            conflict_type="remote_delete_signal",
                            nexus_value={"exists": True},
                            traffit_value={
                                "event_type": event.event_type,
                                "payload": event.payload,
                            },
                            status="manual_action_required",
                        )
                    )
                event.status = "succeeded"
            else:
                event.status = "shadowed"
        elif employee_id is None:
            event.status = "ignored"
        else:
            remote = await client.get_json(f"/employees/{employee_id}")
            if not isinstance(remote, Mapping):
                raise RuntimeError("targeted candidate fetch returned non-object")
            await apply_remote_candidate(db, remote, apply_changes=apply_changes)
            if "file" in event.event_type.lower():
                await sync_candidate_file_manifest(
                    db,
                    client,
                    employee_id=employee_id,
                    apply_changes=apply_changes,
                )
            event.status = "succeeded" if apply_changes else "shadowed"
        event.processed_at = _utcnow()
        event.next_attempt_at = None
        event.last_error = None
    except Exception as exc:  # noqa: BLE001 - one poison event must not stop batch
        event.last_error = str(exc)[:2000]
        if event.attempts >= event.max_attempts:
            event.status = "dead_letter"
            event.processed_at = _utcnow()
            event.next_attempt_at = None
        else:
            event.status = "retry"
            delay = min(2 ** max(event.attempts - 1, 0), 900) + random.uniform(0, 1)
            if isinstance(exc, TraffitAPIError) and exc.retry_after_s is not None:
                delay = exc.retry_after_s
            event.next_attempt_at = _utcnow() + timedelta(seconds=delay)
    finally:
        event.locked_at = None
        event.locked_by = None
    await db.flush()
    return event.status


async def run_inbox_batch(
    db: AsyncSession,
    client: TraffitClient,
    *,
    worker_id: str,
    apply_changes: bool,
    limit: int = 50,
) -> dict[str, int]:
    recovered = await recover_stale_webhook_locks(db)
    events = await claim_webhook_events(
        db,
        worker_id=worker_id,
        limit=limit,
        include_shadowed=apply_changes,
    )
    await db.commit()
    stats: dict[str, int] = {"claimed": len(events), "recovered": recovered}
    for event in events:
        status = await process_webhook_event(
            db, client, event, apply_changes=apply_changes
        )
        stats[status] = stats.get(status, 0) + 1
        await db.commit()
    return stats


async def _state_for_phase(db: AsyncSession, phase: str) -> TraffitSyncState:
    state = await db.get(TraffitSyncState, phase)
    if state is None:
        state = TraffitSyncState(
            phase=phase,
            consecutive_failures=0,
        )
        db.add(state)
        await db.flush()
    return state


async def run_poll_reconcile(
    db: AsyncSession,
    client: TraffitClient,
    *,
    mode: str = "delta",
    trigger: str = "scheduler",
    dry_run: bool = True,
    leader_id: Optional[str] = None,
    existing_run: Optional[TraffitSyncRun] = None,
    lease_lost: Optional[asyncio.Event] = None,
) -> TraffitSyncRun:
    """Restart-safe reconcile using per-stream cursors and existing importers.

    Candidate profiles use the conflict-aware applier above. Traffit-owned jobs
    and workflows plus append-only activities/stages reuse the battle-tested
    importer. A cursor advances only when its phase reports a complete success.
    """
    if mode not in {"delta", "active", "full"}:
        raise ValueError("mode must be delta, active or full")
    started = _utcnow()
    run = existing_run
    if run is None:
        run = TraffitSyncRun(
            mode=mode,
            trigger=trigger,
            scope={
                "active_only": mode == "active",
                "implemented_entities": (
                    ["candidate_profiles", "candidate_file_manifests"]
                    if mode == "active"
                    else ["tenant_streams"]
                ),
            },
            status="running",
            dry_run=dry_run,
            leader_id=leader_id,
            started_at=started,
            stats={},
            errors=[],
        )
        db.add(run)
    else:
        run.status = "running"
        run.dry_run = dry_run
        run.leader_id = leader_id
        run.started_at = started
        run.finished_at = None
        run.stats = {}
        run.errors = []
    await db.flush()
    run_id = run.id
    # The audit envelope must survive a rollback in an individual phase.
    await db.commit()
    importer = TraffitImporter(client, db, dry_run=dry_run, batch_size=100)
    control_row = None
    baseline_only = False
    if mode == "full":
        from app.services.traffit.control import get_control_row

        control_row = await get_control_row(db, create=True)
        baseline_only = not bool(
            (control_row.settings or {}).get("full_baseline_complete", False)
        )
    phase_names = (
        ["candidates", "candidate_files"]
        if mode == "active"
        else [
            "workflows",
            "candidates",
            "jobs",
            "pipelines",
            "candidate_activities",
            "candidate_files",
        ]
    )
    aggregate: dict[str, Any] = {}

    for phase_name in phase_names:
        if lease_lost is not None and lease_lost.is_set():
            raise RuntimeError("Traffit integration lease lost during reconcile")
        state = await _state_for_phase(
            db,
            f"integration:{'active:' if mode == 'active' else ''}{phase_name}",
        )
        effective_cursor_at, effective_cursor_external_id = _effective_reconcile_cursor(
            state, dry_run=dry_run
        )
        since = None
        if mode != "full" and effective_cursor_at is not None:
            since = effective_cursor_at - timedelta(hours=48)
        phase = TraffitSyncRunPhase(
            run_id=run.id,
            phase=phase_name,
            status="running",
            started_at=_utcnow(),
            cursor_before={
                "at": (
                    effective_cursor_at.isoformat() if effective_cursor_at else None
                ),
                "external_id": effective_cursor_external_id,
            },
            stats={},
        )
        db.add(phase)
        state.last_attempt_at = started
        state.last_status = "running"
        await db.flush()
        await db.commit()
        try:
            next_cursor_at = started
            next_cursor_external_id = effective_cursor_external_id
            if phase_name == "candidates":
                seen = applied = conflicts = 0
                seen_candidate_ids: set[str] = set()
                max_cursor: Optional[tuple[datetime, tuple[int, Any], str]] = None
                filter_ = TraffitImporter._delta_filter("updated_at", since)
                remote_stream = (
                    _iter_active_remote_candidates(db, client)
                    if mode == "active"
                    else client.get_paginated(
                        "/employees/", page_size=100, filter_=filter_
                    )
                )
                async for remote in remote_stream:
                    seen += 1
                    result = await apply_remote_candidate(
                        db, remote, apply_changes=not dry_run
                    )
                    applied += int(result["action"] == "applied")
                    conflicts += int(result.get("conflicts", 0))
                    if remote.get("id") is not None:
                        remote_id = str(remote["id"])
                        seen_candidate_ids.add(remote_id)
                        source_at = _parse_traffit_datetime(remote.get("updated_at"))
                        if source_at is not None:
                            id_key: tuple[int, Any] = (
                                (0, int(remote_id))
                                if remote_id.isdigit()
                                else (1, remote_id)
                            )
                            candidate_cursor = (source_at, id_key, remote_id)
                            if max_cursor is None or candidate_cursor > max_cursor:
                                max_cursor = candidate_cursor
                summary = {
                    "processed": seen,
                    "inserted": applied,
                    "updated": 0,
                    "skipped": 0,
                    "errors": [],
                    "conflicts": conflicts,
                }
                if max_cursor is not None:
                    next_cursor_at = max_cursor[0]
                    next_cursor_external_id = max_cursor[2]
                else:
                    # An empty, complete stream can safely advance to the run
                    # start; the next poll still applies the overlap window.
                    next_cursor_at = started
                    next_cursor_external_id = None
                if mode == "full" and not dry_run:
                    summary["absence"] = await reconcile_entity_absence(
                        db,
                        entity_type="candidate",
                        seen_remote_ids=seen_candidate_ids,
                        baseline_only=baseline_only,
                    )
            elif phase_name == "workflows":
                summary = (await importer.import_workflows()).as_dict()
            elif phase_name == "jobs":
                summary = (await importer.import_jobs(since)).as_dict()
                if mode == "full" and not dry_run and not (summary.get("errors") or []):
                    seen_job_ids = {
                        str(item["id"])
                        async for item in client.get_paginated(
                            "/recruitments/", page_size=100
                        )
                        if item.get("id") is not None
                    }
                    await _backfill_job_links(db, seen_job_ids)
                    summary["absence"] = await reconcile_entity_absence(
                        db,
                        entity_type="job",
                        seen_remote_ids=seen_job_ids,
                        baseline_only=baseline_only,
                    )
            elif phase_name == "pipelines":
                summary = (await importer.import_pipelines(since)).as_dict()
            elif phase_name == "candidate_activities":
                summary = (await importer.import_candidate_activities(since)).as_dict()
            else:
                summary = await run_active_file_manifest_shard(
                    db, client, apply_changes=not dry_run
                )

            if phase_name != "candidates":
                summary["cursor_semantics"] = "run_started_with_48h_overlap"

            raw_errors = summary.get("errors") or 0
            if isinstance(raw_errors, int):
                has_errors = raw_errors > 0
                error_details: list[Any] = list(summary.get("error_samples") or [])
            else:
                error_details = list(raw_errors)
                has_errors = bool(error_details)
            complete = not has_errors
            phase.status = "succeeded" if complete else "partial"
            phase.complete = complete
            phase.items_seen = int(summary.get("processed", 0) or 0)
            phase.items_applied = int(summary.get("inserted", 0) or 0) + int(
                summary.get("updated", 0) or 0
            )
            phase.items_skipped = int(summary.get("skipped", 0) or 0)
            phase.conflicts_created = int(summary.get("conflicts", 0) or 0)
            phase.stats = summary
            if complete:
                if dry_run:
                    state.cursor_payload = {
                        **(state.cursor_payload or {}),
                        "shadow_cursor_at": next_cursor_at.isoformat(),
                        "shadow_cursor_external_id": next_cursor_external_id,
                    }
                else:
                    state.cursor_at = next_cursor_at
                    state.cursor_external_id = next_cursor_external_id
                state.last_success_at = _utcnow()
                state.last_status = "ok"
                state.consecutive_failures = 0
                state.last_error = None
                state.next_due_at = started + timedelta(minutes=5)
                phase.cursor_after = {
                    "at": next_cursor_at.isoformat(),
                    "external_id": next_cursor_external_id,
                }
            else:
                state.last_status = "errors"
                state.consecutive_failures += 1
                state.last_error = str(error_details or raw_errors)[:2000]
                state.next_due_at = started + timedelta(minutes=5)
                run.errors = [
                    *(run.errors or []),
                    {
                        "phase": phase_name,
                        "errors": (error_details[:20] or [str(raw_errors)]),
                    },
                ]
            aggregate[phase_name] = summary
        except Exception as exc:  # noqa: BLE001 - phase isolation is intentional
            await db.rollback()
            # Re-load rows after rollback; never advance this phase cursor.
            run = await db.get(TraffitSyncRun, run_id)
            assert run is not None
            phase = await db.scalar(
                select(TraffitSyncRunPhase).where(
                    TraffitSyncRunPhase.run_id == run.id,
                    TraffitSyncRunPhase.phase == phase_name,
                )
            )
            state = await _state_for_phase(
                db,
                f"integration:{'active:' if mode == 'active' else ''}{phase_name}",
            )
            phase.status = "failed"
            phase.complete = False
            phase.error = str(exc)[:2000]
            state.last_status = "error"
            state.consecutive_failures += 1
            state.last_error = str(exc)[:2000]
            run.errors = [
                *(run.errors or []),
                {"phase": phase_name, "error": str(exc)[:1000]},
            ]
            aggregate[phase_name] = {"error": str(exc)[:1000]}
        finally:
            phase.finished_at = _utcnow()
            await db.commit()

    run = await db.get(TraffitSyncRun, run_id)
    assert run is not None
    run.stats = aggregate
    run.finished_at = _utcnow()
    run.status = "succeeded" if not run.errors else "partial"
    if mode == "full" and not dry_run and not run.errors and control_row is not None:
        control_row = await get_control_row(db, create=True)
        assert control_row is not None
        control_row.settings = {
            **(control_row.settings or {}),
            "full_baseline_complete": True,
            "full_baseline_completed_at": _utcnow().isoformat(),
        }
    await db.flush()
    return run
