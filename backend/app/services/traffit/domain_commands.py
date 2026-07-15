"""Central capture points for Nexus-originated Traffit domain mutations.

Every HTTP path that changes a synchronized domain object calls this module
before its transaction is committed.  The helpers deliberately do not commit:
the local mutation and its outbox row therefore succeed or roll back together.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Iterable, Mapping, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.models.job import Job
from app.models.note import Note
from app.models.pipeline_template import PipelineStageDef, RejectionReason
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.traffit_integration import (
    TraffitEntityLink,
    TraffitOutboxEvent,
    TraffitSyncConflict,
)
from app.services.traffit.outbox import enqueue_traffit_event


_CANDIDATE_SYNC_FIELDS = (
    "name",
    "lastname",
    "email",
    "phone",
    "location",
    "city",
    "country",
    "region",
    "linkedin",
    "status",
    "source",
    "profile_about",
    "availability_date",
    "availability_status",
    "languages",
    "custom_fields",
)


def jsonable(value: Any) -> Any:
    """Convert ORM/Pydantic values to a JSONB-safe structure."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(child) for child in value]
    return value


def candidate_snapshot(
    candidate: Candidate,
    *,
    fields: Optional[Iterable[str]] = None,
) -> dict[str, Any]:
    names = tuple(fields or _CANDIDATE_SYNC_FIELDS)
    return {
        name: jsonable(getattr(candidate, name, None))
        for name in names
        if hasattr(candidate, name)
    }


async def get_entity_link(
    db: AsyncSession,
    entity_type: str,
    nexus_entity_id: int,
) -> Optional[TraffitEntityLink]:
    return await db.scalar(
        select(TraffitEntityLink).where(
            TraffitEntityLink.entity_type == entity_type,
            TraffitEntityLink.nexus_entity_id == nexus_entity_id,
        )
    )


async def candidate_is_traffit_linked(
    db: AsyncSession,
    candidate_id: Optional[int],
) -> bool:
    if candidate_id is None:
        return False
    link = await get_entity_link(db, "candidate", candidate_id)
    if link is not None and link.status == "detached":
        return False
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is not None and candidate.external_source == "traffit":
        return True
    return link is not None


async def capture_candidate_created(
    db: AsyncSession,
    candidate: Candidate,
    *,
    actor_id: Optional[int],
) -> Optional[TraffitOutboxEvent]:
    fields = candidate_snapshot(candidate)
    return await enqueue_traffit_event(
        db,
        "candidate.create",
        "candidate",
        candidate.id,
        {"fields": fields},
        actor_id=actor_id,
        candidate_id=candidate.id,
        changed_fields=fields.keys(),
        priority=10,
    )


async def capture_candidate_updated(
    db: AsyncSession,
    candidate: Candidate,
    patch: Mapping[str, Any],
    *,
    actor_id: Optional[int],
) -> Optional[TraffitOutboxEvent]:
    json_patch = jsonable(dict(patch))
    return await enqueue_traffit_event(
        db,
        "candidate.update",
        "candidate",
        candidate.id,
        {"fields": json_patch},
        actor_id=actor_id,
        candidate_id=candidate.id,
        changed_fields=json_patch.keys(),
        priority=10,
    )


async def capture_note_appended(
    db: AsyncSession,
    note: Note,
    *,
    actor_id: Optional[int],
    author_name: Optional[str] = None,
    correction: bool = False,
) -> Optional[TraffitOutboxEvent]:
    if note.candidate_id is None:
        return None
    content = note.content
    note_type = jsonable(note.note_type)
    if note_type in {"call", "email", "meeting"} and len(content) > 2000:
        content = f"{content[:2000].rstrip()}\n\n[Podsumowanie skrócone przez NEXUS]"
    return await enqueue_traffit_event(
        db,
        "note.correct" if correction else "note.append",
        "note",
        note.id,
        {
            "content": content,
            "author_name": author_name,
            "note_type": note_type,
            "supersedes_note_id": note.supersedes_note_id,
        },
        actor_id=actor_id,
        candidate_id=note.candidate_id,
        changed_fields=("content", "note_type"),
        priority=20,
    )


async def capture_file_uploaded(
    db: AsyncSession,
    document: CandidateDocument,
    *,
    actor_id: Optional[int],
) -> Optional[TraffitOutboxEvent]:
    return await enqueue_traffit_event(
        db,
        "file.upload",
        "file",
        document.id,
        {
            "document_id": document.id,
            "filename": document.filename,
            "content_type": document.content_type,
            "content_sha256": document.content_sha256,
            "is_public": False,
        },
        actor_id=actor_id,
        candidate_id=document.candidate_id,
        changed_fields=("content_sha256", "filename"),
        priority=20,
    )


async def _stage_remote_ids(
    db: AsyncSession,
    stage: CandidateStage,
) -> tuple[Optional[str], Optional[str]]:
    state_id: Optional[str] = None
    if stage.stage_def_id is not None:
        state_id = await db.scalar(
            select(PipelineStageDef.external_id).where(
                PipelineStageDef.id == stage.stage_def_id,
                PipelineStageDef.external_source == "traffit",
            )
        )
    if state_id is None:
        template_id = await db.scalar(
            select(Job.pipeline_template_id).where(Job.id == stage.job_id)
        )
        if template_id is not None:
            state_id = await db.scalar(
                select(PipelineStageDef.external_id).where(
                    PipelineStageDef.template_id == template_id,
                    PipelineStageDef.legacy_enum_value == stage.stage.value,
                    PipelineStageDef.external_source == "traffit",
                )
            )

    previous = await db.scalar(
        select(CandidateStage)
        .where(
            CandidateStage.candidate_id == stage.candidate_id,
            CandidateStage.job_id == stage.job_id,
            CandidateStage.id != stage.id,
            CandidateStage.moved_at <= stage.moved_at,
        )
        .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
        .limit(1)
    )
    expected_state_id: Optional[str] = None
    if previous is not None and previous.stage_def_id is not None:
        expected_state_id = await db.scalar(
            select(PipelineStageDef.external_id).where(
                PipelineStageDef.id == previous.stage_def_id,
                PipelineStageDef.external_source == "traffit",
            )
        )
    if previous is not None and expected_state_id is None:
        template_id = await db.scalar(
            select(Job.pipeline_template_id).where(Job.id == stage.job_id)
        )
        if template_id is not None:
            expected_state_id = await db.scalar(
                select(PipelineStageDef.external_id).where(
                    PipelineStageDef.template_id == template_id,
                    PipelineStageDef.legacy_enum_value == previous.stage.value,
                    PipelineStageDef.external_source == "traffit",
                )
            )
    return state_id, expected_state_id


async def capture_assignment_added(
    db: AsyncSession,
    stage: CandidateStage,
    job: Job,
    *,
    actor_id: Optional[int],
) -> Optional[TraffitOutboxEvent]:
    if job.external_source != "traffit" or not job.external_id:
        return None
    return await enqueue_traffit_event(
        db,
        "assignment.add",
        "candidate_assignment",
        stage.id,
        {"recruitment_id": job.external_id},
        actor_id=actor_id,
        candidate_id=stage.candidate_id,
        changed_fields=("recruitment_id",),
        priority=20,
    )


async def capture_stage_moved(
    db: AsyncSession,
    stage: CandidateStage,
    job: Job,
    *,
    actor_id: Optional[int],
) -> Optional[TraffitOutboxEvent]:
    if job.external_source != "traffit" or not job.external_id:
        return None
    state_id, expected_state_id = await _stage_remote_ids(db, stage)
    payload: dict[str, Any] = {
        "recruitment_id": job.external_id,
        "state_id": state_id,
        "expected_state_id": expected_state_id,
        "candidate_stage_id": stage.id,
    }
    event_type = "stage.move"
    if stage.stage in {PipelineStage.rejected, PipelineStage.withdrawn}:
        event_type = "stage.reject"
        rejection_id: Optional[str] = None
        if stage.rejection_reason_id is not None:
            rejection_id = await db.scalar(
                select(RejectionReason.external_id).where(
                    RejectionReason.id == stage.rejection_reason_id,
                    RejectionReason.external_source == "traffit",
                )
            )
        payload["local_rejection_reason_id"] = stage.rejection_reason_id
        payload["rejection_id"] = rejection_id
    return await enqueue_traffit_event(
        db,
        event_type,
        "candidate_stage",
        stage.id,
        payload,
        actor_id=actor_id,
        candidate_id=stage.candidate_id,
        changed_fields=("stage", "rejection_reason_id"),
        priority=10,
    )


async def capture_delete_requested(
    db: AsyncSession,
    *,
    event_type: str,
    aggregate_type: str,
    aggregate_id: int,
    candidate_id: Optional[int],
    actor_id: Optional[int],
    details: Mapping[str, Any],
) -> Optional[TraffitOutboxEvent]:
    if event_type not in {
        "candidate.delete_requested",
        "note.delete_requested",
        "file.delete_requested",
        "assignment.remove_requested",
    }:
        raise ValueError(f"Unsupported manual action event: {event_type}")
    return await enqueue_traffit_event(
        db,
        event_type,
        aggregate_type,
        aggregate_id,
        jsonable(dict(details)),
        actor_id=actor_id,
        candidate_id=candidate_id,
        changed_fields=("deletion_requested",),
        priority=10,
    )


async def request_manual_action(
    db: AsyncSession,
    *,
    entity_type: str,
    nexus_entity_id: int,
    candidate_id: Optional[int],
    traffit_entity_id: Optional[str],
    conflict_type: str,
    actor_id: Optional[int],
    details: Mapping[str, Any],
    outbox_event_id: Optional[int] = None,
) -> TraffitSyncConflict:
    """Persist a non-destructive delete/detach request for admin review."""
    existing = await db.scalar(
        select(TraffitSyncConflict).where(
            TraffitSyncConflict.entity_type == entity_type,
            TraffitSyncConflict.nexus_entity_id == nexus_entity_id,
            TraffitSyncConflict.conflict_type == conflict_type,
            TraffitSyncConflict.status.in_(("open", "manual_action_required")),
        )
    )
    if existing is not None:
        if outbox_event_id is not None and existing.outbox_event_id is None:
            existing.outbox_event_id = outbox_event_id
        return existing
    link = await get_entity_link(db, entity_type, nexus_entity_id)
    conflict = TraffitSyncConflict(
        entity_link_id=link.id if link else None,
        outbox_event_id=outbox_event_id,
        entity_type=entity_type,
        nexus_entity_id=nexus_entity_id,
        traffit_entity_id=(
            link.traffit_entity_id
            if link and link.traffit_entity_id
            else traffit_entity_id
        ),
        candidate_id=candidate_id,
        conflict_type=conflict_type,
        base_value=link.base_snapshot if link else None,
        nexus_value={"requested_by": actor_id, **jsonable(dict(details))},
        status="manual_action_required",
    )
    db.add(conflict)
    await db.flush()
    return conflict
