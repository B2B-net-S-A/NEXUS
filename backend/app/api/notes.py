from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.note import Note
from app.models.candidate import Candidate
from app.models.user_activity import UserActivity, UserActionType
from app.schemas.note import NoteCreate, NoteList, NoteResponse, NoteUpdate
from app.api.deps import CurrentUser

router = APIRouter()


@router.get("", response_model=NoteList)
async def list_notes(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    candidate_id: Optional[int] = None,
    job_id: Optional[int] = None,
):
    query = select(Note)
    if candidate_id:
        query = query.where(Note.candidate_id == candidate_id)
    if job_id:
        query = query.where(Note.job_id == job_id)
    query = query.order_by(Note.created_at.desc())
    total = (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
    result = await db.execute(query)
    return NoteList(items=list(result.scalars().all()), total=total)


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
async def create_note(data: NoteCreate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    note = Note(**data.model_dump(), author_id=current_user.id)
    db.add(note)
    await db.flush()
    # Update candidate notes_count
    if data.candidate_id:
        result = await db.execute(select(Candidate).where(Candidate.id == data.candidate_id))
        candidate = result.scalar_one_or_none()
        if candidate:
            candidate.notes_count = (candidate.notes_count or 0) + 1

    # Track activity for leaderboard
    entity_id = data.candidate_id or data.job_id or note.id
    entity_type = "candidate" if data.candidate_id else ("job" if data.job_id else "note")
    db.add(UserActivity(
        user_id=current_user.id,
        action_type=UserActionType.note_added,
        entity_type=entity_type,
        entity_id=entity_id,
        details={"note_id": note.id, "note_type": data.note_type.value if data.note_type else None},
    ))

    await db.refresh(note)
    return note


@router.get("/{note_id}", response_model=NoteResponse)
async def get_note(note_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


@router.patch("/{note_id}", response_model=NoteResponse)
async def update_note(
    note_id: int, data: NoteUpdate, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(note, k, v)
    await db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_note(note_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Note).where(Note.id == note_id))
    note = result.scalar_one_or_none()
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    await db.delete(note)
