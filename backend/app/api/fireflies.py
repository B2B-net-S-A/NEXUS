"""
Fireflies Integration API.
GET /api/fireflies/sync        — trigger manual transcript sync
GET /api/fireflies/transcripts — list recent meeting notes from Fireflies
GET /api/fireflies/status      — current integration status
"""

from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.note import Note, NoteType
from app.api.deps import OperationalUser
from app.services.fireflies_sync import sync_fireflies_transcripts, get_sync_status

router = APIRouter()


@router.get("/fireflies/sync")
async def trigger_fireflies_sync(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger a Fireflies transcript sync.
    Best-effort: returns result even if partial failure.

    Mutating (writes meeting notes, hits the external Fireflies API), so gated
    to OperationalUser — the read-only ``user`` viewer must not be able to
    kick off a global sync (M6-P0.11).
    """
    result = await sync_fireflies_transcripts(db)
    return result


@router.get("/fireflies/transcripts")
async def list_fireflies_transcripts(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    candidate_id: Optional[int] = Query(None),
    limit: int = Query(20, ge=1, le=100),
):
    """
    List recent meeting notes created from Fireflies sync.
    Optionally filter by candidate_id.
    """
    q = select(Note).where(Note.note_type == NoteType.meeting)
    if candidate_id is not None:
        q = q.where(Note.candidate_id == candidate_id)
    q = q.order_by(desc(Note.created_at)).limit(limit)
    result = await db.execute(q)
    notes = result.scalars().all()

    return [
        {
            "id": n.id,
            "title": n.content.split("\n")[0].replace("# ", "").strip()
            if n.content
            else "Spotkanie",
            "candidate_id": n.candidate_id,
            "created_at": n.created_at.isoformat() if n.created_at else None,
            "preview": (n.content or "")[:200] + "..."
            if len(n.content or "") > 200
            else (n.content or ""),
        }
        for n in notes
    ]


@router.get("/fireflies/status")
async def fireflies_status(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Get Fireflies integration status: last sync time, transcript count, errors.
    """
    import os

    status = get_sync_status()

    # Count total meeting notes in DB
    result = await db.execute(select(Note).where(Note.note_type == NoteType.meeting))
    total_notes = len(result.scalars().all())

    return {
        "connected": bool(os.getenv("FIREFLIES_API_KEY")),
        "last_synced_at": status.get("last_synced_at"),
        "transcript_count": total_notes,
        "error": status.get("error"),
    }
