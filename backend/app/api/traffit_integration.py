"""Public webhook and admin control-plane routers for Traffit integration.

Mount ``public_router`` at ``/api/integrations/traffit`` and ``admin_router``
at ``/api/admin/traffit``. Existing ``admin_traffit`` routes remain unchanged.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser
from app.core.config import settings
from app.core.database import get_db
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job
from app.models.pipeline_template import PipelineStageDef, RejectionReason
from app.models.recruitment_pipeline import (
    CandidateStage,
    PipelineStage,
    VerificationStatus,
)
from app.models.traffit_integration import (
    IntegrationLease,
    TraffitEntityLink,
    TraffitFieldContract,
    TraffitOutboxEvent,
    TraffitSyncConflict,
    TraffitSyncRun,
    TraffitWebhookEvent,
)
from app.models.traffit_sync_state import TraffitSyncState
from app.services.traffit.client import (
    TraffitClient,
    TraffitConfig,
    integration_scopes_from_env,
)
from app.services.traffit.control import (
    effective_control,
    get_control_row,
    integration_master_enabled,
)
from app.services.traffit.field_contracts import refresh_candidate_contracts
from app.services.traffit.outbox import enqueue_traffit_event
from app.services.traffit.webhook import (
    MAX_WEBHOOK_BODY_BYTES,
    InvalidWebhookSignature,
    assert_webhook_authorized,
    ingest_webhook,
)

public_router = APIRouter()
admin_router = APIRouter()

_ACTIONABLE_CONFLICT_STATUSES = ("open", "manual_action_required")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _conflict_status_values(value: Optional[str]) -> tuple[str, ...]:
    """Expand the admin-facing actionable filter to both review queues."""
    if value == "actionable":
        return _ACTIONABLE_CONFLICT_STATUSES
    if not value:
        return ()
    return (value,)


def _redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = dict(payload)
    if "content_base64" in redacted:
        redacted["content_base64"] = "[REDACTED]"
    return redacted


@public_router.post(
    "/webhooks/{subscription_id}/{secret}",
    status_code=status.HTTP_202_ACCEPTED,
)
async def receive_traffit_webhook(
    subscription_id: str,
    secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not integration_master_enabled():
        raise HTTPException(status_code=503, detail="Traffit integration disabled")
    control = await effective_control(db)
    if not control.webhook_accept_enabled:
        raise HTTPException(status_code=503, detail="Traffit webhook receiver paused")
    raw_body = await request.body()
    if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
        raise HTTPException(status_code=413, detail="Webhook payload too large")

    per_subscription = (control.settings or {}).get("webhook_secret_hashes", {})
    expected_hash = (
        per_subscription.get(subscription_id)
        if isinstance(per_subscription, dict)
        else None
    )
    configured_secret_hash = getattr(
        settings, "TRAFFIT_INTEGRATION_WEBHOOK_SECRET_HASH", ""
    ) or os.environ.get("TRAFFIT_INTEGRATION_WEBHOOK_SECRET_HASH", "")
    if not expected_hash and configured_secret_hash:
        expected_hash = configured_secret_hash
    hmac_secret = settings.TRAFFIT_INTEGRATION_WEBHOOK_HMAC_SECRET or None
    signature = request.headers.get("X-Traffit-Signature") or request.headers.get(
        "X-Signature"
    )
    try:
        assert_webhook_authorized(
            url_secret=secret,
            expected_secret_hash=expected_hash or "",
            raw_body=raw_body,
            signature=signature,
            hmac_secret=hmac_secret,
        )
    except InvalidWebhookSignature as exc:
        raise HTTPException(
            status_code=401, detail="Invalid webhook signature"
        ) from exc
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail="Webhook body must be JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Webhook body must be an object")
    event, created = await ingest_webhook(
        db,
        subscription_id=subscription_id,
        payload=payload,
        request_id=(
            request.headers.get("X-Webhook-Id") or request.headers.get("X-Request-Id")
        ),
        event_type=request.headers.get("X-Traffit-Event"),
        max_attempts=settings.TRAFFIT_INTEGRATION_MAX_ATTEMPTS,
    )
    return {"accepted": True, "duplicate": not created, "event_id": event.id}


class ControlUpdate(BaseModel):
    webhook_accept_enabled: Optional[bool] = None
    inbound_apply_enabled: Optional[bool] = None
    poll_enabled: Optional[bool] = None
    outbound_enabled: Optional[bool] = None
    dry_run: Optional[bool] = None
    paused_reason: Optional[str] = Field(default=None, max_length=2000)
    inbound_paused: Optional[bool] = None
    outbound_paused: Optional[bool] = None
    poll_paused: Optional[bool] = None
    reason: Optional[str] = Field(default=None, max_length=2000)
    settings_patch: dict[str, Any] = Field(default_factory=dict)


class ReconcileRequest(BaseModel):
    scope: Literal["active", "full"] = "active"
    entities: list[str] = Field(default_factory=list, max_length=100)


class RejectionReasonMappingUpdate(BaseModel):
    external_id: str = Field(min_length=1, max_length=100)


class ConflictResolution(BaseModel):
    resolution: Literal[
        "nexus",
        "traffit",
        "merged",
        "manual",
        "detach",
        "unlink",
        "ignored",
    ]
    resolved_value: Any = None
    merged_value: Any = None
    note: Optional[str] = Field(default=None, max_length=4000)


@admin_router.get("/integration/status")
async def integration_status(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    control = await effective_control(db)
    outbox_counts = dict(
        (
            await db.execute(
                select(TraffitOutboxEvent.status, func.count()).group_by(
                    TraffitOutboxEvent.status
                )
            )
        ).all()
    )
    inbox_counts = dict(
        (
            await db.execute(
                select(TraffitWebhookEvent.status, func.count()).group_by(
                    TraffitWebhookEvent.status
                )
            )
        ).all()
    )
    conflict_counts = dict(
        (
            await db.execute(
                select(TraffitSyncConflict.status, func.count()).group_by(
                    TraffitSyncConflict.status
                )
            )
        ).all()
    )
    oldest_outbox = await db.scalar(
        select(func.min(TraffitOutboxEvent.created_at)).where(
            TraffitOutboxEvent.status.in_(("pending", "retry", "processing"))
        )
    )
    oldest_inbox = await db.scalar(
        select(func.min(TraffitWebhookEvent.created_at)).where(
            TraffitWebhookEvent.status.in_(("pending", "retry", "processing"))
        )
    )
    leader = await db.get(IntegrationLease, "traffit-integration-worker")
    states = list(
        (
            await db.scalars(
                select(TraffitSyncState)
                .where(TraffitSyncState.phase.like("integration:%"))
                .order_by(TraffitSyncState.phase)
            )
        ).all()
    )
    last_run = await db.scalar(
        select(TraffitSyncRun).order_by(TraffitSyncRun.id.desc()).limit(1)
    )
    contracts = dict(
        (
            await db.execute(
                select(TraffitFieldContract.status, func.count()).group_by(
                    TraffitFieldContract.status
                )
            )
        ).all()
    )
    mapped_rejection_reasons = int(
        await db.scalar(
            select(func.count())
            .select_from(RejectionReason)
            .where(
                RejectionReason.external_source == "traffit",
                RejectionReason.external_id.is_not(None),
            )
        )
        or 0
    )
    unmapped_rejection_reasons = int(
        await db.scalar(
            select(func.count())
            .select_from(RejectionReason)
            .where(
                RejectionReason.active.is_(True),
                or_(
                    RejectionReason.external_source != "traffit",
                    RejectionReason.external_source.is_(None),
                    RejectionReason.external_id.is_(None),
                ),
            )
        )
        or 0
    )
    now = _utcnow()
    return {
        "enabled": control.master_enabled,
        "dry_run": control.dry_run,
        "inbound_apply_enabled": control.inbound_apply_enabled,
        "outbound_enabled": control.outbound_enabled,
        "webhook_accept_enabled": control.webhook_accept_enabled,
        "poll_enabled": control.poll_enabled,
        "paused": {
            "inbound": not control.inbound_apply_enabled,
            "outbound": not control.outbound_enabled,
            "poll": not control.poll_enabled,
        },
        "conflicts_open": sum(
            int(conflict_counts.get(key, 0))
            for key in ("open", "manual_action_required")
        ),
        "last_reconcile_at": (
            last_run.finished_at if last_run and last_run.finished_at else None
        ),
        "streams": [
            {
                "phase": row.phase,
                "last_success_at": row.last_success_at,
                "last_status": row.last_status,
                "lag_seconds": (
                    max(0, int((now - row.last_success_at).total_seconds()))
                    if row.last_success_at
                    else None
                ),
                "consecutive_failures": row.consecutive_failures,
            }
            for row in states
        ],
        "effective": {
            "webhook_accept": control.webhook_accept_enabled,
            "inbound_apply": control.inbound_apply_enabled,
            "poll": control.poll_enabled,
            "outbound": control.outbound_enabled,
            "dry_run": control.dry_run,
            "paused_reason": control.paused_reason,
        },
        "queues": {
            "inbox_pending": sum(
                int(inbox_counts.get(key, 0))
                for key in ("pending", "retry", "processing")
            ),
            "outbox_pending": sum(
                int(outbox_counts.get(key, 0))
                for key in ("pending", "retry", "processing")
            ),
            "dead_letter": int(inbox_counts.get("dead_letter", 0))
            + int(outbox_counts.get("dead_letter", 0)),
            "oldest_inbox_at": oldest_inbox,
            "oldest_outbox_at": oldest_outbox,
            "outbox": outbox_counts,
            "inbox": inbox_counts,
            "conflicts": conflict_counts,
            "outbox_oldest_age_seconds": (
                max(0, int((now - oldest_outbox).total_seconds()))
                if oldest_outbox
                else None
            ),
            "inbox_oldest_age_seconds": (
                max(0, int((now - oldest_inbox).total_seconds()))
                if oldest_inbox
                else None
            ),
        },
        "leader": (
            {
                "owner_id": leader.holder_id,
                "holder_id": leader.holder_id,
                "generation": leader.generation,
                "heartbeat_at": leader.heartbeat_at,
                "expires_at": leader.expires_at,
                "active": leader.expires_at > now,
            }
            if leader
            else None
        ),
        "cursors": [
            {
                "phase": row.phase,
                "cursor_at": row.cursor_at,
                "cursor_external_id": row.cursor_external_id,
                "cursor_payload": row.cursor_payload,
                "last_success_at": row.last_success_at,
                "last_status": row.last_status,
                "consecutive_failures": row.consecutive_failures,
                "last_error": row.last_error,
                "next_due_at": row.next_due_at,
            }
            for row in states
        ],
        "last_run": (
            {
                "id": last_run.id,
                "run_uuid": last_run.run_uuid,
                "mode": last_run.mode,
                "status": last_run.status,
                "dry_run": last_run.dry_run,
                "started_at": last_run.started_at,
                "finished_at": last_run.finished_at,
                "stats": last_run.stats,
                "errors": last_run.errors,
            }
            if last_run
            else None
        ),
        "field_contracts": contracts,
        "rejection_reason_mapping": {
            "mapped": mapped_rejection_reasons,
            "unmapped": unmapped_rejection_reasons,
            "ready": unmapped_rejection_reasons == 0,
        },
        "file_slo": next(
            (
                row.cursor_payload
                for row in states
                if row.phase == "integration:file_manifest_shard"
            ),
            {
                "file_slo_ready": False,
                "file_slo_blocked_reason": "no complete file-manifest sweep",
            },
        ),
    }


@admin_router.get("/integration/events")
async def list_integration_events(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    kind: Optional[Literal["outbox", "webhook"]] = None,
    direction: Optional[Literal["outbound", "inbound"]] = None,
    event_status: Optional[str] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    if direction:
        kind = "outbox" if direction == "outbound" else "webhook"

    async def outbound_items(fetch_limit: int) -> tuple[list[dict[str, Any]], int]:
        query = select(TraffitOutboxEvent).order_by(TraffitOutboxEvent.id.desc())
        count_query = select(func.count()).select_from(TraffitOutboxEvent)
        if event_status:
            query = query.where(TraffitOutboxEvent.status == event_status)
            count_query = count_query.where(TraffitOutboxEvent.status == event_status)
        rows = list((await db.scalars(query.limit(fetch_limit))).all())
        total = int(await db.scalar(count_query) or 0)
        return [
            {
                "id": f"outbound:{row.id}",
                "direction": "outbound",
                "kind": "outbox",
                "event_uuid": row.event_uuid,
                "event_type": row.event_type,
                "aggregate_type": row.aggregate_type,
                "aggregate_id": row.aggregate_id,
                "candidate_id": row.candidate_id,
                "status": row.status,
                "attempts": row.attempts,
                "max_attempts": row.max_attempts,
                "next_attempt_at": row.next_attempt_at,
                "processed_at": row.processed_at,
                "created_at": row.created_at,
                "changed_fields": row.changed_fields,
                "payload": _redact_payload(row.payload or {}),
                "last_error": row.last_error,
            }
            for row in rows
        ], total

    async def inbound_items(fetch_limit: int) -> tuple[list[dict[str, Any]], int]:
        query = select(TraffitWebhookEvent).order_by(TraffitWebhookEvent.id.desc())
        count_query = select(func.count()).select_from(TraffitWebhookEvent)
        if event_status:
            query = query.where(TraffitWebhookEvent.status == event_status)
            count_query = count_query.where(TraffitWebhookEvent.status == event_status)
        rows = list((await db.scalars(query.limit(fetch_limit))).all())
        total = int(await db.scalar(count_query) or 0)
        return [
            {
                "id": f"inbound:{row.id}",
                "direction": "inbound",
                "kind": "webhook",
                "event_type": row.event_type,
                "aggregate_type": row.remote_entity_type or "unknown",
                "aggregate_id": row.remote_entity_id or "",
                "remote_entity_type": row.remote_entity_type,
                "remote_entity_id": row.remote_entity_id,
                "status": row.status,
                "attempts": row.attempts,
                "max_attempts": row.max_attempts,
                "next_attempt_at": row.next_attempt_at,
                "processed_at": row.processed_at,
                "created_at": row.created_at,
                "payload": _redact_payload(row.payload or {}),
                "last_error": row.last_error,
            }
            for row in rows
        ], total

    fetch_limit = offset + limit
    if kind == "outbox":
        items, total = await outbound_items(fetch_limit)
    elif kind == "webhook":
        items, total = await inbound_items(fetch_limit)
    else:
        outbound, outbound_total = await outbound_items(fetch_limit)
        inbound, inbound_total = await inbound_items(fetch_limit)
        items = sorted(
            [*outbound, *inbound],
            key=lambda item: item.get("created_at")
            or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )
        total = outbound_total + inbound_total
    return {"items": items[offset : offset + limit], "total": total}


@admin_router.post("/integration/events/{event_id}/retry")
async def retry_integration_event(
    event_id: str,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    kind: Literal["outbox", "webhook"] = "outbox",
) -> dict[str, Any]:
    if ":" in event_id:
        prefix, raw_id = event_id.split(":", 1)
        kind = "webhook" if prefix == "inbound" else "outbox"
    else:
        raw_id = event_id
    try:
        parsed_id = int(raw_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail="Invalid integration event id"
        ) from exc
    model = TraffitOutboxEvent if kind == "outbox" else TraffitWebhookEvent
    event = await db.get(model, parsed_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Integration event not found")
    if event.status not in {
        "dead_letter",
        "retry",
        "manual_action_required",
        "dry_run",
        "shadowed",
    }:
        raise HTTPException(status_code=409, detail="Event is not retryable")
    event.status = "retry"
    event.next_attempt_at = _utcnow()
    event.processed_at = None
    event.locked_at = None
    event.locked_by = None
    event.last_error = None
    direction_value = "outbound" if kind == "outbox" else "inbound"
    return {
        "id": f"{direction_value}:{event.id}",
        "direction": direction_value,
        "kind": kind,
        "status": event.status,
    }


@admin_router.get("/integration/conflicts")
async def list_conflicts(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    conflict_status: Optional[str] = Query("actionable", alias="status"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    conflict_statuses = _conflict_status_values(conflict_status)
    query = select(TraffitSyncConflict).order_by(
        TraffitSyncConflict.detected_at.desc(), TraffitSyncConflict.id.desc()
    )
    if conflict_statuses:
        query = query.where(TraffitSyncConflict.status.in_(conflict_statuses))
    count_query = select(func.count()).select_from(TraffitSyncConflict)
    if conflict_statuses:
        count_query = count_query.where(
            TraffitSyncConflict.status.in_(conflict_statuses)
        )
    rows = list((await db.scalars(query.offset(offset).limit(limit))).all())
    items = [
        {
            "id": row.id,
            "entity_type": row.entity_type,
            "nexus_entity_id": row.nexus_entity_id,
            "traffit_entity_id": row.traffit_entity_id,
            "external_id": row.traffit_entity_id,
            "candidate_id": row.candidate_id,
            "field_path": row.field_path,
            "conflict_type": row.conflict_type,
            "base_value": row.base_value,
            "nexus_value": row.nexus_value,
            "traffit_value": row.traffit_value,
            "local_value": row.nexus_value,
            "remote_value": row.traffit_value,
            "status": row.status,
            "resolution": row.resolution,
            "resolved_value": row.resolved_value,
            "resolution_note": row.resolution_note,
            "detected_at": row.detected_at,
            "created_at": row.detected_at,
            "resolved_at": row.resolved_at,
            "resolved_by": row.resolved_by,
        }
        for row in rows
    ]
    return {"items": items, "total": int(await db.scalar(count_query) or 0)}


def _set_candidate_field(candidate: Candidate, path: str, value: Any) -> None:
    if path.startswith("custom_fields."):
        custom = dict(candidate.custom_fields or {})
        custom[path.split(".", 1)[1]] = value
        candidate.custom_fields = custom
        return
    if path == "status" and value is not None:
        value = CandidateStatus(value)
    if not hasattr(candidate, path):
        raise ValueError(f"Candidate field is not locally writable: {path}")
    setattr(candidate, path, value)


def _set_snapshot_field(snapshot: dict[str, Any], path: str, value: Any) -> None:
    if "." not in path:
        snapshot[path] = value
        return
    first, rest = path.split(".", 1)
    nested = dict(snapshot.get(first) or {})
    nested[rest] = value
    snapshot[first] = nested


def _remove_snapshot_field(snapshot: dict[str, Any], path: str) -> None:
    if "." not in path:
        snapshot.pop(path, None)
        return
    first, rest = path.split(".", 1)
    nested = dict(snapshot.get(first) or {})
    nested.pop(rest, None)
    if nested:
        snapshot[first] = nested
    else:
        snapshot.pop(first, None)


async def _apply_remote_stage_resolution(
    db: AsyncSession,
    event: TraffitOutboxEvent,
    remote_state_id: Any,
) -> None:
    stage_id = event.payload.get("candidate_stage_id") or event.aggregate_id
    stage = await db.get(CandidateStage, stage_id)
    if stage is None:
        raise HTTPException(status_code=409, detail="Candidate stage no longer exists")
    job = await db.get(Job, stage.job_id)
    query = select(PipelineStageDef).where(
        PipelineStageDef.external_source == "traffit",
        PipelineStageDef.external_id == str(remote_state_id),
    )
    if job is not None and job.pipeline_template_id is not None:
        query = query.where(PipelineStageDef.template_id == job.pipeline_template_id)
    target = await db.scalar(query.limit(1))
    if target is None:
        raise HTTPException(
            status_code=409,
            detail="Traffit stage has no local workflow mapping",
        )
    stage.stage_def_id = target.id
    if target.legacy_enum_value:
        try:
            stage.stage = PipelineStage(target.legacy_enum_value)
        except ValueError as exc:
            raise HTTPException(
                status_code=409,
                detail="Mapped Traffit stage has an invalid legacy stage value",
            ) from exc
    stage.verification_status = VerificationStatus.active
    audit = f"[Traffit sync] Admin accepted remote stage {target.name}."
    stage.notes = f"{stage.notes}\n{audit}" if stage.notes else audit


@admin_router.post("/integration/conflicts/{conflict_id}/resolve")
async def resolve_conflict(
    conflict_id: int,
    body: ConflictResolution,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    conflict = await db.get(TraffitSyncConflict, conflict_id)
    if conflict is None:
        raise HTTPException(status_code=404, detail="Conflict not found")
    if conflict.status not in {"open", "manual_action_required"}:
        raise HTTPException(status_code=409, detail="Conflict is already resolved")
    resolution = "detach" if body.resolution == "unlink" else body.resolution
    merged_value = (
        body.merged_value
        if "merged_value" in body.model_fields_set
        else body.resolved_value
    )
    selected = {
        "nexus": conflict.nexus_value,
        "traffit": conflict.traffit_value,
        "merged": merged_value,
    }.get(resolution, body.resolved_value)
    if resolution == "merged" and merged_value is None:
        raise HTTPException(status_code=422, detail="Merged resolution needs a value")
    link = (
        await db.get(TraffitEntityLink, conflict.entity_link_id)
        if conflict.entity_link_id
        else None
    )
    event = (
        await db.get(TraffitOutboxEvent, conflict.outbox_event_id)
        if conflict.outbox_event_id
        else None
    )

    if resolution == "detach":
        if link is not None:
            link.status = "detached"
    elif resolution in {"traffit", "merged"} and conflict.entity_type == "candidate":
        candidate_id = conflict.candidate_id or conflict.nexus_entity_id
        candidate = await db.get(Candidate, candidate_id) if candidate_id else None
        if candidate is None or not conflict.field_path:
            raise HTTPException(
                status_code=409, detail="Candidate conflict cannot be applied"
            )
        try:
            _set_candidate_field(candidate, conflict.field_path, selected)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    if (
        event is not None
        and conflict.conflict_type == "stage_divergence"
        and resolution in {"traffit", "merged"}
    ):
        await _apply_remote_stage_resolution(db, event, selected)

    should_retry = False
    if event is not None:
        payload = dict(event.payload or {})
        if conflict.conflict_type == "stage_divergence":
            if resolution in {"nexus", "merged"}:
                payload["expected_state_id"] = conflict.traffit_value
                if resolution == "merged" and selected is not None:
                    payload["state_id"] = selected
                should_retry = True
        elif conflict.entity_type == "candidate" and conflict.field_path:
            fields = dict(payload.get("fields") or {})
            base = dict(payload.get("base_snapshot") or {})
            if resolution in {"nexus", "merged"}:
                # Resolution changes the actual retry patch, not just the
                # comparison baseline. This is especially important for a
                # custom merged value.
                _set_snapshot_field(fields, conflict.field_path, selected)
                should_retry = True
            else:
                _remove_snapshot_field(fields, conflict.field_path)
            _set_snapshot_field(base, conflict.field_path, conflict.traffit_value)
            payload["fields"] = fields
            payload["base_snapshot"] = base
        event.payload = payload
    elif resolution in {"nexus", "merged"} and conflict.entity_type == "candidate":
        if not conflict.field_path or conflict.nexus_entity_id is None:
            raise HTTPException(
                status_code=409, detail="Conflict lacks candidate field context"
            )
        fields: dict[str, Any] = {}
        _set_snapshot_field(fields, conflict.field_path, selected)
        queued = await enqueue_traffit_event(
            db,
            "candidate.update",
            "candidate",
            conflict.nexus_entity_id,
            {
                "fields": fields,
                "base_snapshot": link.base_snapshot if link else {},
            },
            actor_id=admin.id,
            candidate_id=conflict.candidate_id or conflict.nexus_entity_id,
            entity_link_id=link.id if link else None,
            operation_id=f"conflict-{conflict.id}",
            changed_fields=(conflict.field_path,),
            priority=10,
        )
        if queued is None:
            raise HTTPException(
                status_code=409, detail="Outbound integration is not armed"
            )
        should_retry = True

    # A Traffit choice is already equal on both systems after the local apply,
    # so that one field can safely advance. Nexus/merged choices remain on the
    # old baseline until outbound confirms success.
    if link is not None and conflict.field_path and resolution == "traffit":
        baseline = dict(link.base_snapshot or {})
        _set_snapshot_field(baseline, conflict.field_path, selected)
        link.base_snapshot = baseline
    conflict.status = "ignored" if resolution == "ignored" else "resolved"
    conflict.resolution = resolution
    conflict.resolved_value = selected
    conflict.resolution_note = body.note
    conflict.resolved_at = _utcnow()
    conflict.resolved_by = admin.id
    await db.flush()

    remaining = 0
    if event is not None:
        remaining = int(
            await db.scalar(
                select(func.count())
                .select_from(TraffitSyncConflict)
                .where(
                    TraffitSyncConflict.outbox_event_id == event.id,
                    TraffitSyncConflict.status.in_(("open", "manual_action_required")),
                )
            )
            or 0
        )
        if remaining:
            event.status = "conflict"
            event.next_attempt_at = None
            event.processed_at = _utcnow()
        elif resolution == "detach":
            event.status = "cancelled"
            event.next_attempt_at = None
            event.processed_at = _utcnow()
        else:
            fields = (event.payload or {}).get("fields")
            if conflict.entity_type == "candidate" and isinstance(fields, dict):
                should_retry = should_retry and bool(fields)
            if should_retry:
                event.status = "retry"
                event.next_attempt_at = _utcnow()
                event.processed_at = None
                event.last_error = None
            else:
                event.status = "cancelled"
                event.next_attempt_at = None
                event.processed_at = _utcnow()

    if link is not None and resolution != "detach":
        if remaining:
            link.status = "conflict"
        elif should_retry:
            link.status = "pending"
        elif resolution == "manual":
            link.status = "manual_action_required"
        else:
            link.status = "synced"
        link.last_error = None
    return {
        "id": conflict.id,
        "status": conflict.status,
        "resolution": body.resolution,
        "remaining_conflicts": remaining,
    }


@admin_router.post("/integration/reconcile", status_code=status.HTTP_202_ACCEPTED)
async def enqueue_reconcile(
    _admin: AdminUser,
    body: ReconcileRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not integration_master_enabled():
        raise HTTPException(status_code=503, detail="Traffit integration disabled")
    mode = body.scope
    existing = await db.scalar(
        select(TraffitSyncRun).where(TraffitSyncRun.status.in_(("queued", "running")))
    )
    if existing is not None:
        raise HTTPException(
            status_code=409, detail="A reconcile is already queued/running"
        )
    control = await effective_control(db)
    run = TraffitSyncRun(
        mode=mode,
        trigger="admin",
        scope={
            "active_only": mode == "active",
            "entities": body.entities,
            "scope_contract": (
                "candidate_profiles_and_file_manifests_for_published_traffit_jobs"
                if mode == "active"
                else "full_tenant"
            ),
        },
        status="queued",
        dry_run=control.dry_run,
        stats={},
        errors=[],
    )
    db.add(run)
    await db.flush()
    return {
        "status": "started",
        "run_id": run.run_uuid,
        "database_run_id": run.id,
        "mode": mode,
    }


@admin_router.post("/integration/control")
async def update_integration_control(
    body: ControlUpdate,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await get_control_row(db, create=True)
    assert row is not None
    for field in (
        "webhook_accept_enabled",
        "inbound_apply_enabled",
        "poll_enabled",
        "outbound_enabled",
        "dry_run",
    ):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    if body.inbound_paused is not None:
        row.inbound_apply_enabled = not body.inbound_paused
    if body.outbound_paused is not None:
        row.outbound_enabled = not body.outbound_paused
    if body.poll_paused is not None:
        row.poll_enabled = not body.poll_paused
    if "paused_reason" in body.model_fields_set:
        row.paused_reason = body.paused_reason
    if "reason" in body.model_fields_set:
        row.paused_reason = body.reason
    if body.settings_patch:
        # Secrets are configured via env or pre-hashed values, never accepted
        # as plaintext through this endpoint.
        forbidden = {key for key in body.settings_patch if "secret" in key.lower()}
        if forbidden:
            raise HTTPException(status_code=422, detail="Secrets cannot be set via API")
        row.settings = {**(row.settings or {}), **body.settings_patch}
    row.updated_by = admin.id
    await db.flush()
    return await integration_status(admin, db)


@admin_router.post("/integration/contracts/refresh")
async def refresh_contracts(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
    sample_employee_id: Optional[str] = None,
) -> dict[str, Any]:
    if not integration_master_enabled():
        raise HTTPException(status_code=503, detail="Traffit integration disabled")
    async with TraffitClient(
        TraffitConfig.from_env(), scope=integration_scopes_from_env()
    ) as client:
        return await refresh_candidate_contracts(
            db, client, sample_employee_id=sample_employee_id
        )


@admin_router.get("/integration/rejection-reasons")
async def list_rejection_reason_mappings(
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    rows = list(
        (
            await db.scalars(
                select(RejectionReason).order_by(
                    RejectionReason.template_id,
                    RejectionReason.order,
                    RejectionReason.id,
                )
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "template_id": row.template_id,
                "name": row.name,
                "category": row.category.value,
                "active": row.active,
                "external_source": row.external_source,
                "external_id": row.external_id,
                "mapped": row.external_source == "traffit" and bool(row.external_id),
            }
            for row in rows
        ],
        "total": len(rows),
    }


@admin_router.get("/integration/rejection-reasons/discover")
async def discover_rejection_reasons(
    _admin: AdminUser,
    recruitment_id: str = Query(..., min_length=1, max_length=100),
) -> dict[str, Any]:
    if not integration_master_enabled():
        raise HTTPException(status_code=503, detail="Traffit integration disabled")
    async with TraffitClient(
        TraffitConfig.from_env(), scope=integration_scopes_from_env()
    ) as client:
        response = await client.get_json(f"/recruitments/{recruitment_id}/rejections")
    if isinstance(response, list):
        items = response
    elif isinstance(response, dict):
        raw_items = response.get("items") or response.get("data") or []
        items = raw_items if isinstance(raw_items, list) else []
    else:
        items = []
    return {
        "recruitment_id": recruitment_id,
        "items": [item for item in items if isinstance(item, dict)],
    }


@admin_router.post("/integration/rejection-reasons/{reason_id}/mapping")
async def map_rejection_reason(
    reason_id: int,
    body: RejectionReasonMappingUpdate,
    _admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    reason = await db.get(RejectionReason, reason_id)
    if reason is None:
        raise HTTPException(status_code=404, detail="Rejection reason not found")
    duplicate = await db.scalar(
        select(RejectionReason).where(
            RejectionReason.id != reason.id,
            RejectionReason.external_source == "traffit",
            RejectionReason.external_id == body.external_id,
        )
    )
    if duplicate is not None:
        raise HTTPException(
            status_code=409,
            detail="Traffit rejection reason is already mapped",
        )
    reason.external_source = "traffit"
    reason.external_id = body.external_id
    await db.flush()
    return {
        "id": reason.id,
        "name": reason.name,
        "external_source": reason.external_source,
        "external_id": reason.external_id,
        "mapped": True,
    }
