from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.note import NoteType


class NoteCreate(BaseModel):
    content: str
    note_type: NoteType = NoteType.general
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None


class NoteUpdate(BaseModel):
    content: Optional[str] = None
    note_type: Optional[NoteType] = None


class NoteResponse(BaseModel):
    id: int
    content: str
    note_type: NoteType
    candidate_id: Optional[int]
    job_id: Optional[int]
    author_id: Optional[int]
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class NoteList(BaseModel):
    items: list[NoteResponse]
    total: int
