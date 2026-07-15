"""Durable outbound dispatcher for Nexus → Traffit core recruitment events."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import httpx
from sqlalchemy import and_, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased, undefer

from app.models.candidate import Candidate, CandidateStatus
from app.models.candidate_document import CandidateDocument
from app.models.pipeline_template import RejectionReason
from app.models.traffit_integration import (
    TraffitEntityLink,
    TraffitFieldContract,
    TraffitOutboxEvent,
    TraffitSyncConflict,
)
from app.services import object_storage
from app.services.traffit.client import TraffitAPIError, TraffitClient
from app.services.traffit.field_contracts import (
    LOCAL_TO_TRAFFIT,
    TRAFFIT_TO_LOCAL,
    candidate_to_traffit,
    contract_from_row,
    refresh_candidate_contracts,
)
from app.services.traffit.mappers import traffit_employee_to_candidate
from app.services.traffit.merge import snapshot_hash, three_way_merge
from app.services.traffit.outbox import OutboxCommand, _enqueue_command

logger = logging.getLogger(__name__)

MANUAL_EVENT_TYPES = frozenset(
    {
        "candidate.delete_requested",
        "note.delete_requested",
        "file.delete_requested",
        "assignment.remove_requested",
    }
)
TERMINAL_ORDER_STATUSES = frozenset(
    {
        "succeeded",
        "dry_run",
        "shadowed",
        "cancelled",
        "conflict",
        "manual_action_required",
        "dead_letter",
    }
)


@dataclass(frozen=True)
class DispatchResult:
    status: str
    remote_response: Optional[dict[str, Any]] = None
    message: Optional[str] = None


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _fields(payload: Mapping[str, Any]) -> dict[str, Any]:
    candidate = payload.get("traffit_payload") or payload.get("fields")
    if isinstance(candidate, Mapping):
        return dict(candidate)
    internal = {
        "employee_id",
        "traffit_candidate_id",
        "base_snapshot",
        "nexus_snapshot",
        "audit_note",
        "actor_name",
        "guid_lookup_enabled",
    }
    return {key: value for key, value in payload.items() if key not in internal}


def _local_candidate_patch(fields: Mapping[str, Any]) -> dict[str, Any]:
    """Accept endpoint-friendly local keys and already-adapted remote keys."""
    local: dict[str, Any] = {}
    custom: dict[str, Any] = {}
    for key, value in fields.items():
        if key == "custom_fields" and isinstance(value, Mapping):
            custom.update(value)
        elif key.startswith("_"):
            custom[key] = value
        else:
            local[TRAFFIT_TO_LOCAL.get(key, key)] = value
    if custom:
        local["custom_fields"] = custom
    return local


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    cursor = target
    parts = path.split(".")
    for part in parts[:-1]:
        nested = cursor.get(part)
        if not isinstance(nested, dict):
            nested = {}
            cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value


def _drop_quarantined_fields(
    local: Mapping[str, Any], quarantined: list[str]
) -> dict[str, Any]:
    result = dict(local)
    custom = dict(result.get("custom_fields") or {})
    for raw_name in quarantined:
        if raw_name.startswith("missing_required:"):
            continue
        local_name = TRAFFIT_TO_LOCAL.get(raw_name, raw_name)
        if raw_name.startswith("_") or local_name.startswith("custom_fields."):
            custom.pop(local_name.split(".", 1)[-1], None)
            custom.pop(raw_name, None)
        else:
            result.pop(local_name, None)
    if custom:
        result["custom_fields"] = custom
    else:
        result.pop("custom_fields", None)
    return result


async def _record_quarantined_fields(
    db: AsyncSession,
    event: TraffitOutboxEvent,
    quarantined: list[str],
) -> None:
    for field in quarantined:
        await _record_conflict(
            db,
            event,
            conflict_type=(
                "missing_required_field"
                if field.startswith("missing_required:")
                else "schema_field_quarantined"
            ),
            field_path=field.split(":", 1)[-1],
            nexus_value={"field": field},
            traffit_value={"capability": "quarantined"},
            status="manual_action_required",
        )


def _remote_candidate_patch(fields: Mapping[str, Any]) -> dict[str, Any]:
    remote: dict[str, Any] = {}
    custom = fields.get("custom_fields")
    for key, value in fields.items():
        if key == "custom_fields":
            continue
        remote[LOCAL_TO_TRAFFIT.get(key, key)] = value
    if isinstance(custom, Mapping):
        remote.update({str(key): value for key, value in custom.items()})
    return remote


async def _adapt_candidate_payload(
    db: AsyncSession,
    event: TraffitOutboxEvent,
    capability: str,
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    raw = _fields(event.payload)
    local = _local_candidate_patch(raw)
    rows = list(
        (
            await db.scalars(
                select(TraffitFieldContract).where(
                    TraffitFieldContract.capability == capability,
                    TraffitFieldContract.status.in_(("active", "quarantined")),
                )
            )
        ).all()
    )
    if not rows:
        # Bootstrap fallback is deliberately narrow. Tenant-only fields become
        # writable after metadata discovery persists an explicit contract.
        allowed_local = set(LOCAL_TO_TRAFFIT)
        local = {
            key: value
            for key, value in local.items()
            if key in allowed_local or key == "custom_fields" or key == "guid"
        }
        return local, _remote_candidate_patch(local), []

    contracts = [contract_from_row(row) for row in rows]
    changed = set(local) | set(raw) | set(event.changed_fields or ())
    remote, quarantined = candidate_to_traffit(local, contracts, changed_fields=changed)
    # Metadata may expose a field with no Nexus projection. It remains usable
    # only when the endpoint supplied that exact remote field explicitly.
    row_by_name = {row.field_name: row for row in rows}
    for key, value in raw.items():
        row = row_by_name.get(key)
        if row is None:
            continue
        if row.status == "quarantined" or not row.writable:
            quarantined.append(key)
        elif row.local_path is None:
            remote[key] = value
    if capability == "create":
        for row in rows:
            if row.required and row.writable and row.field_name not in remote:
                quarantined.append(f"missing_required:{row.field_name}")
    return local, remote, sorted(set(quarantined))


def _remote_to_local_snapshot(
    remote: Mapping[str, Any],
    *,
    base: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Project a Traffit employee without treating unmapped fields as clears.

    ``base_snapshot`` can contain tenant fields which the legacy employee
    mapper does not project (for example ``source`` or ``availability_date``).
    Those values are still part of the shared three-way-merge baseline.  A
    remote GET must therefore preserve them instead of making their absence
    look like a Traffit-side deletion.

    For projected fields we also require the corresponding raw key to be
    present.  This keeps a sparse/tenant-specific GET response from clearing a
    local value merely because the mapper returned its default ``None``.
    Explicit ``null`` remains observable because the raw key is present.
    """
    mapped = traffit_employee_to_candidate(dict(remote), None)
    if base is None:
        fields = (
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
        return {key: mapped.get(key) for key in fields}

    snapshot = dict(base)
    if isinstance(base.get("custom_fields"), Mapping):
        snapshot["custom_fields"] = dict(base["custom_fields"])

    raw_keys_by_local = {
        "name": ("name",),
        "lastname": ("lastname",),
        "email": ("email",),
        "phone": ("mobile", "phone"),
        "linkedin": ("linkedin",),
        "location": ("candidate_location", "location"),
        "status": ("status",),
        "profile_about": ("candidate_about",),
        "languages": ("candidate_languages",),
    }
    for local_name, raw_names in raw_keys_by_local.items():
        if any(raw_name in remote for raw_name in raw_names):
            snapshot[local_name] = mapped.get(local_name)

    # Custom fields are nested, so overlay only keys explicitly represented by
    # this response and retain the remaining shared custom-field baseline.
    mapped_custom = mapped.get("custom_fields")
    mapped_custom = mapped_custom if isinstance(mapped_custom, Mapping) else {}
    custom = dict(snapshot.get("custom_fields") or {})
    for raw_name, raw_value in remote.items():
        if not raw_name.startswith("_"):
            continue
        canonical_name = f"traffit{raw_name}"
        value = mapped_custom.get(canonical_name, raw_value)
        aliases = (
            raw_name,
            canonical_name,
            f"traffit_{raw_name.lstrip('_')}",
        )
        existing_aliases = [name for name in aliases if name in custom]
        for name in existing_aliases or [canonical_name]:
            custom[name] = value
    if custom or "custom_fields" in snapshot:
        snapshot["custom_fields"] = custom
    return snapshot


def _filter_remote_patch(
    remote_patch: Mapping[str, Any], safe_local_patch: Mapping[str, Any]
) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    custom = safe_local_patch.get("custom_fields")
    custom_keys = set(custom) if isinstance(custom, Mapping) else set()
    for remote_name, value in remote_patch.items():
        local_name = TRAFFIT_TO_LOCAL.get(remote_name, remote_name)
        if local_name in safe_local_patch or remote_name in custom_keys:
            safe[remote_name] = value
    return safe


async def _link_for_event(
    db: AsyncSession, event: TraffitOutboxEvent
) -> Optional[TraffitEntityLink]:
    if event.entity_link_id is not None:
        link = await db.get(TraffitEntityLink, event.entity_link_id)
        if link is not None:
            return link
    entity_type = "candidate" if event.candidate_id else event.aggregate_type
    nexus_id = event.candidate_id or event.aggregate_id
    return await db.scalar(
        select(TraffitEntityLink).where(
            TraffitEntityLink.entity_type == entity_type,
            TraffitEntityLink.nexus_entity_id == nexus_id,
        )
    )


async def _employee_id(
    db: AsyncSession, event: TraffitOutboxEvent
) -> tuple[str, Optional[TraffitEntityLink]]:
    explicit = event.payload.get("employee_id") or event.payload.get(
        "traffit_candidate_id"
    )
    link = await _link_for_event(db, event)
    if link is not None and link.status == "detached":
        raise ValueError("Traffit mapping is detached")
    remote_id = explicit or (link.traffit_entity_id if link else None)
    if remote_id is None:
        raise ValueError("candidate has no Traffit entity link")
    return str(remote_id), link


async def _upsert_candidate_link(
    db: AsyncSession,
    event: TraffitOutboxEvent,
    remote_id: str,
    snapshot: Mapping[str, Any],
) -> TraffitEntityLink:
    link = await _link_for_event(db, event)
    if link is not None and link.status == "detached":
        raise ValueError("Traffit mapping is detached")
    now = _utcnow()
    digest = snapshot_hash(snapshot)
    if link is None:
        link = TraffitEntityLink(
            entity_type="candidate",
            nexus_entity_id=event.candidate_id or event.aggregate_id,
            candidate_id=event.candidate_id or event.aggregate_id,
            traffit_entity_id=remote_id,
        )
        db.add(link)
    link.traffit_entity_id = remote_id
    link.status = "synced"
    link.base_snapshot = dict(snapshot)
    link.nexus_snapshot_hash = digest
    link.traffit_snapshot_hash = digest
    link.shared_snapshot_hash = digest
    link.last_synced_at = now
    link.last_seen_at = now
    link.last_direction = "outbound"
    link.last_error = None
    await db.flush()
    event.entity_link_id = link.id
    return link


async def _find_candidate_by_guid(
    client: TraffitClient, guid: str
) -> Optional[dict[str, Any]]:
    filter_ = {"guid": {"value": guid, "comparison": "="}}
    matches = [
        item
        async for item in client.get_paginated(
            "/employees/", page_size=10, filter_=filter_
        )
    ]
    return matches[0] if len(matches) == 1 else None


async def _record_conflict(
    db: AsyncSession,
    event: TraffitOutboxEvent,
    *,
    conflict_type: str,
    field_path: Optional[str] = None,
    base_value: Any = None,
    nexus_value: Any = None,
    traffit_value: Any = None,
    status: str = "open",
) -> TraffitSyncConflict:
    link = await _link_for_event(db, event)
    conflict = TraffitSyncConflict(
        entity_link_id=link.id if link else None,
        outbox_event_id=event.id,
        entity_type=event.aggregate_type,
        nexus_entity_id=event.aggregate_id,
        traffit_entity_id=link.traffit_entity_id if link else None,
        candidate_id=event.candidate_id,
        field_path=field_path,
        conflict_type=conflict_type,
        base_value=base_value,
        nexus_value=nexus_value,
        traffit_value=traffit_value,
        status=status,
    )
    db.add(conflict)
    if link is not None:
        link.status = "conflict" if status == "open" else status
    await db.flush()
    return conflict


async def _candidate_create(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
) -> DispatchResult:
    local_payload, payload, quarantined = await _adapt_candidate_payload(
        db, event, "create"
    )
    missing_required = [
        field for field in quarantined if field.startswith("missing_required:")
    ]
    if missing_required:
        raise ValueError(
            "missing required Traffit fields: " + ", ".join(missing_required)
        )
    local_payload = _drop_quarantined_fields(local_payload, quarantined)
    # Retried create after an ambiguous response: search first, never blindly
    # issue a second POST. The capability is gated by sandbox discovery.
    if event.attempts > 1 and event.payload.get("guid_lookup_enabled"):
        guid = payload.get("guid")
        if guid:
            found = await _find_candidate_by_guid(client, str(guid))
            if found is not None:
                remote_id = str(found["id"])
                await _upsert_candidate_link(db, event, remote_id, local_payload)
                return DispatchResult(
                    "succeeded", {"id": remote_id, "reconciled": True}
                )

    response = await client.post_json("/employees/", payload)
    remote_id: Any = None
    if isinstance(response, Mapping):
        remote_id = response.get("id") or response.get("employee_id")
    if (
        remote_id is None
        and event.payload.get("guid_lookup_enabled")
        and payload.get("guid")
    ):
        found = await _find_candidate_by_guid(client, str(payload["guid"]))
        remote_id = found.get("id") if found else None
    if remote_id is None:
        raise RuntimeError("Traffit candidate create returned no stable id")
    await _upsert_candidate_link(db, event, str(remote_id), local_payload)
    if quarantined:
        await _record_quarantined_fields(db, event, quarantined)
        return DispatchResult(
            "manual_action_required",
            {"id": str(remote_id), "quarantined_fields": quarantined},
            "Some candidate fields require an adapter",
        )
    return DispatchResult("succeeded", {"id": str(remote_id)})


async def _candidate_update(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
) -> DispatchResult:
    remote_id, link = await _employee_id(db, event)
    desired_local_patch, desired_patch, quarantined = await _adapt_candidate_payload(
        db, event, "patch"
    )
    desired_local_patch = _drop_quarantined_fields(desired_local_patch, quarantined)
    current = await client.get_json(f"/employees/{remote_id}")
    if not isinstance(current, Mapping):
        raise RuntimeError("Traffit employee GET returned a non-object")
    base_raw = event.payload.get("base_snapshot") or (
        link.base_snapshot if link else {}
    )
    base = _local_candidate_patch(base_raw) if isinstance(base_raw, Mapping) else {}
    if not base:
        raise ValueError("candidate.update requires a shared baseline")
    nexus_snapshot = dict(base)
    desired_custom = desired_local_patch.get("custom_fields")
    if isinstance(desired_custom, Mapping):
        nexus_snapshot["custom_fields"] = {
            **(
                dict(base.get("custom_fields") or {})
                if isinstance(base.get("custom_fields"), Mapping)
                else {}
            ),
            **dict(desired_custom),
        }
    nexus_snapshot.update(
        {
            field: value
            for field, value in desired_local_patch.items()
            if field != "custom_fields"
        }
    )
    explicit_nexus = event.payload.get("nexus_snapshot")
    if isinstance(explicit_nexus, Mapping):
        explicit_patch = _local_candidate_patch(explicit_nexus)
        explicit_custom = explicit_patch.get("custom_fields")
        if isinstance(explicit_custom, Mapping):
            nexus_snapshot["custom_fields"] = {
                **dict(nexus_snapshot.get("custom_fields") or {}),
                **dict(explicit_custom),
            }
        nexus_snapshot.update(
            {
                field: value
                for field, value in explicit_patch.items()
                if field != "custom_fields"
            }
        )
    remote_snapshot = _remote_to_local_snapshot(current, base=base)
    merge = three_way_merge(dict(base), nexus_snapshot, remote_snapshot)
    if merge.apply_to_nexus and event.candidate_id is not None:
        candidate = await db.get(Candidate, event.candidate_id)
        if candidate is not None:
            for field, value in merge.apply_to_nexus.items():
                if field == "custom_fields" and isinstance(value, Mapping):
                    candidate.custom_fields = {
                        **(candidate.custom_fields or {}),
                        **dict(value),
                    }
                elif field == "status" and value is not None:
                    candidate.status = CandidateStatus(value)
                elif hasattr(candidate, field):
                    setattr(candidate, field, value)
    safe_remote_patch = _filter_remote_patch(desired_patch, merge.apply_to_traffit)
    if safe_remote_patch:
        await client.patch_json(f"/employees/{remote_id}", safe_remote_patch)
    if merge.conflicts:
        # Non-conflicting fields have already been applied above. Retain only
        # conflicted paths on the event so a later admin retry cannot resend
        # unrelated/stale values.
        unresolved_fields: dict[str, Any] = {}
        unresolved_base: dict[str, Any] = {}
        for item in merge.conflicts:
            _set_path(unresolved_fields, item.field_path, item.nexus_value)
            _set_path(unresolved_base, item.field_path, item.traffit_value)
            await _record_conflict(
                db,
                event,
                conflict_type=item.conflict_type,
                field_path=item.field_path,
                base_value=item.base_value,
                nexus_value=item.nexus_value,
                traffit_value=item.traffit_value,
            )
        payload = dict(event.payload or {})
        payload["fields"] = unresolved_fields
        payload["base_snapshot"] = unresolved_base
        event.payload = payload
        event.changed_fields = [item.field_path for item in merge.conflicts]
        return DispatchResult("conflict", message="concurrent candidate update")

    # With no conflicts, ``merged`` is the complete acknowledged state.  In
    # particular it retains baseline-only fields and non-updated nested custom
    # fields instead of replacing them with a partial patch.
    shared = merge.merged
    await _upsert_candidate_link(db, event, remote_id, shared)
    if quarantined:
        await _record_quarantined_fields(db, event, quarantined)
        return DispatchResult(
            "manual_action_required",
            {"id": remote_id, "quarantined_fields": quarantined},
            "Some candidate fields require an adapter",
        )
    return DispatchResult("succeeded", {"id": remote_id})


def _note_content(event: TraffitOutboxEvent) -> str:
    content = str(event.payload.get("content") or "").strip()
    if not content:
        raise ValueError("note content is empty")
    actor = str(event.payload.get("author_name") or "Użytkownik NEXUS").strip()
    marker = f"[NEXUS:{event.event_uuid}]"
    prefix = f"[NEXUS | Autor: {actor}]"
    if event.event_type == "note.correct":
        prefix += " [KOREKTA]"
    if marker in content:
        return content
    return f"{prefix}\n{content}\n{marker}"


async def _note_append(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
) -> DispatchResult:
    remote_id, _ = await _employee_id(db, event)
    # Marker makes a retry discoverable in the append-only activity stream.
    marker = f"[NEXUS:{event.event_uuid}]"
    if event.attempts > 1:
        async for activity in client.get_paginated(
            "/employees/activities", page_size=100
        ):
            employee = activity.get("employee") or {}
            if str(employee.get("id")) != remote_id:
                continue
            if marker in str(activity.get("content") or ""):
                return DispatchResult(
                    "succeeded", {"marker": marker, "reconciled": True}
                )
    await client.post_json(
        f"/employees/{remote_id}/notes", {"content": _note_content(event)}
    )
    return DispatchResult("succeeded", {"marker": marker})


async def _document_bytes(
    db: AsyncSession, payload: Mapping[str, Any]
) -> tuple[bytes, str, str, Optional[int]]:
    document_id = payload.get("document_id")
    if document_id is not None:
        document = await db.scalar(
            select(CandidateDocument)
            .where(CandidateDocument.id == int(document_id))
            .options(undefer(CandidateDocument.file_content))
        )
        if document is None:
            raise ValueError(f"candidate document {document_id} does not exist")
        if document.storage_key:
            content = await asyncio.to_thread(
                object_storage.download_cv, document.storage_key
            )
        else:
            content = document.file_content or b""
        return (
            content,
            str(payload.get("filename") or document.filename),
            str(
                payload.get("content_type")
                or document.content_type
                or "application/octet-stream"
            ),
            document.id,
        )
    encoded = payload.get("content_base64")
    if not encoded:
        raise ValueError("file event requires document_id or content_base64")
    return (
        base64.b64decode(str(encoded), validate=True),
        str(payload.get("filename") or "document.bin"),
        str(payload.get("content_type") or "application/octet-stream"),
        None,
    )


async def _remote_files(
    client: TraffitClient, employee_id: str
) -> list[dict[str, Any]]:
    response = await client.get_json(f"/employees/{employee_id}/files")
    return (
        [item for item in response if isinstance(item, dict)]
        if isinstance(response, list)
        else []
    )


def _matching_file_candidates(
    files: list[dict[str, Any]], filename: str, size: int
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for item in reversed(files):
        remote_name = item.get("filename") or item.get("name")
        remote_size = item.get("size") or item.get("size_bytes")
        if remote_name == filename and (
            remote_size is None or int(remote_size) == size
        ):
            candidates.append(item)
    return candidates


async def _matching_file_by_digest(
    client: TraffitClient,
    employee_id: str,
    files: list[dict[str, Any]],
    filename: str,
    size: int,
    digest: str,
) -> Optional[dict[str, Any]]:
    """Verify bytes; filename+size alone is never accepted as identity."""
    for item in _matching_file_candidates(files, filename, size):
        file_id = item.get("id")
        if file_id is None:
            continue
        response = await client.request(
            "GET",
            f"/employees/{employee_id}/files/{file_id}/content",
            expected_statuses=(200,),
        )
        if hashlib.sha256(response.content).hexdigest() == digest:
            return item
    return None


async def _file_upload(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
) -> DispatchResult:
    remote_id, _ = await _employee_id(db, event)
    content, filename, content_type, document_id = await _document_bytes(
        db, event.payload
    )
    digest = hashlib.sha256(content).hexdigest()
    expected_digest = event.payload.get("content_sha256")
    if expected_digest and str(expected_digest) != digest:
        raise ValueError("candidate document SHA-256 changed after enqueue")

    if document_id is not None:
        existing_link = await db.scalar(
            select(TraffitEntityLink).where(
                TraffitEntityLink.entity_type == "file",
                TraffitEntityLink.nexus_entity_id == document_id,
            )
        )
        if existing_link and existing_link.traffit_entity_id:
            return DispatchResult(
                "succeeded",
                {"id": existing_link.traffit_entity_id, "deduplicated": True},
            )

    remote_files = await _remote_files(client, remote_id)
    match = await _matching_file_by_digest(
        client, remote_id, remote_files, filename, len(content), digest
    )
    if match is None:
        await client.post_multipart(
            f"/employees/{remote_id}/files/",
            filename=filename,
            content=content,
            content_type=content_type,
            field_name="file[file]",
            data={
                "file[isPublic]": "1" if event.payload.get("is_public", True) else "0",
                "dictionary_file_type": str(event.payload.get("file_type") or "CV"),
            },
        )
        match = await _matching_file_by_digest(
            client,
            remote_id,
            await _remote_files(client, remote_id),
            filename,
            len(content),
            digest,
        )

    remote_file_id = (
        str(match.get("id")) if match and match.get("id") is not None else None
    )
    if remote_file_id is None:
        # The upload may have succeeded while the response/manifest remained
        # eventually consistent. Never claim success without a stable remote
        # identity; the retry starts with the SHA-256 manifest reconciliation
        # above and therefore does not blindly upload a duplicate.
        raise RuntimeError(
            "Traffit file upload outcome is ambiguous: uploaded bytes were not "
            "discoverable by SHA-256 in the remote manifest"
        )
    if document_id is not None:
        file_link = TraffitEntityLink(
            entity_type="file",
            nexus_entity_id=document_id,
            traffit_entity_id=f"{remote_id}-{remote_file_id}",
            candidate_id=event.candidate_id,
            status="synced",
            base_snapshot={
                "filename": filename,
                "size_bytes": len(content),
                "content_sha256": digest,
            },
            shared_snapshot_hash=digest,
            nexus_snapshot_hash=digest,
            traffit_snapshot_hash=digest,
            last_synced_at=_utcnow(),
            last_seen_at=_utcnow(),
            last_direction="outbound",
        )
        db.add(file_link)
    return DispatchResult(
        "succeeded", {"id": remote_file_id, "sha256": digest, "size": len(content)}
    )


async def _assignment_exists(
    client: TraffitClient, recruitment_id: str, employee_id: str
) -> bool:
    async for item in client.get_paginated(
        f"/recruitments/{recruitment_id}/employees", page_size=100
    ):
        candidate = (
            item.get("employee") if isinstance(item.get("employee"), dict) else item
        )
        if str(candidate.get("id")) == employee_id:
            return True
    return False


async def _assignment_add(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
) -> DispatchResult:
    employee_id, _ = await _employee_id(db, event)
    recruitment_id = str(event.payload.get("recruitment_id") or "")
    if not recruitment_id:
        raise ValueError("assignment event requires recruitment_id")
    if not await _assignment_exists(client, recruitment_id, employee_id):
        await client.request(
            "POST",
            f"/recruitments/{recruitment_id}/employees/{employee_id}",
            expected_statuses=(200, 201, 204),
        )
    return DispatchResult(
        "succeeded", {"employee_id": employee_id, "recruitment_id": recruitment_id}
    )


def _extract_state_id(candidate_jobs: Any, recruitment_id: str) -> Optional[str]:
    items = candidate_jobs if isinstance(candidate_jobs, list) else [candidate_jobs]
    for item in items:
        if not isinstance(item, Mapping):
            continue
        recruitment = item.get("recruitment") or item.get("job") or item
        rid = recruitment.get("id") if isinstance(recruitment, Mapping) else None
        if str(rid) != recruitment_id:
            continue
        state = item.get("state") or item.get("current_state") or {}
        state_id = state.get("id") if isinstance(state, Mapping) else state
        return str(state_id) if state_id is not None else None
    return None


async def _stage_action(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
) -> DispatchResult:
    employee_id, _ = await _employee_id(db, event)
    recruitment_id = str(event.payload.get("recruitment_id") or "")
    if not recruitment_id:
        raise ValueError("stage event requires recruitment_id")
    jobs = await client.get_json(f"/employees/{employee_id}/recruitments")
    current_state = _extract_state_id(jobs, recruitment_id)
    expected_state = event.payload.get("expected_state_id")
    requested_state = event.payload.get("state_id")
    # The prior request may have succeeded but its response was lost. A target
    # state observed on retry is positive reconciliation, not a conflict.
    if event.event_type == "stage.move" and requested_state is not None:
        if current_state == str(requested_state):
            return DispatchResult(
                "succeeded",
                {
                    "employee_id": employee_id,
                    "recruitment_id": recruitment_id,
                    "state_id": current_state,
                    "reconciled": True,
                },
            )
    if expected_state is not None and current_state != str(expected_state):
        await _record_conflict(
            db,
            event,
            conflict_type="stage_divergence",
            field_path="stage_id",
            base_value=str(expected_state),
            nexus_value=str(event.payload.get("state_id") or "rejected"),
            traffit_value=current_state,
        )
        return DispatchResult("conflict", message="Traffit stage changed concurrently")

    if event.event_type == "stage.reject":
        rejection_id = event.payload.get("rejection_id")
        local_reason_id = event.payload.get("local_rejection_reason_id")
        if rejection_id is None and local_reason_id is not None:
            rejection_id = await db.scalar(
                select(RejectionReason.external_id).where(
                    RejectionReason.id == int(local_reason_id),
                    RejectionReason.external_source == "traffit",
                )
            )
        if rejection_id is None:
            await _record_conflict(
                db,
                event,
                conflict_type="rejection_reason_mapping_missing",
                field_path="rejection_reason_id",
                nexus_value={"local_rejection_reason_id": local_reason_id},
                traffit_value=None,
                status="manual_action_required",
            )
            return DispatchResult(
                "manual_action_required",
                message="Traffit rejection reason mapping is required",
            )
        await client.post_json(
            f"/employees/{employee_id}/recruitments/{recruitment_id}/states/_move_to_reject_state",
            {"rejection_id": rejection_id},
        )
        target = "rejected"
    else:
        state_id = event.payload.get("state_id")
        if state_id is None:
            raise ValueError("stage.move requires state_id")
        await client.post_json(
            f"/employees/{employee_id}/recruitments/{recruitment_id}/states/{state_id}/_move",
            {},
        )
        target = str(state_id)
    return DispatchResult(
        "succeeded",
        {
            "employee_id": employee_id,
            "recruitment_id": recruitment_id,
            "state_id": target,
        },
    )


async def _manual_action(db: AsyncSession, event: TraffitOutboxEvent) -> DispatchResult:
    message = f"Traffit API does not support safe symmetric {event.event_type}"
    existing = await db.scalar(
        select(TraffitSyncConflict).where(
            TraffitSyncConflict.outbox_event_id == event.id,
            TraffitSyncConflict.status.in_(("open", "manual_action_required")),
        )
    )
    if existing is None:
        await _record_conflict(
            db,
            event,
            conflict_type="unsupported_delete",
            field_path="deleted_at",
            nexus_value=event.payload,
            status="manual_action_required",
        )
    else:
        link = await _link_for_event(db, event)
        if link is not None:
            link.status = "manual_action_required"
    return DispatchResult("manual_action_required", message=message)


async def dispatch_event(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
) -> DispatchResult:
    if event.event_type in MANUAL_EVENT_TYPES:
        return await _manual_action(db, event)
    if event.event_type == "candidate.create":
        return await _candidate_create(db, client, event)
    if event.event_type == "candidate.update":
        return await _candidate_update(db, client, event)
    if event.event_type in {"note.append", "note.correct"}:
        return await _note_append(db, client, event)
    if event.event_type == "file.upload":
        return await _file_upload(db, client, event)
    if event.event_type == "assignment.add":
        return await _assignment_add(db, client, event)
    if event.event_type in {"stage.move", "stage.reject"}:
        return await _stage_action(db, client, event)
    raise ValueError(f"unsupported outbound event type: {event.event_type}")


async def claim_outbox_events(
    db: AsyncSession,
    *,
    worker_id: str,
    limit: int = 20,
    include_shadowed: bool = False,
) -> list[TraffitOutboxEvent]:
    """Claim due events while preserving ordering within an aggregate."""
    now = _utcnow()
    earlier = aliased(TraffitOutboxEvent)
    same_partition = or_(
        and_(
            TraffitOutboxEvent.candidate_id.is_not(None),
            earlier.candidate_id == TraffitOutboxEvent.candidate_id,
        ),
        and_(
            TraffitOutboxEvent.candidate_id.is_(None),
            earlier.candidate_id.is_(None),
            earlier.aggregate_type == TraffitOutboxEvent.aggregate_type,
            earlier.aggregate_id == TraffitOutboxEvent.aggregate_id,
        ),
    )
    terminal_order_statuses = set(TERMINAL_ORDER_STATUSES)
    if include_shadowed:
        terminal_order_statuses.discard("shadowed")
        terminal_order_statuses.discard("dry_run")
    preceding_unfinished = exists(
        select(earlier.id).where(
            same_partition,
            earlier.sequence < TraffitOutboxEvent.sequence,
            earlier.status.not_in(terminal_order_statuses),
        )
    )
    rows = list(
        (
            await db.scalars(
                select(TraffitOutboxEvent)
                .where(
                    TraffitOutboxEvent.status.in_(
                        ("pending", "retry", "shadowed", "dry_run")
                        if include_shadowed
                        else ("pending", "retry")
                    ),
                    or_(
                        TraffitOutboxEvent.next_attempt_at.is_(None),
                        TraffitOutboxEvent.next_attempt_at <= now,
                    ),
                    TraffitOutboxEvent.attempts < TraffitOutboxEvent.max_attempts,
                    ~preceding_unfinished,
                )
                .order_by(
                    TraffitOutboxEvent.priority.asc(),
                    TraffitOutboxEvent.next_attempt_at.asc(),
                    TraffitOutboxEvent.id.asc(),
                )
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


async def recover_stale_outbox_locks(
    db: AsyncSession,
    *,
    stale_after: timedelta = timedelta(minutes=5),
) -> int:
    cutoff = _utcnow() - stale_after
    rows = list(
        (
            await db.scalars(
                select(TraffitOutboxEvent).where(
                    TraffitOutboxEvent.status == "processing",
                    TraffitOutboxEvent.locked_at < cutoff,
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


async def _enqueue_audit_note(db: AsyncSession, event: TraffitOutboxEvent) -> None:
    if event.event_type not in {
        "candidate.update",
        "file.upload",
        "assignment.add",
        "stage.move",
        "stage.reject",
    }:
        return
    audit = event.payload.get("audit_note")
    if not audit:
        changed = list(event.changed_fields or ())
        label = ", ".join(changed) if changed else event.event_type
        audit = f"Akcja w NEXUS: {label}"
    remote_id, _ = await _employee_id(db, event)
    await _enqueue_command(
        db,
        OutboxCommand(
            event_type="note.append",
            aggregate_type="note",
            aggregate_id=event.id,
            candidate_id=event.candidate_id,
            entity_link_id=event.entity_link_id,
            actor_user_id=event.actor_user_id,
            payload={
                "employee_id": remote_id,
                "content": str(audit),
                "author_name": event.payload.get("actor_name") or "Użytkownik NEXUS",
            },
            idempotency_key=f"{event.idempotency_key}:audit",
            priority=event.priority + 1,
        ),
    )


async def process_claimed_event(
    db: AsyncSession,
    client: TraffitClient,
    event: TraffitOutboxEvent,
    *,
    dry_run: bool,
) -> DispatchResult:
    now = _utcnow()
    try:
        if dry_run:
            result = DispatchResult(
                "shadowed",
                {
                    "event_type": event.event_type,
                    "changed_fields": list(event.changed_fields or ()),
                },
            )
        else:
            result = await dispatch_event(db, client, event)
        event.status = result.status
        event.remote_response = result.remote_response
        event.last_error = result.message
        event.processed_at = now
        event.next_attempt_at = None
        event.locked_at = None
        event.locked_by = None
        if result.status == "succeeded":
            await _enqueue_audit_note(db, event)
        return result
    except TraffitAPIError as exc:
        if exc.status_code == 400 and event.event_type in {
            "candidate.create",
            "candidate.update",
        }:
            sample_id = event.payload.get("employee_id") or event.payload.get(
                "traffit_candidate_id"
            )
            if sample_id is None:
                link = await _link_for_event(db, event)
                sample_id = link.traffit_entity_id if link else None
            try:
                await refresh_candidate_contracts(
                    db, client, sample_employee_id=sample_id
                )
            except Exception:  # noqa: BLE001 - preserve original validation error
                logger.exception("Traffit metadata refresh after HTTP 400 failed")

        ambiguous_create = (
            event.event_type == "candidate.create"
            and exc.status_code >= 500
            and not event.payload.get("guid_lookup_enabled")
        )
        if ambiguous_create:
            await _record_conflict(
                db,
                event,
                conflict_type="ambiguous_candidate_create",
                nexus_value={"changed_fields": list(event.changed_fields or ())},
                traffit_value={"status": exc.status_code, "body": exc.body[:500]},
                status="manual_action_required",
            )
            event.status = "manual_action_required"
            event.processed_at = now
        elif exc.status_code in {401, 429} or exc.retryable:
            _schedule_retry(event, str(exc), exc.retry_after_s)
        elif 400 <= exc.status_code < 500:
            await _record_conflict(
                db,
                event,
                conflict_type="remote_validation_error",
                nexus_value={"changed_fields": list(event.changed_fields or ())},
                traffit_value={"status": exc.status_code, "body": exc.body[:500]},
                status="manual_action_required",
            )
            event.status = "manual_action_required"
            event.processed_at = now
        else:
            _schedule_retry(event, str(exc), exc.retry_after_s)
        event.last_error = str(exc)[:2000]
        event.locked_at = None
        event.locked_by = None
        return DispatchResult(event.status, message=event.last_error)
    except (httpx.TransportError, httpx.TimeoutException, RuntimeError) as exc:
        if event.event_type == "candidate.create" and not event.payload.get(
            "guid_lookup_enabled"
        ):
            await _record_conflict(
                db,
                event,
                conflict_type="ambiguous_candidate_create",
                nexus_value={"changed_fields": list(event.changed_fields or ())},
                traffit_value={"error": str(exc)[:500]},
                status="manual_action_required",
            )
            event.status = "manual_action_required"
            event.last_error = (
                "Candidate create outcome is ambiguous and GUID lookup was not "
                f"validated: {exc}"
            )[:2000]
            event.processed_at = now
            event.locked_at = None
            event.locked_by = None
        else:
            _schedule_retry(event, str(exc))
        return DispatchResult(event.status, message=event.last_error)
    except (TypeError, ValueError) as exc:
        await _record_conflict(
            db,
            event,
            conflict_type="invalid_outbox_payload",
            nexus_value={"changed_fields": list(event.changed_fields or ())},
            traffit_value={"error": str(exc)[:500]},
            status="manual_action_required",
        )
        event.status = "manual_action_required"
        event.last_error = str(exc)[:2000]
        event.processed_at = now
        event.locked_at = None
        event.locked_by = None
        return DispatchResult(event.status, message=event.last_error)
    except Exception as exc:  # noqa: BLE001 - isolate one poison queue item
        logger.exception("Unexpected Traffit outbox failure for event %s", event.id)
        _schedule_retry(event, str(exc))
        return DispatchResult(event.status, message=event.last_error)


def _schedule_retry(
    event: TraffitOutboxEvent,
    message: str,
    retry_after_s: Optional[float] = None,
) -> None:
    event.last_error = message[:2000]
    event.locked_at = None
    event.locked_by = None
    if event.attempts >= event.max_attempts:
        event.status = "dead_letter"
        event.processed_at = _utcnow()
        event.next_attempt_at = None
        return
    wait = retry_after_s
    if wait is None:
        wait = min(2 ** max(event.attempts - 1, 0), 900) + random.uniform(0, 1)
    event.status = "retry"
    event.next_attempt_at = _utcnow() + timedelta(seconds=wait)


async def run_outbound_batch(
    db: AsyncSession,
    client: TraffitClient,
    *,
    worker_id: str,
    dry_run: bool,
    limit: int = 20,
) -> dict[str, int]:
    await recover_stale_outbox_locks(db)
    events = await claim_outbox_events(
        db,
        worker_id=worker_id,
        limit=limit,
        include_shadowed=not dry_run,
    )
    # Make claims visible so another worker cannot recover/reclaim them.
    await db.commit()
    stats: dict[str, int] = {"claimed": len(events)}
    for event in events:
        event_id = event.id
        try:
            result = await process_claimed_event(db, client, event, dry_run=dry_run)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - recover failed DB transaction
            logger.exception("Failed to persist Traffit outbox event %s", event_id)
            await db.rollback()
            recovered = await db.get(TraffitOutboxEvent, event_id)
            if recovered is None:
                continue
            _schedule_retry(recovered, f"worker transaction failed: {exc}")
            result = DispatchResult(recovered.status, message=recovered.last_error)
            await db.commit()
        stats[result.status] = stats.get(result.status, 0) + 1
    return stats
