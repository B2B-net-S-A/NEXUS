from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from app.models.note import NoteType
from app.schemas.integration import IntegrationSyncState


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
    external_source: Optional[str] = None
    external_id: Optional[str] = None
    source_created_at: Optional[datetime] = None
    source_updated_at: Optional[datetime] = None
    source_deleted_at: Optional[datetime] = None
    supersedes_note_id: Optional[int] = None
    integration: Optional[IntegrationSyncState] = None

    model_config = {"from_attributes": True}


class NoteList(BaseModel):
    items: list[NoteResponse]
    total: int


class EnrichedNoteResponse(NoteResponse):
    """Note + denormalized display fields for the Notatki tab.

    `author_name`/`author_email` come from a User outerjoin (NULL for legacy
    Traffit imports). `content_rendered` resolves `$$user_NN$$` Traffit mention
    tokens to "@Imię Nazwisko"; raw `content` stays intact for editing.
    `job_title` shows which recruitment a note is pinned to (NULL = general).
    """

    author_name: Optional[str] = None
    author_email: Optional[str] = None
    content_rendered: Optional[str] = None
    job_title: Optional[str] = None


class EnrichedNoteList(BaseModel):
    items: list[EnrichedNoteResponse]
    total: int
